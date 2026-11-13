from app.config import Settings


def test_application_defaults_to_pinned_neural_embedding(monkeypatch, tmp_path):
    monkeypatch.delenv('EMBEDDING_BACKEND')
    monkeypatch.delenv('EMBEDDING_REVISION', raising=False)
    settings = Settings(data_dir=tmp_path)
    assert settings.embedding_backend == 'sentence_transformers'
    assert settings.embedding_model == 'intfloat/multilingual-e5-small'
    assert len(settings.embedding_revision) == 40
