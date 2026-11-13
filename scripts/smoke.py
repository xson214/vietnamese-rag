"""Exercise the running API with original sample data and prepare a tiny benchmark."""
import json
import time
import unicodedata
from pathlib import Path

import httpx
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]


def main():
    file = ROOT / 'data/samples/quy-trinh-demo.pdf'
    with httpx.Client(base_url='http://127.0.0.1:8000', timeout=30) as client:
        uploaded = client.post('/api/v1/documents', headers={'Idempotency-Key':'sample-pdf-v1'}, files={'file':(file.name,file.read_bytes(),'application/pdf')})
        uploaded.raise_for_status()
        ident = uploaded.json()['document']['document_id']
        for _ in range(100):
            status = client.get(f'/api/v1/documents/{ident}/status').json()
            if status['status'] == 'ready':
                break
            if status['status'] == 'failed':
                raise RuntimeError(status)
            time.sleep(.2)
        else:
            raise RuntimeError('Timed out waiting for sample ingestion.')
        version = status['available_index_versions'][-1]
        question = 'Hồ sơ đăng ký được xử lý trong bao nhiêu ngày?'
        chat = client.post('/api/v1/chat', json={'question':question, 'document_ids':[ident], 'index_version':version})
        chat.raise_for_status()
        result = chat.json()
        assert result['status'] == 'answered', result
        assert result['confidence'] is None
        assert client.get(result['citations'][0]['source_url']).content.startswith(b'%PDF')
        assert client.get('/api/v1/health').status_code == 200
        assert client.get('http://127.0.0.1:5173').status_code == 200
        quote = 'Hồ sơ đăng ký được xử lý trong 5 ngày làm việc.'
        page = unicodedata.normalize('NFC', PdfReader(file).pages[0].extract_text().replace('\r\n','\n').replace('\r','\n'))
        start = page.index(quote)
        span = dict(document_id=ident,document_version=1,page_number=1,start_offset=start,end_offset=start+len(quote),quote=quote)
        gold = {'dataset_version':'smoke-v1', 'fixture_only':True, 'questions':[
            {'question_id':'smoke-answerable','question':question,'document_ids':[ident],'answerable':True,
             'reference_answer':'5 ngày làm việc.', 'evidence_sets':[{'spans':[span]}]},
            {'question_id':'smoke-unanswerable','question':'Khoảng cách giữa sao Hỏa và sao Kim là bao nhiêu?',
             'document_ids':[ident],'answerable':False,'reference_answer':None,'evidence_sets':[]},
        ]}
        output = ROOT / 'evaluation/results'
        output.mkdir(parents=True, exist_ok=True)
        (output / 'smoke-gold.json').write_text(json.dumps(gold, ensure_ascii=False, indent=2), encoding='utf-8')
        (output / 'smoke-index.txt').write_text(version, encoding='utf-8')
        print(json.dumps({'document_id':ident,'index_version':version,'chat_status':result['status'],
                          'citation_page':result['citations'][0]['page_number'],'confidence':None},ensure_ascii=False))


if __name__ == '__main__':
    main()
