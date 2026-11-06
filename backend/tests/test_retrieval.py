import pytest
from fastapi.testclient import TestClient

from src.library import storage as library
from src.library.epub import Book, Section
from src.main import app
from src.retrieval.search import PASSAGE_CHARS
from src.retrieval.search import keyword_search as search


def test_search_indexes_only_eligible_text(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    text = "A" * (PASSAGE_CHARS - 4) + " key secretending"
    book = library.add_book(Book("Book", (Section(text), Section("later revelation"))))
    other = library.add_book(Book("Other", (Section("unrelated secretending"),)))
    with pytest.raises(ValueError):
        search(book, "key")
    library.confirm_reading_units(
        book,
        [
            library.ReadingUnitStart("chapter", 0, 0),
            library.ReadingUnitStart("chapter", 0, text.index("secretending")),
            library.ReadingUnitStart("chapter", 1, 0),
        ],
    )
    library.set_progress(book, 2)
    assert search(book, "secretending") == []
    assert search(book, "revelation") == []
    result = search(book, "key")
    assert len(result) == 1
    start = result[0].character_offset
    assert text[start : start + len(result[0].text)] == result[0].text
    assert start + len(result[0].text) <= text.index("secretending")
    assert "secretending" not in result[0].text
    with TestClient(app) as client:
        response = client.post(
            f"/api/books/{book}/keyword-search", json={"query": "key"}
        )
    assert response.status_code == 200
    assert response.json()[0]["text"] == result[0].text
    library.set_progress(book, 4)
    assert search(book, "revelation")[0].section_position == 1
    assert search(book, "secretending")[0].text.endswith("secretending")
    library.set_progress(book, 2)
    assert search(book, "secretending") == []
    with pytest.raises(ValueError):
        search(other, "secretending")
    for query in ("!!!", "a" * 501):
        with pytest.raises(ValueError):
            search(book, query)
    assert search(book, '"key" OR secretending')


def test_search_keeps_paragraph_offsets_within_completed_text(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    first = "α" * 410 + " compass"
    second = "β" * 410 + " lantern"
    unread = " unreadsecret"
    text = first + "\n\n" + second + unread
    book = library.add_book(Book("Book", (Section(text),)))
    library.confirm_reading_units(
        book,
        [
            library.ReadingUnitStart("chapter", 0, 0),
            library.ReadingUnitStart("chapter", 0, len(first + "\n\n" + second)),
        ],
    )
    library.set_progress(book, 2)
    with TestClient(app) as client:
        response = client.post(
            f"/api/books/{book}/keyword-search", json={"query": "lantern"}
        )
    assert response.status_code == 200
    assert response.json() == [
        {"section_position": 0, "character_offset": len(first) + 2, "text": second}
    ]
