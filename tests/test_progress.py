import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from spoiless.database import connect
from spoiless.library import storage as library
from spoiless.library.api import ProgressRequest, reading_progress, update_progress
from spoiless.library.epub import Book, Section


def test_progress_boundary_and_reconfirmation(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    book_id = library.add_book(
        Book("A", (Section("Intro 📚 one TWO"), Section("THREE")))
    )
    assert reading_progress(book_id).model_dump() == {
        "chapter_count": 0,
        "current_chapter": None,
    }
    with pytest.raises(HTTPException) as error:
        update_progress(book_id, ProgressRequest(current_chapter=2))
    assert error.value.status_code == 422
    with pytest.raises(ValueError):
        library.eligible_text(book_id)
    units = [
        library.ReadingUnitStart("front_matter", 0, 0),
        library.ReadingUnitStart("chapter", 0, 8),
        library.ReadingUnitStart("chapter", 0, 12),
        library.ReadingUnitStart("chapter", 1, 0),
    ]
    library.confirm_reading_units(book_id, units)
    assert reading_progress(book_id).model_dump() == {
        "chapter_count": 3,
        "current_chapter": None,
    }
    for value in (1, "2", True):
        with pytest.raises(ValidationError):
            ProgressRequest(current_chapter=value)
    with pytest.raises(HTTPException):
        update_progress(book_id, ProgressRequest(current_chapter=5))
    assert (
        update_progress(book_id, ProgressRequest(current_chapter=2)).current_chapter
        == 2
    )
    assert library.eligible_text(book_id) == [(0, "Intro 📚 one ")]
    assert (
        update_progress(book_id, ProgressRequest(current_chapter=4)).current_chapter
        == 4
    )
    assert library.eligible_text(book_id) == [(0, "Intro 📚 one TWO"), (1, "THREE")]
    assert (
        update_progress(book_id, ProgressRequest(current_chapter=2)).current_chapter
        == 2
    )
    assert "TWO" not in str(library.eligible_text(book_id))
    library.confirm_reading_units(book_id, units)
    with pytest.raises(ValueError):
        library.eligible_text(book_id)
    assert reading_progress(book_id).current_chapter is None
    assert library.delete_book(book_id)
    with pytest.raises(HTTPException) as error:
        reading_progress(book_id)
    assert error.value.status_code == 404


def test_one_chapter_and_independent_books(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    first = library.add_book(Book("One", (Section("Only chapter"),)))
    second = library.add_book(Book("Two", (Section("Other book"),)))
    library.confirm_reading_units(first, [library.ReadingUnitStart("chapter", 0, 0)])
    library.confirm_reading_units(second, [library.ReadingUnitStart("chapter", 0, 0)])
    library.set_progress(first, 2)
    assert library.eligible_text(first) == [(0, "Only chapter")]
    with pytest.raises(ValueError):
        library.eligible_text(second)
    with connect() as db, db:
        db.execute(
            "UPDATE reading_progress SET current_chapter = 99 WHERE book_id = ?",
            (first,),
        )
    with pytest.raises(ValueError):
        library.eligible_text(first)
