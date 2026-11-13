"""Download the pinned embedding model and verify local inference without an API key."""
import json
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.config import Settings  # noqa: E402
from app.retrieval import Engine  # noqa: E402
from app.chunking import chunk_pages  # noqa: E402


def main():
    settings = Settings()
    if settings.embedding_backend != 'sentence_transformers':
        raise SystemExit('Set EMBEDDING_BACKEND=sentence_transformers before setup.')
    engine = Engine(settings)
    spec = engine._pin_revision(engine._embedding_spec(), 'embedding')
    vectors = engine._encode(['Quy trình đăng ký học phần.', 'Các trung tâm dữ liệu độc lập.'], spec)
    query = engine._encode(['Cách đăng ký môn học?'], spec, query=True)
    assert vectors.shape == (2, 384) and query.shape == (1, 384)
    assert np.isfinite(vectors).all() and np.allclose(np.linalg.norm(vectors, axis=1), 1, atol=1e-4)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    samples = [
        ('registration', 'Hồ sơ đăng ký được giải quyết trong năm ngày làm việc.'),
        ('cloud', 'Availability Zone bao gồm các trung tâm dữ liệu hoạt động độc lập.'),
        ('library', 'Thư viện mở cửa từ tám giờ sáng đến năm giờ chiều.'),
    ]
    chunks = [chunk for ident, text in samples for chunk in chunk_pages(
        {'document_id': ident, 'filename': ident + '.pdf'}, [text])]
    # Dense-only, no BM25 or lexical reranker, to exercise real model inference.
    with tempfile.TemporaryDirectory(dir=settings.data_dir) as directory:
        index = Path(directory) / 'index'
        engine.build('embedding-smoke', chunks, index)
        hits, trace = engine.search(index, 'How long does processing an application take?',
                                   {'dense': True, 'bm25': False, 'reranking': False, 'top_k': 3})
        assert hits[0]['document_id'] == 'registration', hits
        assert trace['retrieval_backend'] == 'sentence_transformers'
    result = {'embedding': spec, 'shape': list(vectors.shape), 'local_inference': 'passed',
              'dense_only_cross_language_retrieval': 'passed'}
    (settings.data_dir / 'embedding-setup.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
