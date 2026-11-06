import json

import pytest

from src.library import chapter_analysis, storage
from src.library.epub import Book, Section


@pytest.fixture
def book_id(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    return storage.add_book(
        Book(
            "Book",
            (Section("Preface 📚\nFirst chapter\nRead\nSecond chapter\nSecret"),),
        )
    )


def test_ai_starts_use_exact_unicode_offsets_and_protect_current_chapter(
    book_id, monkeypatch
):
    response = {
        "chapters": [
            {"section": 0, "start": "First chapter\nRead"},
            {"section": 0, "start": "Second chapter\nSecret"},
        ]
    }
    monkeypatch.setattr(
        chapter_analysis, "generate_response", lambda *args: json.dumps(response)
    )
    chapter_analysis.analyze_chapters(book_id, "account", "model")
    storage.set_progress(book_id, 2)
    eligible = storage.eligible_text(book_id)[0][1]
    assert "First chapter" in eligible and "Secret" not in eligible
    assert storage.get_navigation(book_id)[0].title == "First chapter"


@pytest.mark.parametrize(
    "response",
    [
        "not json",
        '{"uncertain":true}',
        '{"chapters":[]}',
        '{"chapters":[{"section":true,"start":"First"}]}',
        '{"chapters":[{"section":0,"start":"missing"}]}',
        '{"chapters":[{"section":0,"start":"chapter"}]}',
        '{"chapters":[{"section":0,"start":"irst chapter"}]}',
        '{"chapters":[{"section":0,"start":"Second chapter"},'
        '{"section":0,"start":"First chapter"}]}',
    ],
)
def test_invalid_suggestions_never_create_a_map(book_id, monkeypatch, response):
    monkeypatch.setattr(chapter_analysis, "generate_response", lambda *args: response)
    with pytest.raises(ValueError):
        chapter_analysis.analyze_chapters(book_id, "account", "model")
    assert storage.get_reading_units(book_id) == []


def test_concurrent_map_is_not_overwritten(book_id, monkeypatch):
    existing = [storage.ReadingUnitStart("chapter", 0, 0)]

    def generate(*args):
        storage.confirm_reading_units(book_id, existing)
        storage.set_progress(book_id, 1)
        return '{"chapters":[{"section":0,"start":"First chapter"}]}'

    monkeypatch.setattr(chapter_analysis, "generate_response", generate)
    with pytest.raises(storage.ChapterMapChanged):
        chapter_analysis.analyze_chapters(book_id, "account", "model")
    assert storage.get_reading_units(book_id) == existing
    assert storage.get_progress(book_id).current_chapter == 1
