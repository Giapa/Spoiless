import sys
from types import SimpleNamespace

import pytest

from spoiless.retrieval import embedding_model


def test_model_download_requires_explicit_setup(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    calls = []

    def fake_model(*args, **kwargs):
        calls.append((args, kwargs))
        return object()

    monkeypatch.setitem(
        sys.modules, "fastembed", SimpleNamespace(TextEmbedding=fake_model)
    )
    assert not embedding_model.model_ready()
    with pytest.raises(ValueError):
        embedding_model.load_model()
    assert not calls
    embedding_model.setup_model()
    assert embedding_model.model_ready()
    assert len(calls) == 1 and not calls[0][1].get("local_files_only", False)
    embedding_model.load_model()
    assert calls[1][1]["local_files_only"] is True


def test_failed_setup_is_not_marked_ready(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    def fail(*args, **kwargs):
        raise OSError("offline")

    monkeypatch.setitem(sys.modules, "fastembed", SimpleNamespace(TextEmbedding=fail))
    with pytest.raises(OSError):
        embedding_model.setup_model()
    assert not embedding_model.model_ready()


def test_setup_endpoint_requires_consent(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from spoiless.main import app

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    calls = []
    monkeypatch.setitem(
        sys.modules,
        "fastembed",
        SimpleNamespace(TextEmbedding=lambda *args, **kwargs: calls.append(args)),
    )
    with TestClient(app) as client:
        assert client.get("/api/semantic-model").json() == {"ready": False}
        assert (
            client.post("/api/semantic-model", json={"consent": False}).status_code
            == 422
        )
        assert calls == []
        assert client.post("/api/semantic-model", json={"consent": True}).json() == {
            "ready": True
        }
        assert len(calls) == 1
