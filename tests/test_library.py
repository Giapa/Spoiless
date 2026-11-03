import sqlite3

import pytest
from fastapi.testclient import TestClient
from test_epub import epub

from spoiless import library
from spoiless.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    return TestClient(app)


def test_import_list_and_delete_without_exposing_text(client):
    response = client.post(
        "/api/books", content=epub(), headers={"content-type": "application/epub+zip"}
    )
    assert response.status_code == 201
    book = response.json()
    assert book["title"] == "A Book"
    assert book["section_count"] == 2
    assert book["chapters_confirmed"] is False
    assert "First" not in response.text
    assert client.get("/api/books").json() == [book]

    assert client.delete(f"/api/books/{book['id']}").status_code == 204
    assert client.get("/api/books").json() == []
    with sqlite3.connect(library.database_path()) as db:
        assert db.execute("SELECT COUNT(*) FROM sections").fetchone()[0] == 0
    assert client.delete(f"/api/books/{book['id']}").status_code == 404


def test_invalid_upload_leaves_no_book(client):
    assert client.post("/api/books", content=b"bad").status_code == 415
    response = client.post(
        "/api/books", content=b"bad", headers={"content-type": "application/epub+zip"}
    )
    assert response.status_code == 422
    assert client.get("/api/books").json() == []


def test_oversized_upload_is_rejected(client, monkeypatch):
    monkeypatch.setattr("spoiless.main.MAX_ARCHIVE_BYTES", 4)
    response = client.post(
        "/api/books", content=b"12345", headers={"content-type": "application/epub+zip"}
    )
    assert response.status_code == 413
    assert client.get("/api/books").json() == []
