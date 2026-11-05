import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from spoiless import chatgpt_accounts, chatgpt_credentials, library
from spoiless.chatgpt_auth import VerifiedIdentity
from spoiless.chatgpt_credentials import CredentialRecord
from spoiless.epub import Book, Section
from spoiless.main import app


class MemoryKeyring:
    def __init__(self):
        self.values = {}

    def get_password(self, service, username):
        return self.values.get((service, username))

    def set_password(self, service, username, value):
        self.values[(service, username)] = value

    def delete_password(self, service, username):
        del self.values[(service, username)]


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
    chatgpt_accounts.activate_after_storage(account)
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


def test_answer_api_returns_verified_text_without_unread_material(
    reading_setup, monkeypatch
):
    book, _ = reading_setup
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
    headers = {"Origin": "http://127.0.0.1:8000", "X-Spoiless-Action": "1"}
    with TestClient(
        app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 1234)
    ) as client:
        response = client.post(
            f"/api/books/{book}/answer",
            json={"question": "Who found the key?", "model": "model", "confirm": True},
            headers=headers,
        )
        history = client.get(f"/api/books/{book}/conversation")
    assert response.status_code == 200
    assert history.status_code == 200
    assert history.json() == [{"question": "Who found the key?", **response.json()}]
    assert response.json() == {
        "answer": "Mira found the key.",
        "citations": [
            {"section_position": 0, "character_offset": 5, "quote": "found the key"}
        ],
    }
    assert response.headers["cache-control"] == "no-store"
    assert "UNREAD_SECRET" not in response.text
    assert "secret-token" not in response.text
    assert "UNREAD_SECRET" not in requests[-1].content.decode()


def test_remote_or_unconfirmed_requests_do_not_contact_openai(
    reading_setup, monkeypatch
):
    book, _ = reading_setup
    requests = []
    monkeypatch.setattr(
        httpx.HTTPTransport,
        "handle_request",
        lambda self, request: requests.append(request),
    )
    good = {"Origin": "http://127.0.0.1:8000", "X-Spoiless-Action": "1"}
    with TestClient(
        app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 1234)
    ) as client:
        for headers, confirmation in (
            ({}, True),
            ({**good, "Origin": "https://attacker.example"}, True),
            (good, False),
            (good, 1),
        ):
            response = client.post(
                f"/api/books/{book}/answer",
                json={"question": "key", "model": "model", "confirm": confirmation},
                headers=headers,
            )
            assert response.status_code in (403, 422)
    assert requests == []


def test_conversation_follows_reading_progress(reading_setup):
    book, _ = reading_setup
    headers = {"Origin": "http://127.0.0.1:8000", "X-Spoiless-Action": "1"}
    with TestClient(
        app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 1234)
    ) as client:
        answer = client.post(
            f"/api/books/{book}/answer",
            json={"question": "zebra", "model": "model", "confirm": True},
            headers=headers,
        )
        assert answer.status_code == 200
        original = client.get(f"/api/books/{book}/conversation").json()
        assert len(original) == 1
        assert (
            client.put(
                f"/api/books/{book}/progress", json={"current_chapter": 3}
            ).status_code
            == 200
        )
        assert client.get(f"/api/books/{book}/conversation").json() == original
        assert (
            client.put(
                f"/api/books/{book}/progress", json={"current_chapter": 2}
            ).status_code
            == 200
        )
        assert client.get(f"/api/books/{book}/conversation").json() == []
        assert (
            client.put(
                f"/api/books/{book}/progress", json={"current_chapter": 3}
            ).status_code
            == 200
        )
        assert client.get(f"/api/books/{book}/conversation").json() == []


def test_reconfirming_chapters_starts_a_new_conversation(reading_setup):
    book, _ = reading_setup
    headers = {"Origin": "http://127.0.0.1:8000", "X-Spoiless-Action": "1"}
    with TestClient(
        app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 1234)
    ) as client:
        assert (
            client.post(
                f"/api/books/{book}/answer",
                json={"question": "zebra", "model": "model", "confirm": True},
                headers=headers,
            ).status_code
            == 200
        )
        units = client.get(f"/api/books/{book}/reading-units").json()
        assert (
            client.put(
                f"/api/books/{book}/reading-units", json={"units": units}
            ).status_code
            == 204
        )
        assert (
            client.put(
                f"/api/books/{book}/progress", json={"current_chapter": 2}
            ).status_code
            == 200
        )
        assert client.get(f"/api/books/{book}/conversation").json() == []


def test_conversations_are_isolated_by_book_and_require_local_access(reading_setup):
    book, _ = reading_setup
    other = library.add_book(Book("Other", (Section("First. Second."),)))
    library.confirm_reading_units(
        other,
        [
            library.ReadingUnitStart("chapter", 0, 0),
            library.ReadingUnitStart("chapter", 0, 7),
        ],
    )
    library.set_progress(other, 2)
    headers = {"Origin": "http://127.0.0.1:8000", "X-Spoiless-Action": "1"}
    with TestClient(
        app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 1234)
    ) as client:
        assert (
            client.post(
                f"/api/books/{book}/answer",
                json={"question": "zebra", "model": "model", "confirm": True},
                headers=headers,
            ).status_code
            == 200
        )
        assert client.get(f"/api/books/{other}/conversation").json() == []
        response = client.get(f"/api/books/{book}/conversation")
        assert response.headers["cache-control"] == "no-store"
        assert len(response.json()) == 1
        assert client.get("/api/books/missing/conversation").status_code == 404
        assert client.delete(f"/api/books/{book}").status_code == 204
        assert client.get(f"/api/books/{book}/conversation").status_code == 404
    with TestClient(
        app, base_url="http://127.0.0.1:8000", client=("192.0.2.1", 1234)
    ) as remote:
        assert remote.get(f"/api/books/{other}/conversation").status_code == 403


def test_invalid_citation_is_withheld_with_safe_error(reading_setup, monkeypatch):
    book, _ = reading_setup

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
    headers = {"Origin": "http://127.0.0.1:8000", "X-Spoiless-Action": "1"}
    with TestClient(
        app,
        base_url="http://127.0.0.1:8000",
        client=("127.0.0.1", 1234),
        raise_server_exceptions=False,
    ) as client:
        response = client.post(
            f"/api/books/{book}/answer",
            json={"question": "key", "model": "model", "confirm": True},
            headers=headers,
        )
        history = client.get(f"/api/books/{book}/conversation")
    assert response.status_code == 502
    assert history.json() == []
    assert "UNREAD_SECRET" not in response.text
    assert "secret-token" not in response.text


def test_progress_change_during_request_returns_conflict(reading_setup, monkeypatch):
    book, _ = reading_setup

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
    headers = {"Origin": "http://127.0.0.1:8000", "X-Spoiless-Action": "1"}
    with TestClient(
        app,
        base_url="http://127.0.0.1:8000",
        client=("127.0.0.1", 1234),
        raise_server_exceptions=False,
    ) as client:
        response = client.post(
            f"/api/books/{book}/answer",
            json={"question": "key", "model": "model", "confirm": True},
            headers=headers,
        )
        history = client.get(f"/api/books/{book}/conversation")
    assert response.status_code == 409
    assert history.json() == []
    assert "Mira" not in response.text


def test_provider_failure_returns_safe_retry_error(reading_setup, monkeypatch):
    book, _ = reading_setup

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
        return httpx.Response(
            503, json={"error": {"message": "secret-token UNREAD_SECRET"}}
        )

    monkeypatch.setattr(
        httpx.HTTPTransport, "handle_request", lambda self, request: handle(request)
    )
    headers = {"Origin": "http://127.0.0.1:8000", "X-Spoiless-Action": "1"}
    with TestClient(
        app,
        base_url="http://127.0.0.1:8000",
        client=("127.0.0.1", 1234),
        raise_server_exceptions=False,
    ) as client:
        response = client.post(
            f"/api/books/{book}/answer",
            json={"question": "key", "model": "model", "confirm": True},
            headers=headers,
        )
    assert response.status_code == 503
    assert "secret-token" not in response.text and "UNREAD_SECRET" not in response.text


def test_plan_usage_limit_has_actionable_response(reading_setup, monkeypatch):
    book, _ = reading_setup

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
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=(
                'data: {"type":"response.failed","response":'
                '{"status":"failed","error":{"code":'
                '"subscription_sharing_usage_limit_exceeded"}}}\n\n'
            ),
        )

    monkeypatch.setattr(
        httpx.HTTPTransport, "handle_request", lambda self, request: handle(request)
    )
    headers = {"Origin": "http://127.0.0.1:8000", "X-Spoiless-Action": "1"}
    with TestClient(
        app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 1234)
    ) as client:
        response = client.post(
            f"/api/books/{book}/answer",
            json={"question": "key", "model": "model", "confirm": True},
            headers=headers,
        )
    assert response.status_code == 429
    assert (
        response.json()["detail"]["code"] == "subscription_sharing_usage_limit_exceeded"
    )


def test_missing_progress_and_missing_book_return_safe_client_errors(
    reading_setup, monkeypatch
):
    book, _ = reading_setup
    library.confirm_reading_units(book, [library.ReadingUnitStart("chapter", 0, 0)])
    requests = []
    monkeypatch.setattr(
        httpx.HTTPTransport,
        "handle_request",
        lambda self, request: requests.append(request),
    )
    headers = {"Origin": "http://127.0.0.1:8000", "X-Spoiless-Action": "1"}
    with TestClient(
        app,
        base_url="http://127.0.0.1:8000",
        client=("127.0.0.1", 1234),
        raise_server_exceptions=False,
    ) as client:
        payload = {"question": "key", "model": "model", "confirm": True}
        assert (
            client.post(
                f"/api/books/{book}/answer", json=payload, headers=headers
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/books/no-such-book/answer", json=payload, headers=headers
            ).status_code
            == 404
        )
    assert requests == []


def test_model_catalog_failure_returns_safe_service_error(reading_setup, monkeypatch):
    book, _ = reading_setup
    monkeypatch.setattr(
        httpx.HTTPTransport,
        "handle_request",
        lambda self, request: httpx.Response(503, text="secret-token"),
    )
    headers = {"Origin": "http://127.0.0.1:8000", "X-Spoiless-Action": "1"}
    with TestClient(
        app,
        base_url="http://127.0.0.1:8000",
        client=("127.0.0.1", 1234),
        raise_server_exceptions=False,
    ) as client:
        response = client.post(
            f"/api/books/{book}/answer",
            json={"question": "key", "model": "model", "confirm": True},
            headers=headers,
        )
    assert response.status_code == 503
    assert "secret-token" not in response.text


def test_removed_credentials_prompt_user_to_sign_in_again(reading_setup):
    book, _ = reading_setup
    chatgpt_credentials.delete_credentials("oaiapp_reader")
    headers = {"Origin": "http://127.0.0.1:8000", "X-Spoiless-Action": "1"}
    with TestClient(
        app,
        base_url="http://127.0.0.1:8000",
        client=("127.0.0.1", 1234),
        raise_server_exceptions=False,
    ) as client:
        response = client.post(
            f"/api/books/{book}/answer",
            json={"question": "key", "model": "model", "confirm": True},
            headers=headers,
        )
    assert response.status_code == 409
    assert "sign in" in response.text.lower()


def test_keyring_failure_is_reported_without_private_details(
    reading_setup, monkeypatch
):
    book, _ = reading_setup

    def unavailable(self, service, username):
        raise RuntimeError("secret-keyring-info")

    monkeypatch.setattr(MemoryKeyring, "get_password", unavailable)
    headers = {"Origin": "http://127.0.0.1:8000", "X-Spoiless-Action": "1"}
    with TestClient(
        app,
        base_url="http://127.0.0.1:8000",
        client=("127.0.0.1", 1234),
        raise_server_exceptions=False,
    ) as client:
        response = client.post(
            f"/api/books/{book}/answer",
            json={"question": "key", "model": "model", "confirm": True},
            headers=headers,
        )
    assert response.status_code == 503
    assert "secret-keyring-info" not in response.text


def test_switching_account_during_model_discovery_blocks_answer_request(
    reading_setup, monkeypatch
):
    book, _ = reading_setup
    other = chatgpt_accounts.remember_verified(
        "oaiapp_other", VerifiedIdentity("other", None)
    )
    requests = []

    def handle(request):
        requests.append(request)
        if request.method == "GET":
            chatgpt_accounts.activate_after_storage(other)
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
    headers = {"Origin": "http://127.0.0.1:8000", "X-Spoiless-Action": "1"}
    with TestClient(
        app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 1234)
    ) as client:
        response = client.post(
            f"/api/books/{book}/answer",
            json={"question": "key", "model": "model", "confirm": True},
            headers=headers,
        )
    assert response.status_code == 409
    assert all(request.method == "GET" for request in requests)


def test_no_active_account_requires_sign_in(reading_setup, monkeypatch):
    book, _ = reading_setup
    chatgpt_accounts.clear_active_account()
    requests = []
    monkeypatch.setattr(
        httpx.HTTPTransport,
        "handle_request",
        lambda self, request: requests.append(request),
    )
    headers = {"Origin": "http://127.0.0.1:8000", "X-Spoiless-Action": "1"}
    with TestClient(
        app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 1234)
    ) as client:
        response = client.post(
            f"/api/books/{book}/answer",
            json={"question": "key", "model": "model", "confirm": True},
            headers=headers,
        )
    assert response.status_code == 409
    assert "connect" in response.text.lower()
    assert requests == []


def test_refresh_network_failure_reports_retry_without_leaking_tokens(
    reading_setup, monkeypatch
):
    book, _ = reading_setup
    original = chatgpt_credentials.load_credentials("oaiapp_reader")
    chatgpt_credentials.save_credentials(
        original.model_copy(update={"expires_at": float(time.time() - 1)}),
        VerifiedIdentity(original.subject, original.email),
    )
    monkeypatch.setattr(
        httpx.HTTPTransport,
        "handle_request",
        lambda self, request: httpx.Response(503, json={"error": "secret-token"}),
    )
    headers = {"Origin": "http://127.0.0.1:8000", "X-Spoiless-Action": "1"}
    with TestClient(
        app,
        base_url="http://127.0.0.1:8000",
        client=("127.0.0.1", 1234),
        raise_server_exceptions=False,
    ) as client:
        response = client.post(
            f"/api/books/{book}/answer",
            json={"question": "key", "model": "model", "confirm": True},
            headers=headers,
        )
    assert response.status_code == 503
    assert "secret-token" not in response.text


def test_request_cannot_supply_another_account(reading_setup, monkeypatch):
    book, _ = reading_setup
    requests = []
    monkeypatch.setattr(
        httpx.HTTPTransport,
        "handle_request",
        lambda self, request: requests.append(request),
    )
    headers = {"Origin": "http://127.0.0.1:8000", "X-Spoiless-Action": "1"}
    with TestClient(
        app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 1234)
    ) as client:
        response = client.post(
            f"/api/books/{book}/answer",
            json={
                "question": "key",
                "model": "model",
                "confirm": True,
                "account_id": "other",
            },
            headers=headers,
        )
    assert response.status_code == 422
    assert requests == []


def test_no_matching_passages_returns_refusal_without_network(
    reading_setup, monkeypatch
):
    book, _ = reading_setup
    requests = []
    monkeypatch.setattr(
        httpx.HTTPTransport,
        "handle_request",
        lambda self, request: requests.append(request),
    )
    headers = {"Origin": "http://127.0.0.1:8000", "X-Spoiless-Action": "1"}
    with TestClient(
        app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 1234)
    ) as client:
        response = client.post(
            f"/api/books/{book}/answer",
            json={"question": "unicorn", "model": "model", "confirm": True},
            headers=headers,
        )
    assert response.status_code == 200
    assert response.json() == {
        "answer": "I couldn't find enough information in the completed chapters.",
        "citations": [],
    }
    assert requests == []
