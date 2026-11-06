import sqlite3

import pytest

from src.database import database_path
from src.library import storage as library
from src.library.epub import Book, Section, read_epub
from src.library.storage import BookNotFound, ReadingUnitStart


@pytest.fixture
def book_id(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    return library.add_book(
        Book("Test", (Section("Intro 📚 chapter"), Section("Next")))
    )


def test_confirms_units_with_front_matter_and_chapter_within_section(book_id):
    units = [
        ReadingUnitStart("front_matter", 0, 0),
        ReadingUnitStart("chapter", 0, 8),
        ReadingUnitStart("chapter", 1, 0),
    ]
    assert library.get_reading_units(book_id) == []
    library.confirm_reading_units(book_id, units)
    assert library.get_reading_units(book_id) == units
    replacement = [ReadingUnitStart("chapter", 0, 0), ReadingUnitStart("chapter", 1, 0)]
    library.confirm_reading_units(book_id, replacement)
    assert library.get_reading_units(book_id) == replacement


@pytest.mark.parametrize(
    "units",
    [
        [],
        [ReadingUnitStart("chapter", 0, 1)],
        [ReadingUnitStart("front_matter", 0, 0)],
        [ReadingUnitStart("chapter", 0, 0), ReadingUnitStart("front_matter", 1, 0)],
        [ReadingUnitStart("chapter", 0, 0), ReadingUnitStart("chapter", 0, 0)],
        [ReadingUnitStart("chapter", 0, 0), ReadingUnitStart("chapter", 1, 4)],
        [ReadingUnitStart("chapter", 0, 0), ReadingUnitStart("chapter", 2, 0)],
    ],
)
def test_invalid_boundaries_preserve_existing_confirmation(book_id, units):
    original = [ReadingUnitStart("chapter", 0, 0)]
    library.confirm_reading_units(book_id, original)
    with pytest.raises(ValueError):
        library.confirm_reading_units(book_id, units)
    assert library.get_reading_units(book_id) == original


def test_deleting_book_removes_confirmed_units(book_id):
    library.confirm_reading_units(book_id, [ReadingUnitStart("chapter", 0, 0)])
    assert library.delete_book(book_id)
    with sqlite3.connect(database_path()) as db:
        assert db.execute("SELECT COUNT(*) FROM reading_units").fetchone()[0] == 0
    with pytest.raises(BookNotFound):
        library.get_reading_units(book_id)
    with pytest.raises(BookNotFound):
        library.confirm_reading_units(book_id, [ReadingUnitStart("chapter", 0, 0)])


def test_detected_chapters_enforce_current_chapter_boundary(tmp_path, monkeypatch):
    from tests.test_epub import epub

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    book = read_epub(
        epub(
            extra={
                "book/two.xhtml": "<h1>Preface</h1><p>Front</p>",
                "book/one.xhtml": "<h1>Chapter 1</h1><p>Read 📚</p>"
                "<h1>Chapter 2</h1><p>Unread secret</p>",
            }
        )
    )
    book_id = library.add_book(book)
    assert library.get_progress(book_id).chapter_count == 2
    library.set_progress(book_id, 1)
    assert library.eligible_text(book_id) == []
    library.set_progress(book_id, 2)
    eligible = " ".join(text for _, text in library.eligible_text(book_id))
    assert "Read 📚" in eligible and "Unread secret" not in eligible


def test_legacy_progress_schema_accepts_first_chapter(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    book_id = library.add_book(Book("Old", (Section("Text"),)))
    library.confirm_reading_units(book_id, [ReadingUnitStart("chapter", 0, 0)])
    with sqlite3.connect(database_path()) as db:
        db.executescript("""
            DROP TABLE reading_progress;
            CREATE TABLE reading_progress (
                book_id TEXT PRIMARY KEY REFERENCES books(id) ON DELETE CASCADE,
                current_chapter INTEGER NOT NULL CHECK (current_chapter >= 2)
            );
        """)
    library.set_progress(book_id, 1)
    assert library.eligible_text(book_id) == []
