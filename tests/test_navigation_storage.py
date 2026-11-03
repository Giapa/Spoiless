import sqlite3

import pytest
from fastapi.testclient import TestClient
from test_epub import epub

from spoiless import library
from spoiless.epub import Book, NavigationEntry, Section
from spoiless.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    return TestClient(app)


def test_import_persists_unconfirmed_suggestions_without_exposing_titles(client):
    package = """<package><metadata><title>Book</title></metadata><manifest>
        <item id="nav" href="toc.xhtml" properties="nav"
            media-type="application/xhtml+xml"/>
        <item id="one" href="one.xhtml" media-type="application/xhtml+xml"/>
        </manifest><spine><itemref idref="one"/></spine></package>"""
    nav = """<html xmlns:epub="http://www.idpf.org/2007/ops"><body>
        <nav epub:type="toc"><ol><li><a href="one.xhtml#start">Secret title</a></li>
        <li><a href="one.xhtml#missing">Unresolved title</a></li></ol></nav>
        </body></html>"""
    data = epub(
        extra={
            "book/content.opf": package,
            "book/toc.xhtml": nav,
            "book/one.xhtml": '<body><p id="start">Text</p></body>',
        }
    )
    response = client.post(
        "/api/books", content=data, headers={"content-type": "application/epub+zip"}
    )
    assert response.status_code == 201
    book_id = response.json()["id"]
    endpoint = f"/api/books/{book_id}/navigation"
    hidden = client.get(endpoint)
    assert hidden.json() == [
        {"title": None, "section_position": 0, "character_offset": 0},
        {"title": None, "section_position": None, "character_offset": None},
    ]
    assert "Secret title" not in hidden.text
    shown = client.get(endpoint, params={"include_titles": "true"}).json()
    assert [entry["title"] for entry in shown] == ["Secret title", "Unresolved title"]
    assert client.get(f"/api/books/{book_id}/reading-units").json() == []
    assert client.get("/api/books").json()[0]["chapters_confirmed"] is False
    assert client.delete(f"/api/books/{book_id}").status_code == 204
    with sqlite3.connect(library.database_path()) as db:
        assert db.execute("SELECT COUNT(*) FROM navigation_entries").fetchone()[0] == 0
    assert client.get(endpoint).status_code == 404


def test_existing_book_without_suggestions_remains_available(client):
    book_id = library.add_book(Book("Old book", (Section("Text"),)))
    assert client.get(f"/api/books/{book_id}/navigation").json() == []
    assert client.get("/api/books").json()[0]["title"] == "Old book"


def test_invalid_navigation_rolls_back_entire_import(client):
    book = Book("Invalid", (Section("Text"),), (NavigationEntry("Bad", 4, 0),))
    with pytest.raises(sqlite3.IntegrityError):
        library.add_book(book)
    assert client.get("/api/books").json() == []


def test_existing_database_gets_navigation_table(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    path = library.database_path()
    path.parent.mkdir(parents=True)
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE books (id TEXT PRIMARY KEY, title TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE sections (book_id TEXT NOT NULL, position INTEGER NOT NULL,
                text TEXT NOT NULL, PRIMARY KEY (book_id, position));
            INSERT INTO books (id, title) VALUES ('old', 'Old book');
            INSERT INTO sections VALUES ('old', 0, 'Old text');
        """)
    assert library.get_navigation("old") == []
    assert library.get_sections("old") == [(0, "Old text")]
