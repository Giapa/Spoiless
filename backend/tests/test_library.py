import sqlite3

import pytest
from fastapi.testclient import TestClient
from test_epub import epub

from src.database import database_path
from src.main import app


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
    with sqlite3.connect(database_path()) as db:
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
    monkeypatch.setattr("src.library.api.MAX_ARCHIVE_BYTES", 4)
    response = client.post(
        "/api/books", content=b"12345", headers={"content-type": "application/epub+zip"}
    )
    assert response.status_code == 413
    assert client.get("/api/books").json() == []


def test_existing_library_and_progress_remain_readable_via_api(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    directory = tmp_path / "spoiless"
    directory.mkdir()
    with sqlite3.connect(directory / "library.sqlite3") as db:
        db.executescript("""
            CREATE TABLE books (id TEXT PRIMARY KEY, title TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE sections (book_id TEXT NOT NULL, position INTEGER NOT NULL,
                text TEXT NOT NULL, PRIMARY KEY (book_id, position));
            CREATE TABLE reading_units (book_id TEXT NOT NULL,
                position INTEGER NOT NULL, kind TEXT NOT NULL,
                section_position INTEGER NOT NULL, character_offset INTEGER NOT NULL,
                PRIMARY KEY (book_id, position));
            CREATE TABLE reading_progress (book_id TEXT PRIMARY KEY,
                current_chapter INTEGER NOT NULL);
            INSERT INTO books (id, title) VALUES ('existing', 'Existing book');
            INSERT INTO sections VALUES ('existing', 0, 'First. Second.');
            INSERT INTO reading_units VALUES ('existing', 0, 'chapter', 0, 0);
            INSERT INTO reading_units VALUES ('existing', 1, 'chapter', 0, 7);
            INSERT INTO reading_progress VALUES ('existing', 2);
        """)
    with TestClient(app) as client:
        assert client.get("/api/books").json() == [
            {
                "id": "existing",
                "title": "Existing book",
                "section_count": 1,
                "chapters_confirmed": True,
            }
        ]
        assert client.get("/api/books/existing/progress").json() == {
            "chapter_count": 2,
            "current_chapter": 2,
        }
