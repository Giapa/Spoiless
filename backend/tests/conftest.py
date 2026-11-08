import pytest


@pytest.fixture
def fake_embedding_model(monkeypatch):
    from src.retrieval import embedding_model

    class FakeModel:
        def embed(self, texts):
            return ([1.0, 1.0] for _ in texts)

    monkeypatch.setattr(embedding_model, "load_model", lambda: FakeModel())
