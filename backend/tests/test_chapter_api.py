import pytest
from fastapi.testclient import TestClient

from src.library import storage as library
from src.library.epub import Book, Section
from src.main import app


@pytest.fixture
def library_client(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    book_id = library.add_book(
        Book("Test", (Section("Intro 📚 chapter"), Section("Next")))
    )
    return TestClient(app), book_id


def test_confirm_and_reload_chapters(library_client):
    client, book_id = library_client
    assert client.get(f"/api/books/{book_id}/reading-units").json() == []
    sections = client.get(f"/api/books/{book_id}/sections")
    assert sections.json() == [
        {"position": 0, "text": "Intro 📚 chapter"},
        {"position": 1, "text": "Next"},
    ]
    units = [
        {"kind": "front_matter", "section_position": 0, "character_offset": 0},
        {"kind": "chapter", "section_position": 0, "character_offset": 8},
        {"kind": "chapter", "section_position": 1, "character_offset": 0},
    ]
    assert (
        client.put(
            f"/api/books/{book_id}/reading-units", json={"units": units}
        ).status_code
        == 204
    )
    assert client.get(f"/api/books/{book_id}/reading-units").json() == units
    response = client.get("/api/books")
    assert response.json()[0]["chapters_confirmed"] is True
    assert "chapter" not in response.json()[0]
    assert "Intro" not in response.text


def test_invalid_update_does_not_replace_previous_confirmation(library_client):
    client, book_id = library_client
    endpoint = f"/api/books/{book_id}/reading-units"
    units = [{"kind": "chapter", "section_position": 0, "character_offset": 0}]
    assert client.put(endpoint, json={"units": units}).status_code == 204
    invalid = [
        [],
        [{"kind": "chapter", "section_position": 0, "character_offset": 999}],
        [{"kind": "chapter", "section_position": 0, "character_offset": "0"}],
        [{"kind": "unknown", "section_position": 0, "character_offset": 0}],
    ]
    for value in invalid:
        assert client.put(endpoint, json={"units": value}).status_code == 422
        assert client.get(endpoint).json() == units


def test_missing_book_returns_not_found(library_client):
    client, _ = library_client
    assert client.get("/api/books/missing/sections").status_code == 404
    assert client.get("/api/books/missing/reading-units").status_code == 404
    body = {
        "units": [{"kind": "chapter", "section_position": 0, "character_offset": 0}]
    }
    assert client.put("/api/books/missing/reading-units", json=body).status_code == 404
