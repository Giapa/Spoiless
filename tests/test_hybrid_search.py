import pytest
from fastapi.testclient import TestClient

from spoiless import embedding_model, library
from spoiless.epub import Book, Section
from spoiless.main import app
from spoiless.retrieval import ModelUnavailable, ProgressChanged, hybrid_search


@pytest.fixture
def book_id(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    book = library.add_book(
        Book(
            "Book", (Section("The sailor found a compass."), Section("Secret ending."))
        )
    )
    library.confirm_reading_units(
        book,
        [
            library.ReadingUnitStart("chapter", 0, 0),
            library.ReadingUnitStart("chapter", 1, 0),
        ],
    )
    library.set_progress(book, 2)
    return book


def test_hybrid_search_never_embeds_unread_text(book_id, monkeypatch):
    inputs = []

    class FakeModel:
        def embed(self, texts):
            inputs.extend(texts)
            return [[1, 0] for _ in texts]

    monkeypatch.setattr(embedding_model, "load_model", lambda: FakeModel())
    result = hybrid_search(book_id, "navigation")
    assert inputs == ["navigation", "The sailor found a compass."]
    assert result[0].text == "The sailor found a compass."
    library.set_progress(book_id, 3)
    assert any("Secret" in p.text for p in hybrid_search(book_id, "ending"))
    library.set_progress(book_id, 2)
    assert all("Secret" not in p.text for p in hybrid_search(book_id, "ending"))


def test_progress_change_discards_inflight_results(book_id, monkeypatch):
    library.set_progress(book_id, 3)

    class ChangingModel:
        def embed(self, texts):
            library.set_progress(book_id, 2)
            return [[1, 0] for _ in texts]

    monkeypatch.setattr(embedding_model, "load_model", lambda: ChangingModel())
    with pytest.raises(ProgressChanged):
        hybrid_search(book_id, "ending")
    library.set_progress(book_id, 3)
    with TestClient(app) as client:
        result = client.post(
            f"/api/books/{book_id}/hybrid-search", json={"query": "ending"}
        )
    assert result.status_code == 409
    assert "Secret" not in result.text


def test_model_failure_does_not_fallback_or_expose_exception(book_id, monkeypatch):
    def fail():
        raise RuntimeError("private model error")

    monkeypatch.setattr(embedding_model, "load_model", fail)
    with pytest.raises(ModelUnavailable):
        hybrid_search(book_id, "compass")
    with TestClient(app) as client:
        result = client.post(
            f"/api/books/{book_id}/hybrid-search", json={"query": "compass"}
        )
    assert result.status_code == 503
    assert "private model error" not in result.text


def test_fuses_keyword_and_semantic_ranks(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    book = library.add_book(
        Book("Book", (Section("navigation chart"), Section("a sailor's compass")))
    )
    library.confirm_reading_units(book, [library.ReadingUnitStart("chapter", 0, 0)])
    library.set_progress(book, 2)

    class FakeModel:
        def embed(self, texts):
            assert len(texts) == 3
            return [[1, 0], [0, 1], [1, 0]]

    monkeypatch.setattr(embedding_model, "load_model", lambda: FakeModel())
    results = hybrid_search(book, "navigation")
    assert [passage.text for passage in results] == [
        "navigation chart",
        "a sailor's compass",
    ]


def test_semantic_input_respects_boundary_inside_section(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    book = library.add_book(Book("Book", (Section("📚 Known passage SECRET"),)))
    library.confirm_reading_units(
        book,
        [
            library.ReadingUnitStart("chapter", 0, 0),
            library.ReadingUnitStart("chapter", 0, 16),
        ],
    )
    library.set_progress(book, 2)
    seen = []

    class FakeModel:
        def embed(self, texts):
            seen.extend(texts)
            return [[1, 0] for _ in texts]

    monkeypatch.setattr(embedding_model, "load_model", lambda: FakeModel())
    hybrid_search(book, "known")
    assert seen == ["known", "📚 Known passage "]
