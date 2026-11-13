import io
import time
import threading
import uuid

import pytest
from fastapi.testclient import TestClient
from reportlab.pdfgen import canvas

from app.config import Settings
from app.main import create_app


def pdf(text='Quy trinh dang ky: Nop ho so tai phong dao tao.', pages=1):
    output = io.BytesIO()
    c = canvas.Canvas(output)
    for _ in range(pages):
        c.drawString(40, 800, text)
        c.showPage()
    c.save()
    return output.getvalue()


@pytest.fixture
def app(tmp_path):
    return create_app(Settings(data_dir=tmp_path))


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


def upload(client, content=None, key=None, name='guide.pdf'):
    return client.post('/api/v1/documents', headers={'Idempotency-Key': key or str(uuid.uuid4())},
                       files={'file': (name, content if content is not None else pdf(), 'application/pdf')})


def wait(client, ident, expected='ready'):
    for _ in range(120):
        response = client.get(f'/api/v1/documents/{ident}/status')
        if expected == 'deleted' and response.status_code == 410:
            return response
        if response.status_code == 200:
            status = response.json()['status']
            if status == expected:
                return response
            if status in {'failed', 'delete_failed'} and status != expected:
                pytest.fail(str(response.json()))
        time.sleep(.03)
    pytest.fail(f'Timeout waiting for {ident}: {response.text}')


def test_full_upload_search_chat_source_and_delete(client):
    response = upload(client)
    assert response.status_code == 202, response.text
    assert response.headers['X-Request-ID'] == response.json()['request_id']
    ident = response.json()['document']['document_id']
    status = wait(client, ident).json()
    version = status['available_index_versions'][0]
    request = {'query': 'Quy trinh dang ky ho so', 'document_ids': [ident], 'retrieval_config': {'top_k': 10}}
    result = client.post('/api/v1/search', json=request)
    assert result.status_code == 200, result.text
    hit = result.json()['hits'][0]
    assert hit['document_id'] == ident and hit['source_spans'][0]['page_number'] == 1
    assert result.json()['retrieval_trace']['demo_backends']
    chat = client.post('/api/v1/chat', json={'question': request['query'], 'document_ids': [ident]})
    assert chat.status_code == 200, chat.text
    assert chat.json()['status'] == 'answered'
    assert chat.json()['confidence'] is None
    citation = chat.json()['citations'][0]
    source = client.get(citation['source_url'])
    assert source.status_code == 200 and source.content.startswith(b'%PDF')
    assert client.get(f'/api/v1/documents/{ident}/source?document_version=2').status_code == 404
    no_evidence = client.post('/api/v1/chat', json={'question': 'orbital astrophysics galaxy fusion'})
    assert no_evidence.json()['status'] == 'insufficient_evidence'
    assert client.delete(f'/api/v1/documents/{ident}').status_code == 202
    assert client.post('/api/v1/search', json={'query': 'ho so', 'index_version': version}).status_code == 409
    wait(client, ident, 'deleted')
    assert client.delete(f'/api/v1/documents/{ident}').status_code == 204
    assert client.get(citation['source_url']).status_code == 410
    assert client.get('/api/v1/documents').json()['items'] == []


def test_idempotency_and_scope_validation(client):
    first = upload(client, key='once')
    ident = first.json()['document']['document_id']
    # ReportLab varies document bytes between calls; replay must reuse same bytes.
    content = pdf('unique')
    second = upload(client, content, key='same')
    assert upload(client, content, key='same').status_code == 200
    assert upload(client, pdf('other'), key='same').status_code == 409
    wait(client, ident)
    assert client.post('/api/v1/search', json={'query': 'dang ky', 'document_ids': [ident, 'unknown']}).status_code == 404
    assert client.post(f'/api/v1/documents/{ident}/retry', headers={'Idempotency-Key':'retry'}).status_code == 409
    assert second.status_code == 202


@pytest.mark.parametrize('payload', [
    {'question':' '}, {'question':'ok','document_ids':[]}, {'question':'ok','document_ids':None},
    {'question':'ok','retrieval_config':{'dense':False,'bm25':False}},
    {'question':'ok','retrieval_config':{'top_k':0}}, {'question':'ok','extra':True},
    {'question':'ok','document_ids':['x','x']}, {'question':'ok','retrieval_config':{'dense':'false'}},
])
def test_invalid_contract(client, payload):
    response = client.post('/api/v1/chat', json=payload)
    assert response.status_code == 422
    assert response.json()['status'] == 'error'


def test_invalid_files_and_pagination(client):
    assert upload(client, b'not pdf').status_code == 422
    assert client.post('/api/v1/documents', files={'file':('x.pdf',pdf(),'application/pdf')}).status_code == 422
    one = upload(client, pdf('first')).json()['document']['document_id']
    two = upload(client, pdf('second')).json()['document']['document_id']
    page = client.get('/api/v1/documents?limit=1').json()
    assert page['next_cursor']
    next_page = client.get('/api/v1/documents', params={'limit':1, 'cursor':page['next_cursor']}).json()
    assert {page['items'][0]['document_id'], next_page['items'][0]['document_id']} == {one,two}
    assert client.get('/api/v1/documents', params={'cursor':page['next_cursor'], 'status':'ready'}).status_code == 400


def test_delete_during_build_does_not_resurrect(app, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    from app.retrieval import Engine
    build = Engine.build
    def blocked(self, *args, **kwargs):
        entered.set()
        release.wait(5)
        return build(self, *args, **kwargs)
    monkeypatch.setattr(Engine, 'build', blocked)
    with TestClient(app) as client:
        ident = upload(client).json()['document']['document_id']
        assert entered.wait(3)
        client.delete(f'/api/v1/documents/{ident}')
        release.set()
        wait(client, ident, 'deleted')
        with app.state.store.db() as db:
            assert not db.execute("SELECT 1 FROM generations WHERE status='published'").fetchone()
        assert not (app.state.store.docdir(ident)).exists()


def test_delete_failure_can_retry_without_exposing_content(app, monkeypatch):
    with TestClient(app) as client:
        ident = upload(client).json()['document']['document_id']
        wait(client, ident)
        original = app.state.store.engine.delete
        def fail(*args):
            raise OSError('simulated external store outage')
        monkeypatch.setattr(app.state.store.engine, 'delete', fail)
        client.delete(f'/api/v1/documents/{ident}')
        wait(client, ident, 'delete_failed')
        assert client.get(f'/api/v1/documents/{ident}/source?document_version=1').status_code == 410
        assert client.post(f'/api/v1/documents/{ident}/retry', headers={'Idempotency-Key':'no-resurrection'}).status_code == 410
        monkeypatch.setattr(app.state.store.engine, 'delete', original)
        client.delete(f'/api/v1/documents/{ident}')
        wait(client, ident, 'deleted')


def test_inflight_chat_revoked_is_error(app, monkeypatch):
    with TestClient(app) as client:
        ident = upload(client).json()['document']['document_id']
        wait(client, ident)
        original = app.state.generator.answer
        def revoked(*args):
            app.state.store.delete(ident)
            return original(*args)
        monkeypatch.setattr(app.state.generator, 'answer', revoked)
        response = client.post('/api/v1/chat', json={'question':'dang ky ho so'})
        assert response.status_code == 409
        assert response.json()['error']['code'] == 'SOURCE_SET_CHANGED'


def test_missing_converter_and_retry_same_key(client, monkeypatch):
    import zipfile
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as doc:
        doc.writestr('word/document.xml', '<document/>')
    monkeypatch.setattr('app.ingestion.shutil.which', lambda _: None)
    response = client.post('/api/v1/documents', headers={'Idempotency-Key':'docx'}, files={'file':('x.docx',output.getvalue(),'application/vnd.openxmlformats-officedocument.wordprocessingml.document')})
    ident = response.json()['document']['document_id']
    assert wait(client, ident, 'failed').json()['error']['code'] == 'CONVERTER_UNAVAILABLE'
    path = f'/api/v1/documents/{ident}/retry'
    assert client.post(path, headers={'Idempotency-Key':'retry-docx'}).status_code == 202
    assert client.post(path, headers={'Idempotency-Key':'retry-docx'}).status_code == 200


def test_restart_keeps_generation_and_documents(tmp_path):
    settings = Settings(data_dir=tmp_path)
    with TestClient(create_app(settings)) as client:
        ident = upload(client).json()['document']['document_id']
        version = wait(client, ident).json()['available_index_versions'][0]
    with TestClient(create_app(settings)) as client:
        response = client.post('/api/v1/search', json={'query':'ho so', 'index_version':version})
        assert response.status_code == 200, response.text
        assert response.json()['hits'][0]['document_id'] == ident


def test_old_generation_stays_pinned_after_new_document(client):
    one = upload(client).json()['document']['document_id']
    version = wait(client, one).json()['available_index_versions'][0]
    two = upload(client, pdf('A separate new document')).json()['document']['document_id']
    wait(client, two)
    old = client.post('/api/v1/search', json={'query':'ho so', 'index_version':version})
    assert old.json()['retrieval_trace']['resolved_index_version'] == version
    assert all(hit['document_id'] == one for hit in old.json()['hits'])
    missing = client.post('/api/v1/search', json={'query':'document', 'index_version':version, 'document_ids':[two]})
    assert missing.status_code == 409


def test_source_docx_conversion_contract(tmp_path, monkeypatch):
    from app.ingestion import DOCX, extract
    directory = tmp_path / 'doc'
    directory.mkdir()
    (directory / 'original.docx').write_bytes(b'docx already validated')
    monkeypatch.setattr('app.ingestion.shutil.which', lambda _: 'soffice')
    def converter(args, **kwargs):
        assert '--headless' in args and str(directory / 'original.docx') == args[-1]
        (directory / 'original.pdf').write_bytes(pdf('converted DOCX text'))
        from types import SimpleNamespace
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr('app.ingestion.subprocess.run', converter)
    pages = extract(directory, DOCX, Settings(data_dir=tmp_path))
    assert 'converted DOCX text' in pages[0]
    assert (directory / 'source.pdf').exists()


def test_openapi_matches_strict_request_runtime(client):
    from jsonschema import Draft202012Validator
    schema = client.get('/openapi.json').json()
    assert 'multipart/form-data' in schema['paths']['/api/v1/documents']['post']['requestBody']['content']
    validator = Draft202012Validator({**schema, '$ref':'#/components/schemas/ChatRequest'})
    assert not list(validator.iter_errors({'question':'valid'}))
    for bad in [{'question':'ok','document_ids':None}, {'question':'ok','document_ids':[]},
                {'question':'ok','retrieval_config':{'dense':False,'bm25':False}}]:
        assert list(validator.iter_errors(bad)), bad


def test_retry_preserves_ingestion_config(client, app, monkeypatch):
    from app.retrieval import Engine
    build = Engine.build
    attempts = []
    def fail_once(self, *args, **kwargs):
        attempts.append(self.settings.chunk_size)
        if len(attempts) == 1:
            raise OSError('transient')
        return build(self, *args, **kwargs)
    monkeypatch.setattr(Engine,'build',fail_once)
    ident = upload(client).json()['document']['document_id']
    wait(client, ident, 'failed')
    app.state.store.settings.chunk_size = 99
    response = client.post(f'/api/v1/documents/{ident}/retry', headers={'Idempotency-Key':'retry-pinned'})
    assert response.status_code == 202
    wait(client, ident)
    assert attempts == [120,120]


def test_reprocess_preserves_pinned_text_sources_and_extraction(client, app, monkeypatch):
    import json
    from app.store import extract

    ident = upload(client).json()['document']['document_id']
    old_index = wait(client, ident).json()['available_index_versions'][0]
    old_source = client.get(f'/api/v1/documents/{ident}/source?document_version=1').content
    old_pages = (app.state.store.docdir(ident) / 'pages.json').read_bytes()
    changed_pdf = pdf('Improved extraction of document text.')

    def improved(directory, mime, settings):
        pages = extract(directory, mime, settings)
        (directory / 'source.pdf').write_bytes(changed_pdf)
        (directory / 'extraction.json').write_text(json.dumps({
            'method': 'ocr', 'ocr_pages': [1], 'warnings': ['Reprocessed scan'],
        }), encoding='utf-8')
        return [page.replace('Quy trinh dang ky', 'Improved extraction') for page in pages]

    monkeypatch.setattr('app.store.extract', improved)
    path = f'/api/v1/documents/{ident}/reprocess'
    response = client.post(path, headers={'Idempotency-Key': 'reprocess-once'})
    assert response.status_code == 202, response.text
    assert response.json()['document']['document_version'] == 2
    assert client.post(path, headers={'Idempotency-Key': 'reprocess-once'}).status_code == 200
    wait(client, ident)
    current = client.get(f'/api/v1/documents/{ident}').json()['document']
    assert current['source_url'].endswith('document_version=2')
    assert client.get(current['source_url']).content == changed_pdf
    assert client.get(f'/api/v1/documents/{ident}/source?document_version=1').content == old_source
    assert (app.state.store.docdir(ident) / 'pages.json').read_bytes() == old_pages
    assert client.get(f'/api/v1/documents/{ident}/source?document_version=3').status_code == 404
    old = client.post('/api/v1/search', json={'query': 'dang ky ho so', 'index_version': old_index}).json()
    new = client.post('/api/v1/search', json={'query': 'Improved extraction', 'document_ids': [ident]}).json()
    assert old['hits'][0]['document_version'] == 1
    assert old['hits'][0]['extraction']['method'] == 'text'
    assert new['hits'][0]['document_version'] == 2
    assert new['hits'][0]['extraction']['method'] == 'ocr'
    assert 'Improved extraction' in new['hits'][0]['text']
    assert client.delete(f'/api/v1/documents/{ident}').status_code == 202
    wait(client, ident, 'deleted')
    assert not app.state.store.docdir(ident).exists()
    assert client.get(current['source_url']).status_code == 410
    assert client.get(f'/api/v1/documents/{ident}/source?document_version=1').status_code == 410


def test_reprocess_rejects_body_and_unready_state(client, app, monkeypatch):
    from app.errors import ApiError

    def fail(*args):
        raise ApiError(503, 'OCR_UNAVAILABLE', 'OCR unavailable', True)

    monkeypatch.setattr('app.store.extract', fail)
    ident = upload(client).json()['document']['document_id']
    wait(client, ident, 'failed')
    path = f'/api/v1/documents/{ident}/reprocess'
    assert client.post(path, headers={'Idempotency-Key': 'failed-version'}).status_code == 409
    assert client.post(path, headers={'Idempotency-Key': 'unexpected-body'}, json={}).status_code == 422
    assert client.post(path).status_code == 422
    assert client.post('/api/v1/documents/unknown/reprocess', headers={'Idempotency-Key': 'unknown'}).status_code == 404


def test_reprocess_failure_can_retry_new_version_without_changing_old(client, app, monkeypatch):
    from app.errors import ApiError
    from app.store import extract

    ident = upload(client).json()['document']['document_id']
    old_index = wait(client, ident).json()['available_index_versions'][0]
    old_pages = (app.state.store.docdir(ident) / 'pages.json').read_bytes()

    def fail(*args):
        raise ApiError(503, 'OCR_UNAVAILABLE', 'OCR unavailable', True)

    monkeypatch.setattr('app.store.extract', fail)
    path = f'/api/v1/documents/{ident}/reprocess'
    assert client.post(path, headers={'Idempotency-Key': 'new-version'}).status_code == 202
    assert wait(client, ident, 'failed').json()['document_version'] == 2
    assert client.get(f'/api/v1/documents/{ident}/source?document_version=1').status_code == 200
    assert client.post('/api/v1/search', json={'query': 'ho so', 'index_version': old_index}).status_code == 200
    monkeypatch.setattr('app.store.extract', extract)
    assert client.post(f'/api/v1/documents/{ident}/retry', headers={'Idempotency-Key': 'retry-version'}).status_code == 202
    assert wait(client, ident).json()['document_version'] == 2
    assert (app.state.store.docdir(ident) / 'pages.json').read_bytes() == old_pages


def test_reprocess_recovers_uncommitted_copy_after_database_failure(client, app, monkeypatch):
    ident = upload(client).json()['document']['document_id']
    wait(client, ident)
    store = app.state.store
    save = store._save

    def failed_save(*args):
        raise OSError('simulated failure before transaction commit')

    monkeypatch.setattr(store, '_save', failed_save)
    with pytest.raises(OSError):
        store.reprocess(ident, 'interrupted-copy')
    assert store.get(ident)['document_version'] == 1
    assert store.versiondir(ident, 2).exists()
    monkeypatch.setattr(store, '_save', save)
    result = client.post(f'/api/v1/documents/{ident}/reprocess', headers={'Idempotency-Key': 'recovered-copy'})
    assert result.status_code == 202, result.text
    assert wait(client, ident).json()['document_version'] == 2
    assert client.get(f'/api/v1/documents/{ident}/source?document_version=1').status_code == 200
