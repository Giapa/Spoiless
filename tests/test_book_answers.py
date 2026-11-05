import json
import time

import httpx
import pytest

from spoiless import library
from spoiless.book_assistant.questions import answer_book_question
from spoiless.chatgpt import accounts as chatgpt_accounts
from spoiless.chatgpt import credentials as chatgpt_credentials
from spoiless.chatgpt.auth import VerifiedIdentity
from spoiless.chatgpt.credentials import CredentialRecord
from spoiless.epub import Book, Section


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


def test_no_matching_evidence_returns_safe_refusal_without_calling_model(
    reading_setup, monkeypatch
):
    book, account = reading_setup
    requests = []
    monkeypatch.setattr(
        httpx.HTTPTransport, "handle_request", lambda self, req: requests.append(req)
    )
    result = answer_book_question(book, account, "model", "unicorn")
    assert (
        result.answer == "I couldn't find enough information in the completed chapters."
    )
    assert result.citations == ()
    assert requests == []


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
    from spoiless.retrieval.search import ProgressChanged

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
    from spoiless.retrieval.search import ProgressChanged

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
    from spoiless.book_assistant.citations import CitationValidationError

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
    from spoiless.retrieval.search import ProgressChanged

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
