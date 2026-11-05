import pytest

from spoiless import library
from spoiless.epub import Book, Section
from spoiless.main import KeywordSearchRequest, keyword_search
from spoiless.retrieval.search import PASSAGE_CHARS
from spoiless.retrieval.search import keyword_search as search


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
    assert result[0].character_offset == 0
    assert "secretending" not in result[0].text
    assert (
        keyword_search(book, KeywordSearchRequest(query="key"))[0].text
        == result[0].text
    )
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
