"""Unit/API lifecycle tests use an explicit offline baseline, never download models."""
import pytest


@pytest.fixture(autouse=True)
def offline_test_embedding(monkeypatch):
    monkeypatch.setenv('EMBEDDING_BACKEND', 'hash')
