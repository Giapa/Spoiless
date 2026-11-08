import json
import time

import httpx
import pytest

from src.book_assistant.questions import answer_book_question
from src.chatgpt import accounts as chatgpt_accounts
from src.chatgpt import credentials as chatgpt_credentials
from src.chatgpt.auth import VerifiedIdentity
from src.chatgpt.credentials import CredentialRecord
from src.library import storage as library
from src.library.epub import Book, Section

pytestmark = pytest.mark.usefixtures("fake_embedding_model")


class MemoryKeyring:
    def __init__(self):
        self.values = {}

    def get_password(self, service, username):
        return self.values.get((service, username))

    def set_password(self, service, username, value):
        self.values[(service, username)] = value


@pytest.fixture
def reading_setup(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    backend = MemoryKeyring()
    monkeypatch.setattr(chatgpt_credentials, "_backend", lambda: backend)
    identity = VerifiedIdentity("reader", None)
    account = chatgpt_accounts.remember_verified("oaiapp_reader", identity)
    record = CredentialRecord(
        client_id="oaiapp_reader",
        subject="reader",
        id_token="id-token",
        access_token="secret-token",
        refresh_token="refresh-token",
        token_type="Bearer",
        expires_at=float(time.time() + 3600),
        scope="openid offline_access resource.invoke chatgpt.tokens.use.direct",
    )
    chatgpt_credentials.save_credentials(record, identity)
    text = "Mira found the key. "
    book = library.add_book(
        Book("Book", (Section(text + "UNREAD_SECRET reveals the ending."),))
    )
    library.confirm_reading_units(
        book,
        [
            library.ReadingUnitStart("chapter", 0, 0),
            library.ReadingUnitStart("chapter", 0, len(text)),
        ],
    )
    library.set_progress(book, 2)
    return book, account


def test_answer_uses_only_completed_text_and_returns_verified_quote(
    reading_setup, monkeypatch
):
    book, account = reading_setup
    requests = []

    def handle(request):
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "models": [
                        {"slug": "model", "display_name": "Model", "visibility": "list"}
                    ]
                },
            )
        answer = json.dumps(
            {
                "answer": "Mira found the key.",
                "citations": [{"passage": 0, "quote": "found the key"}],
            }
        )
        delta = json.dumps({"type": "response.output_text.delta", "delta": answer})
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=(
                f"data: {delta}\n\n"
                'data: {"type":"response.completed",'
                '"response":{"status":"completed"}}\n\n'
            ),
        )

    monkeypatch.setattr(
        httpx.HTTPTransport, "handle_request", lambda self, request: handle(request)
    )
    answer = answer_book_question(book, account, "model", "Who found the key?")
    assert answer.answer == "Mira found the key."
    assert answer.citations[0].quote == "found the key"
    assert answer.citations[0].character_offset == 5
    sent = json.loads(requests[-1].content)["input"][0]["content"]
    assert "Mira found the key" in sent
    assert "UNREAD_SECRET" not in sent


def test_semantic_search_can_find_evidence_without_matching_words(
    reading_setup, monkeypatch
):
    book, account = reading_setup
    prompts = []

    def generate(account_id, model, prompt, before_send):
        before_send()
        prompts.append(prompt)
        return json.dumps(
            {
                "answer": "Mira found the key.",
                "citations": [{"passage": 0, "quote": "found the key"}],
            }
        )

    monkeypatch.setattr("src.book_assistant.questions.generate_response", generate)
    result = answer_book_question(book, account, "model", "Who discovered it?")
    assert result.answer == "Mira found the key."
    assert "Mira found the key" in prompts[0]
    assert "UNREAD_SECRET" not in prompts[0]


def test_answer_can_use_relevant_evidence_beyond_first_five_results(
    reading_setup, monkeypatch
):
    _, account = reading_setup
    sections = [Section(f"Darrow speaks to stranger {i}.") for i in range(10)]
    sections += [Section("My wife Eo held my hand."), Section("UNREAD_SECRET")]
    book = library.add_book(Book("First person story", tuple(sections)))
    library.confirm_reading_units(
        book,
        [
            library.ReadingUnitStart("chapter", 0, 0),
            library.ReadingUnitStart("chapter", 11, 0),
        ],
    )
    library.set_progress(book, 2)

    def generate(account_id, model, prompt, before_send):
        before_send()
        payload = json.loads(prompt.split("\n", 1)[1])
        assert all("UNREAD_SECRET" not in p for p in payload["passages"])
        index = next(
            i for i, text in enumerate(payload["passages"]) if "wife Eo" in text
        )
        return json.dumps(
            {
                "answer": "Eo is his wife.",
                "citations": [{"passage": index, "quote": "My wife Eo"}],
            }
        )

    monkeypatch.setattr("src.book_assistant.questions.generate_response", generate)
    result = answer_book_question(book, account, "model", "Who is Darrow related to?")
    assert result.answer == "Eo is his wife."
    assert result.citations[0].section_position == 10


def test_model_can_decline_when_passage_lacks_an_answer(reading_setup, monkeypatch):
    book, account = reading_setup

    def handle(request):
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "models": [
                        {"slug": "model", "display_name": "Model", "visibility": "list"}
                    ]
                },
            )
        delta = json.dumps(
            {
                "type": "response.output_text.delta",
                "delta": '{"insufficient_evidence":true}',
            }
        )
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=(
                f"data: {delta}\n\n"
                'data: {"type":"response.completed",'
                '"response":{"status":"completed"}}\n\n'
            ),
        )

    monkeypatch.setattr(
        httpx.HTTPTransport, "handle_request", lambda self, request: handle(request)
    )
    result = answer_book_question(book, account, "model", "Where is the key?")
    assert (
        result.answer == "I couldn't find enough information in the completed chapters."
    )
    assert result.citations == ()


def test_progress_change_during_generation_withholds_answer(reading_setup, monkeypatch):
    from src.retrieval.search import ProgressChanged

    book, account = reading_setup

    def handle(request):
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "models": [
                        {"slug": "model", "display_name": "Model", "visibility": "list"}
                    ]
                },
            )
        library.set_progress(book, 3)
        answer = json.dumps(
            {
                "answer": "Mira found the key.",
                "citations": [{"passage": 0, "quote": "found the key"}],
            }
        )
        delta = json.dumps({"type": "response.output_text.delta", "delta": answer})
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=(
                f"data: {delta}\n\n"
                'data: {"type":"response.completed",'
                '"response":{"status":"completed"}}\n\n'
            ),
        )

    monkeypatch.setattr(
        httpx.HTTPTransport, "handle_request", lambda self, request: handle(request)
    )
    with pytest.raises(ProgressChanged):
        answer_book_question(book, account, "model", "Who found the key?")


def test_chapter_map_change_with_same_eligible_text_withholds_answer(
    reading_setup, monkeypatch
):
    from src.retrieval.search import ProgressChanged

    book, account = reading_setup

    def handle(request):
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "models": [
                        {"slug": "model", "display_name": "Model", "visibility": "list"}
                    ]
                },
            )
        library.confirm_reading_units(
            book,
            [
                library.ReadingUnitStart("chapter", 0, 0),
                library.ReadingUnitStart("chapter", 0, len("Mira found the key. ")),
                library.ReadingUnitStart(
                    "chapter", 0, len("Mira found the key. UNREAD_SECRET ")
                ),
            ],
        )
        library.set_progress(book, 2)
        answer = json.dumps(
            {
                "answer": "Mira found the key.",
                "citations": [{"passage": 0, "quote": "found the key"}],
            }
        )
        delta = json.dumps({"type": "response.output_text.delta", "delta": answer})
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=(
                f"data: {delta}\n\n"
                'data: {"type":"response.completed",'
                '"response":{"status":"completed"}}\n\n'
            ),
        )

    monkeypatch.setattr(
        httpx.HTTPTransport, "handle_request", lambda self, request: handle(request)
    )
    with pytest.raises(ProgressChanged):
        answer_book_question(book, account, "model", "Who found the key?")


def test_fabricated_citation_withholds_the_entire_answer(reading_setup, monkeypatch):
    from src.book_assistant.citations import CitationValidationError

    book, account = reading_setup

    def handle(request):
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "models": [
                        {"slug": "model", "display_name": "Model", "visibility": "list"}
                    ]
                },
            )
        answer = json.dumps(
            {
                "answer": "UNREAD_SECRET",
                "citations": [{"passage": 0, "quote": "UNREAD_SECRET"}],
            }
        )
        delta = json.dumps({"type": "response.output_text.delta", "delta": answer})
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=(
                f"data: {delta}\n\n"
                'data: {"type":"response.completed",'
                '"response":{"status":"completed"}}\n\n'
            ),
        )

    monkeypatch.setattr(
        httpx.HTTPTransport, "handle_request", lambda self, request: handle(request)
    )
    with pytest.raises(CitationValidationError) as error:
        answer_book_question(book, account, "model", "Who found the key?")
    assert "UNREAD_SECRET" not in str(error.value)


def test_progress_change_during_model_discovery_prevents_sending_book_text(
    reading_setup, monkeypatch
):
    from src.retrieval.search import ProgressChanged

    book, account = reading_setup
    library.set_progress(book, 3)
    requests = []

    def handle(request):
        requests.append(request)
        if request.method == "GET":
            library.set_progress(book, 2)
            return httpx.Response(
                200,
                json={
                    "models": [
                        {"slug": "model", "display_name": "Model", "visibility": "list"}
                    ]
                },
            )
        return httpx.Response(500)

    monkeypatch.setattr(
        httpx.HTTPTransport, "handle_request", lambda self, request: handle(request)
    )
    with pytest.raises(ProgressChanged):
        answer_book_question(book, account, "model", "Who found the key?")
    assert all(request.method == "GET" for request in requests)


def test_unconfirmed_progress_never_sends_book_text(reading_setup, monkeypatch):
    book, account = reading_setup
    library.confirm_reading_units(book, [library.ReadingUnitStart("chapter", 0, 0)])
    requests = []
    monkeypatch.setattr(
        httpx.HTTPTransport,
        "handle_request",
        lambda self, request: requests.append(request),
    )
    with pytest.raises(ValueError):
        answer_book_question(book, account, "model", "key")
    assert requests == []


def test_chat_routes_recap_and_saves_it(reading_setup, monkeypatch):
    from src.book_assistant.citations import ValidatedAnswer
    from src.database import connect

    book, account = reading_setup
    monkeypatch.setattr(
        "src.book_assistant.questions.generate_response",
        lambda *args, **kwargs: json.dumps({"recap": 1, "mode": "chapter"}),
    )
    calls = []

    def recap(book_id, account_id, model, chapter, mode):
        calls.append((book_id, chapter, mode))
        return ValidatedAnswer("A recap.", ())

    monkeypatch.setattr("src.book_assistant.recaps.recap_chapter", recap)
    result = answer_book_question(book, account, "model", "Summarize chapter 1")
    assert result.answer == "A recap."
    assert calls == [(book, 1, "chapter")]
    with connect() as db:
        assert db.execute(
            "SELECT question, answer FROM conversation_turns "
            "WHERE book_id = ? AND active = 1",
            (book,),
        ).fetchone() == ("Summarize chapter 1", "A recap.")
    library.set_progress(book, 3)
    with connect() as db:
        assert (
            db.execute(
                "SELECT count(*) FROM conversation_turns "
                "WHERE book_id = ? AND active = 1",
                (book,),
            ).fetchone()[0]
            == 0
        )
