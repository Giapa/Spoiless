import json

import pytest

from src.library import chapter_analysis, storage
from src.library.epub import Book, NavigationEntry, Section


@pytest.fixture
def book_id(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    text = "Preface 📚\nFirst chapter\nRead\nSecond chapter\nSecret"
    return storage.add_book(
        Book(
            "Book",
            (Section(text),),
            (
                NavigationEntry("Preface", 0, 0),
                NavigationEntry("First chapter", 0, text.index("First chapter")),
                NavigationEntry("Second chapter", 0, text.index("Second chapter")),
            ),
        )
    )


def test_ai_starts_use_exact_unicode_offsets_and_protect_current_chapter(
    book_id, monkeypatch
):
    calls = []

    def classify(account, model, prompt):
        calls.append(prompt)
        return json.dumps(
            {"boundaries": [True] * len(json.loads(prompt.rsplit("\n", 1)[1]))}
        )

    monkeypatch.setattr(chapter_analysis, "generate_response", classify)
    chapter_analysis.analyze_chapters(book_id, "account", "model")
    storage.set_progress(book_id, 2)
    eligible = storage.eligible_text(book_id)[0][1]
    assert "First chapter" in eligible and "Secret" not in eligible
    assert len(calls) == 1


@pytest.mark.parametrize(
    "response",
    [
        "not json",
        '{"uncertain":true}',
        "{}",
        '{"boundary":1}',
        '{"boundary":true,"extra":1}',
        '{"boundary":"true"}',
        '{"boundaries":[true]}',
        '{"boundaries":[true,1]}',
        '{"boundaries":[true,true,true]}',
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
        return json.dumps(
            {"boundaries": [True] * len(json.loads(args[2].rsplit("\n", 1)[1]))}
        )

    monkeypatch.setattr(chapter_analysis, "generate_response", generate)
    with pytest.raises(storage.ChapterMapChanged):
        chapter_analysis.analyze_chapters(book_id, "account", "model")
    assert storage.get_reading_units(book_id) == existing
    assert storage.get_progress(book_id).current_chapter == 1


def test_large_book_uses_small_passages_only_for_ambiguous_boundaries(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    book_id = storage.add_book(
        Book(
            "Large",
            (
                Section("Chapter 1\n" + "a" * 220000),
                Section("Continuation\n" + "b" * 220000),
                Section("Chapter 2\nUnread secret"),
            ),
        )
    )
    calls = []

    def classify(account, model, prompt):
        calls.append(prompt)
        return '{"boundaries":[false]}'

    monkeypatch.setattr(chapter_analysis, "generate_response", classify)
    chapter_analysis.analyze_chapters(book_id, "account", "model")
    units = storage.get_reading_units(book_id)
    assert [(u.section_position, u.character_offset) for u in units] == [(0, 0), (2, 0)]
    assert len(calls) == 1
    assert len(calls[0]) < 5000
    storage.set_progress(book_id, 2)
    assert "Unread secret" not in "".join(
        text for _, text in storage.eligible_text(book_id)
    )


def test_missing_numbered_chapter_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    book = storage.add_book(
        Book("Gap", (Section("Chapter 1\nRead\nChapter 3\nUnread"),))
    )
    monkeypatch.setattr(
        chapter_analysis, "generate_response", lambda *args: '{"boundaries":[true]}'
    )
    with pytest.raises(ValueError):
        chapter_analysis.analyze_chapters(book, "account", "model")
    assert storage.get_reading_units(book) == []


def test_clear_numbered_chapters_do_not_call_model(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    book = storage.add_book(
        Book("Clear", (Section("Chapter 1\nRead"), Section("Chapter 2\nUnread")))
    )

    def unexpected(*args):
        pytest.fail("Clear chapter markers should not need the model")

    monkeypatch.setattr(chapter_analysis, "generate_response", unexpected)
    chapter_analysis.analyze_chapters(book, "account", "model")
    assert len(storage.get_reading_units(book)) == 2


def test_chapter_reference_in_prose_is_checked_not_assumed(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    book = storage.add_book(
        Book(
            "Book",
            (
                Section(
                    "Chapter 1\nChapter 2 was where the evidence began.\n"
                    "Chapter 2\nUnread"
                ),
            ),
        )
    )
    calls = []

    def classify(account, model, prompt):
        calls.append(prompt)
        payload = json.loads(prompt.rsplit("\n", 1)[1])
        return json.dumps(
            {
                "boundaries": [
                    item["after"].startswith("Chapter 2\nUnread") for item in payload
                ]
            }
        )

    monkeypatch.setattr(chapter_analysis, "generate_response", classify)
    chapter_analysis.analyze_chapters(book, "account", "model")
    assert len(calls) == 1
    storage.set_progress(book, 2)
    assert "Unread" not in storage.eligible_text(book)[0][1]


def test_more_than_200_ambiguous_passages_are_batched(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    book = storage.add_book(
        Book(
            "Many",
            (
                Section("Chapter 1\nRead"),
                *(Section(f"Continuation {i}") for i in range(205)),
            ),
        )
    )
    sizes = []

    def classify(account, model, prompt):
        passages = json.loads(prompt.rsplit("\n", 1)[1])
        sizes.append(len(passages))
        return json.dumps({"boundaries": [False] * len(passages)})

    monkeypatch.setattr(chapter_analysis, "generate_response", classify)
    chapter_analysis.analyze_chapters(book, "account", "model")
    assert sum(sizes) == 205 and max(sizes) <= 5
    assert len(storage.get_reading_units(book)) == 1
