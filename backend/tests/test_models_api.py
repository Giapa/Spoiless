import time

import httpx
import pytest
from fastapi.testclient import TestClient

from src.chatgpt import accounts as chatgpt_accounts
from src.chatgpt import credentials as chatgpt_credentials
from src.chatgpt.auth import VerifiedIdentity
from src.chatgpt.credentials import CredentialRecord
from src.library import storage as library
from src.library.epub import Book, Section
from src.main import app


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


def test_model_list_shows_only_selected_account_visible_models(
    reading_setup, monkeypatch
):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "models": [
                    {
                        "slug": "model-b",
                        "display_name": "Model B",
                        "visibility": "list",
                    },
                    {
                        "slug": "private-model",
                        "display_name": "Hidden",
                        "visibility": "hide",
                    },
                    {
                        "slug": "model-a",
                        "display_name": "Model A",
                        "visibility": "list",
                    },
                ]
            },
        )

    monkeypatch.setattr(
        httpx.HTTPTransport, "handle_request", lambda self, request: handle(request)
    )
    headers = {"Origin": "http://127.0.0.1:8000", "X-Spoiless-Action": "1"}
    with TestClient(
        app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 1234)
    ) as client:
        response = client.post(
            "/api/chatgpt/models", json={"confirm": True}, headers=headers
        )
    assert response.status_code == 200
    assert response.json() == [
        {"slug": "model-b", "display_name": "Model B"},
        {"slug": "model-a", "display_name": "Model A"},
    ]
    assert response.headers["cache-control"] == "no-store"
    assert "secret-token" not in response.text
    assert requests[0].headers["authorization"] == "Bearer secret-token"


def test_switching_accounts_during_lookup_withholds_stale_models(
    reading_setup, monkeypatch
):
    other = chatgpt_accounts.remember_verified(
        "oaiapp_other", VerifiedIdentity("other", None)
    )

    def handle(request):
        chatgpt_accounts.activate_after_storage(other)
        return httpx.Response(
            200,
            json={
                "models": [
                    {
                        "slug": "old-account-model",
                        "display_name": "Old",
                        "visibility": "list",
                    }
                ]
            },
        )

    monkeypatch.setattr(
        httpx.HTTPTransport, "handle_request", lambda self, request: handle(request)
    )
    headers = {"Origin": "http://127.0.0.1:8000", "X-Spoiless-Action": "1"}
    with TestClient(
        app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 1234)
    ) as client:
        response = client.post(
            "/api/chatgpt/models", json={"confirm": True}, headers=headers
        )
    assert response.status_code == 409
    assert "old-account-model" not in response.text


def test_model_lookup_requires_local_confirmed_action(reading_setup, monkeypatch):
    requests = []
    monkeypatch.setattr(
        httpx.HTTPTransport, "handle_request", lambda self, req: requests.append(req)
    )
    good = {"Origin": "http://127.0.0.1:8000", "X-Spoiless-Action": "1"}
    with TestClient(
        app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 1234)
    ) as client:
        for headers, payload in [
            ({}, {"confirm": True}),
            ({**good, "Origin": "https://attacker.example"}, {"confirm": True}),
            (good, {"confirm": False}),
            (good, {"confirm": 1}),
            (good, {"confirm": True, "account_id": "other"}),
        ]:
            assert client.post(
                "/api/chatgpt/models", json=payload, headers=headers
            ).status_code in (403, 422)
    assert requests == []


def test_temporary_model_provider_failure_returns_safe_error(
    reading_setup, monkeypatch
):
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
            "/api/chatgpt/models", json={"confirm": True}, headers=headers
        )
    assert response.status_code == 503
    assert "secret-token" not in response.text


@pytest.mark.parametrize(
    ("status", "expected"),
    [(401, "connection"), (403, "eligibility"), (429, "rate limiting")],
)
def test_model_provider_errors_offer_safe_recovery(
    reading_setup, monkeypatch, status, expected
):
    monkeypatch.setattr(
        httpx.HTTPTransport,
        "handle_request",
        lambda self, request: httpx.Response(status, text="secret-token"),
    )
    headers = {"Origin": "http://127.0.0.1:8000", "X-Spoiless-Action": "1"}
    with TestClient(
        app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 1234)
    ) as client:
        response = client.post(
            "/api/chatgpt/models", json={"confirm": True}, headers=headers
        )
    assert response.status_code == 503
    assert expected in response.json()["detail"]
    assert "secret-token" not in response.text


def test_missing_credentials_requires_signing_in_again(reading_setup):
    chatgpt_credentials.delete_credentials("oaiapp_reader")
    headers = {"Origin": "http://127.0.0.1:8000", "X-Spoiless-Action": "1"}
    with TestClient(
        app,
        base_url="http://127.0.0.1:8000",
        client=("127.0.0.1", 1234),
        raise_server_exceptions=False,
    ) as client:
        response = client.post(
            "/api/chatgpt/models", json={"confirm": True}, headers=headers
        )
    assert response.status_code == 409
    assert "sign in" in response.text.lower()


def test_unavailable_keyring_reports_error_without_private_details(
    reading_setup, monkeypatch
):
    def unavailable(self, service, username):
        raise RuntimeError("private-keyring-error")

    monkeypatch.setattr(MemoryKeyring, "get_password", unavailable)
    headers = {"Origin": "http://127.0.0.1:8000", "X-Spoiless-Action": "1"}
    with TestClient(
        app,
        base_url="http://127.0.0.1:8000",
        client=("127.0.0.1", 1234),
        raise_server_exceptions=False,
    ) as client:
        response = client.post(
            "/api/chatgpt/models", json={"confirm": True}, headers=headers
        )
    assert response.status_code == 503
    assert "private-keyring-error" not in response.text


def test_refresh_outage_reports_retry_without_disclosing_token(
    reading_setup, monkeypatch
):
    original = chatgpt_credentials.load_credentials("oaiapp_reader")
    chatgpt_credentials.save_credentials(
        original.model_copy(update={"expires_at": float(time.time() - 1)}),
        VerifiedIdentity(original.subject, original.email),
    )
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
            "/api/chatgpt/models", json={"confirm": True}, headers=headers
        )
    assert response.status_code == 503
    assert "secret-token" not in response.text


def test_model_lookup_requires_active_account(reading_setup, monkeypatch):
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
            "/api/chatgpt/models", json={"confirm": True}, headers=headers
        )
    assert response.status_code == 409
    assert requests == []


def test_switching_away_and_back_invalidates_in_flight_lookup(
    reading_setup, monkeypatch
):
    _, selected = reading_setup
    other = chatgpt_accounts.remember_verified(
        "oaiapp_other", VerifiedIdentity("other", None)
    )

    def handle(request):
        chatgpt_accounts.activate_after_storage(other)
        chatgpt_accounts.activate_after_storage(selected)
        return httpx.Response(
            200,
            json={
                "models": [
                    {"slug": "old-model", "display_name": "Old", "visibility": "list"}
                ]
            },
        )

    monkeypatch.setattr(
        httpx.HTTPTransport, "handle_request", lambda self, request: handle(request)
    )
    headers = {"Origin": "http://127.0.0.1:8000", "X-Spoiless-Action": "1"}
    with TestClient(
        app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 1234)
    ) as client:
        response = client.post(
            "/api/chatgpt/models", json={"confirm": True}, headers=headers
        )
    assert response.status_code == 409
    assert "old-model" not in response.text
