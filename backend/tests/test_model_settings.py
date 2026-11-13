import json
import socket

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.errors import ApiError
from app.main import create_app
from app.model_settings import fetch_models, resolve_generation_settings, validate_endpoint
from app.schemas import ChatRequest, GenerationConfig, ModelsRequest


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *args, **kwargs: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34',443))
    ])


def test_connection_policy_blocks_lan_metadata_and_credentials():
    for endpoint in ['http://provider.example/v1', 'https://169.254.169.254/v1',
                     'https://192.168.1.1/v1', 'https://user:secret@provider.example/v1',
                     'https://provider.example/v1?api_key=secret', 'https://provider.example/v1#fragment',
                     'file:///etc/passwd','https://provider.example\\evil/v1']:
        with pytest.raises(ApiError) as caught:
            validate_endpoint(endpoint)
        assert caught.value.code == 'INVALID_MODEL_ENDPOINT'
        assert 'secret' not in caught.value.message
    assert validate_endpoint('https://provider.example/v1/') == 'https://provider.example/v1'
    assert validate_endpoint('http://127.0.0.1:11434/v1') == 'http://127.0.0.1:11434/v1'
    assert validate_endpoint('http://[::1]:11434/v1') == 'http://[::1]:11434/v1'


def test_dns_private_result_blocked(monkeypatch):
    monkeypatch.setattr(socket,'getaddrinfo',lambda *a,**kw:[(socket.AF_INET,socket.SOCK_STREAM,6,'',('10.0.0.1',443))])
    with pytest.raises(ApiError) as caught:
        validate_endpoint('https://provider.example/v1')
    assert caught.value.code == 'INVALID_MODEL_ENDPOINT'


def test_config_is_ephemeral_and_repr_redacts_key(tmp_path):
    original = Settings(data_dir=tmp_path)
    config = GenerationConfig(backend='api',base_url='https://provider.example/v1',model='chosen-model',api_key='private-key')
    resolved = resolve_generation_settings(original,config)
    assert resolved.llm_api_key == 'private-key' and resolved.llm_model == 'chosen-model'
    assert original.llm_model == '' and original.generation_backend == 'extractive'
    assert 'private-key' not in repr(config) and 'private-key' not in repr(resolved)
    assert config.model_dump_json().find('private-key') == -1
    assert resolve_generation_settings(original,None) is original
    assert resolve_generation_settings(resolved,GenerationConfig()).llm_api_key == ''


@pytest.mark.parametrize('config', [None, {'backend':'api','model':'x'},
                                  {'backend':'api','base_url':'https://x.test','model':'x','api_key':'key\nSECRET'},
                                  {'backend':'api','base_url':'https://x.test','model':'x','unknown':1}])
def test_invalid_generation_configs(config):
    with pytest.raises(ValidationError):
        ChatRequest(question='question',generation_config=config)


def test_model_list_auth_and_models_no_key_echo(monkeypatch):
    captured = {}
    def get(url,**kwargs):
        captured.update(kwargs)
        return httpx.Response(200,request=httpx.Request('GET',url),json={'data':[{'id':'model-b'},{'id':'model-a'},{'id':'model-a'}]})
    monkeypatch.setattr(httpx,'get',get)
    config = ModelsRequest(base_url='https://provider.example/v1',api_key='top-secret')
    result = fetch_models(config)
    assert result == ['model-a','model-b']
    assert captured['headers']['Authorization'] == 'Bearer top-secret'
    assert captured['trust_env'] is False and captured['follow_redirects'] is False
    assert 'top-secret' not in json.dumps(result)


@pytest.mark.parametrize('status,expected', [(401,'MODEL_AUTH_FAILED'),(403,'MODEL_AUTH_FAILED'),(302,'INVALID_MODEL_ENDPOINT'),(429,'UPSTREAM_ERROR'),(500,'UPSTREAM_ERROR')])
def test_model_list_errors_are_safe(monkeypatch,status,expected):
    monkeypatch.setattr(httpx,'get',lambda url,**kwargs:httpx.Response(status,request=httpx.Request('GET',url),json={'message':'key-repeated-by-provider'}))
    with pytest.raises(ApiError) as caught:
        fetch_models(ModelsRequest(base_url='https://provider.example/v1',api_key='key-repeated-by-provider'))
    assert caught.value.code == expected
    assert 'key-repeated-by-provider' not in caught.value.message


def test_model_list_timeout_and_malformed(monkeypatch):
    def timeout(*args,**kwargs):
        raise httpx.ReadTimeout('secret-in-error')
    monkeypatch.setattr(httpx,'get',timeout)
    with pytest.raises(ApiError) as caught:
        fetch_models(ModelsRequest(base_url='https://provider.example/v1'))
    assert caught.value.status == 504 and 'secret-in-error' not in caught.value.message
    monkeypatch.setattr(httpx,'get',lambda url,**kwargs:httpx.Response(200,request=httpx.Request('GET',url),json={'data':['not-an-object']}))
    with pytest.raises(ApiError) as caught:
        fetch_models(ModelsRequest(base_url='https://provider.example/v1'))
    assert caught.value.code == 'MODEL_LIST_BAD_RESPONSE'


def test_http_models_and_ephemeral_chat_override(tmp_path,monkeypatch):
    app = create_app(Settings(data_dir=tmp_path))
    store = app.state.store
    trace = {'resolved_index_version':'idx-test','corpus_snapshot_id':'corpus-test',
             'embedding_model_version':'demo','chunking_config_id':'chunk-test',
             'effective_config':{'dense':True,'bm25':True,'reranking':True,'top_k':5},
             'candidate_count':0,'reranked_count':0,'returned_count':0,'context_chunk_count':0}
    monkeypatch.setattr(store,'pin',lambda *args:('idx-test',tmp_path))
    monkeypatch.setattr(store,'recheck',lambda *args:None)
    monkeypatch.setattr(store.engine,'search',lambda *args:([],trace))
    seen = []
    def answer(self,question,hits,trace):
        seen.append((self.settings.generation_backend,self.settings.llm_model,self.settings.llm_api_key))
        return dict(status='insufficient_evidence',answer='Chưa đủ bằng chứng.',citations=[],confidence=None,retrieval_trace=trace)
    monkeypatch.setattr('app.main.Generator.answer',answer)
    monkeypatch.setattr(httpx,'get',lambda url,**kwargs:httpx.Response(200,request=httpx.Request('GET',url),json={'data':[{'id':'chosen-model'}]}))
    secret = 'request-only-secret'
    with TestClient(app) as client:
        models = client.post('/api/v1/models',json={'base_url':'https://provider.example/v1','api_key':secret})
        assert models.status_code == 200 and models.json()['models'] == ['chosen-model']
        request = {'question':'question','generation_config':{'backend':'api','base_url':'https://provider.example/v1','model':'chosen-model','api_key':secret}}
        override = client.post('/api/v1/chat',json=request)
        default = client.post('/api/v1/chat',json={'question':'question'})
        assert override.status_code == 200 and default.status_code == 200
        assert secret not in override.text and secret not in models.text
        assert seen == [('api','chosen-model',secret),('extractive','','')]
        invalid = client.post('/api/v1/models',json={'base_url':'https://provider.example/v1','api_key':secret+'\n'})
        assert invalid.status_code == 422 and secret not in invalid.text
    for path in tmp_path.rglob('*'):
        if path.is_file():
            assert secret.encode() not in path.read_bytes()
