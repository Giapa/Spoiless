import json

import pytest

from src.book_assistant import recaps
from src.library import storage
from src.library.epub import Book, Section
from src.retrieval.search import ProgressChanged


@pytest.mark.parametrize("mode", ["chapter", "through"])
def test_large_recap_uses_bounded_requests_and_excludes_unread_text(
    tmp_path, monkeypatch, mode
):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    chapter = "COMPLETE " + "a" * 250000 + " END"
    book = storage.add_book(Book("Long", (Section(chapter + "\nUNREAD_SECRET"),)))
    storage.confirm_reading_units(
        book,
        [
            storage.ReadingUnitStart("chapter", 0, 0),
            storage.ReadingUnitStart("chapter", 0, len(chapter)),
        ],
    )
    storage.set_progress(book, 2)
    prompts = []

    def generate(account_id, model, prompt, *, before_send):
        before_send()
        payload = json.loads(prompt.split("\n", 1)[1])
        prompts.append(payload)
        assert "UNREAD_SECRET" not in json.dumps(payload)
        assert sum(map(len, payload["passages"])) <= 24000
        quote = payload["passages"][0][:1]
        return json.dumps(
            {"answer": "A summary.", "citations": [{"passage": 0, "quote": quote}]}
        )

    monkeypatch.setattr(recaps, "generate_response", generate)
    answer = recaps.recap_chapter(book, "account", "model", 1, mode)
    assert answer.answer == "A summary."
    assert len(prompts) > 11
    assert all(len(payload.get("summaries", [])) <= 10 for payload in prompts)


def test_large_recap_stops_if_progress_moves_back_during_generation(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    chapter = "x" * 250001
    book = storage.add_book(Book("Long", (Section(chapter + "unread"),)))
    storage.confirm_reading_units(
        book,
        [
            storage.ReadingUnitStart("chapter", 0, 0),
            storage.ReadingUnitStart("chapter", 0, len(chapter)),
        ],
    )
    storage.set_progress(book, 2)
    calls = 0

    def generate(account_id, model, prompt, *, before_send):
        nonlocal calls
        before_send()
        calls += 1
        if calls == 2:
            storage.set_progress(book, 1)
        return json.dumps(
            {"answer": "A summary.", "citations": [{"passage": 0, "quote": "x"}]}
        )

    monkeypatch.setattr(recaps, "generate_response", generate)
    with pytest.raises(ProgressChanged):
        recaps.recap_chapter(book, "account", "model", 1)
    assert calls == 2
