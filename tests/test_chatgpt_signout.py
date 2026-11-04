import time
from urllib.parse import parse_qs

import httpx
import pytest
from fastapi.testclient import TestClient

from spoiless import chatgpt_accounts, chatgpt_credentials, chatgpt_session, main
from spoiless.chatgpt_auth import VerifiedIdentity
from spoiless.chatgpt_credentials import CredentialRecord


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
def account(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    keyring = MemoryKeyring()
    monkeypatch.setattr(chatgpt_credentials, "_backend", lambda: keyring)
    monkeypatch.setattr(main, "_sign_in", chatgpt_session.SignInManager())
    identity = VerifiedIdentity("reader", "reader@example.test")
    account_id = chatgpt_accounts.remember_verified("oaiapp_reader", identity)
    record = CredentialRecord(
        client_id="oaiapp_reader",
        subject=identity.subject,
        email=identity.email,
        id_token="id-secret",
        access_token="access-secret",
        refresh_token="refresh-secret",
        token_type="Bearer",
        expires_at=float(time.time() + 3600),
        scope="openid offline_access resource.invoke chatgpt.tokens.use.direct",
    )
    chatgpt_credentials.save_credentials(record, identity)
    chatgpt_accounts.activate_after_storage(account_id)
    return account_id


def test_signout_revokes_and_clears_active_account(account, monkeypatch):
    requests = []

    def handle(request):
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "revocation_endpoint": "https://auth.openai.com/api/accounts/oauth/revoke"
                },
            )
        return httpx.Response(200)

    headers = {"Origin": "http://127.0.0.1:8000", "X-Spoiless-Action": "1"}
    with TestClient(
        main.app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 1234)
    ) as client:
        real_client = httpx.Client
        monkeypatch.setattr(
            httpx,
            "Client",
            lambda **kwargs: real_client(
                transport=httpx.MockTransport(handle), **kwargs
            ),
        )
        response = client.post(
            "/api/chatgpt/sign-out", json={"confirm": True}, headers=headers
        )
        assert response.status_code == 200
        assert response.json() == {"revocation_confirmed": True}
        assert client.get("/api/chatgpt/sign-in").json()["status"] == "idle"
        assert client.get("/api/chatgpt/accounts").json() == [
            {"id": account, "email": "reader@example.test", "active": False}
        ]
        assert (
            client.post(
                "/api/chatgpt/accounts/select",
                json={"account_id": account, "confirm": True},
                headers=headers,
            ).status_code
            == 409
        )
    assert (
        str(requests[0].url)
        == "https://auth.openai.com/.well-known/openid-configuration"
    )
    assert str(requests[1].url) == "https://auth.openai.com/api/accounts/oauth/revoke"
    assert parse_qs(requests[1].content.decode()) == {
        "token": ["refresh-secret"],
        "token_type_hint": ["refresh_token"],
        "client_id": ["oaiapp_reader"],
    }


def test_signout_reports_unconfirmed_after_temporary_provider_failure(
    account, monkeypatch
):
    requests = []

    def handle(request):
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "revocation_endpoint": "https://auth.openai.com/api/accounts/oauth/revoke"
                },
            )
        return httpx.Response(503)

    headers = {"Origin": "http://127.0.0.1:8000", "X-Spoiless-Action": "1"}
    with TestClient(
        main.app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 1234)
    ) as client:
        real_client = httpx.Client
        monkeypatch.setattr(
            httpx,
            "Client",
            lambda **kwargs: real_client(
                transport=httpx.MockTransport(handle), **kwargs
            ),
        )
        monkeypatch.setattr(time, "sleep", lambda seconds: None)
        response = client.post(
            "/api/chatgpt/sign-out", json={"confirm": True}, headers=headers
        )
        assert response.status_code == 200
        assert response.json() == {"revocation_confirmed": False}
        assert client.get("/api/chatgpt/sign-in").json()["status"] == "idle"
        assert (
            client.post(
                "/api/chatgpt/accounts/select",
                json={"account_id": account, "confirm": True},
                headers=headers,
            ).status_code
            == 409
        )
    assert len([request for request in requests if request.method == "POST"]) == 3


def test_signout_does_not_send_token_to_untrusted_discovery_endpoint(
    account, monkeypatch
):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(
            200, json={"revocation_endpoint": "https://attacker.example/steal"}
        )

    headers = {"Origin": "http://127.0.0.1:8000", "X-Spoiless-Action": "1"}
    with TestClient(
        main.app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 1234)
    ) as client:
        real_client = httpx.Client
        monkeypatch.setattr(
            httpx,
            "Client",
            lambda **kwargs: real_client(
                transport=httpx.MockTransport(handle), **kwargs
            ),
        )
        response = client.post(
            "/api/chatgpt/sign-out", json={"confirm": True}, headers=headers
        )
        assert response.json() == {"revocation_confirmed": False}
        assert client.get("/api/chatgpt/sign-in").json()["status"] == "idle"
    assert len(requests) == 1 and requests[0].method == "GET"


def test_signout_rejects_untrusted_requests(account):
    with TestClient(
        main.app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 1234)
    ) as client:
        for headers, payload in [
            ({}, {"confirm": True}),
            (
                {"Origin": "https://attacker.example", "X-Spoiless-Action": "1"},
                {"confirm": True},
            ),
            (
                {"Origin": "http://127.0.0.1:8000", "X-Spoiless-Action": "1"},
                {"confirm": False},
            ),
        ]:
            assert client.post(
                "/api/chatgpt/sign-out", json=payload, headers=headers
            ).status_code in (403, 422)
        assert client.get("/api/chatgpt/accounts").json()[0]["active"] is True


def test_signout_can_clear_selection_after_credentials_already_disappeared(account):
    chatgpt_credentials.delete_credentials("oaiapp_reader")
    headers = {"Origin": "http://127.0.0.1:8000", "X-Spoiless-Action": "1"}
    with TestClient(
        main.app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 1234)
    ) as client:
        response = client.post(
            "/api/chatgpt/sign-out", json={"confirm": True}, headers=headers
        )
        assert response.status_code == 200
        assert response.json() == {"revocation_confirmed": False}
        assert client.get("/api/chatgpt/sign-in").json()["status"] == "idle"


def test_signout_preserves_other_saved_account(account, monkeypatch):
    other_identity = VerifiedIdentity("other-reader", "reader@example.test")
    other_id = chatgpt_accounts.remember_verified("oaiapp_other", other_identity)
    other = CredentialRecord(
        client_id="oaiapp_other",
        subject=other_identity.subject,
        email=other_identity.email,
        id_token="other-id",
        access_token="other-access",
        refresh_token="other-refresh",
        token_type="Bearer",
        expires_at=float(time.time() + 3600),
        scope="openid offline_access chatgpt.tokens.use.direct",
    )
    chatgpt_credentials.save_credentials(other, other_identity)
    headers = {"Origin": "http://127.0.0.1:8000", "X-Spoiless-Action": "1"}

    def handle(request):
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "revocation_endpoint": "https://auth.openai.com/api/accounts/oauth/revoke"
                },
            )
        return httpx.Response(200)

    with TestClient(
        main.app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 1234)
    ) as client:
        real_client = httpx.Client
        monkeypatch.setattr(
            httpx,
            "Client",
            lambda **kwargs: real_client(
                transport=httpx.MockTransport(handle), **kwargs
            ),
        )
        assert (
            client.post(
                "/api/chatgpt/sign-out", json={"confirm": True}, headers=headers
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/api/chatgpt/accounts/select",
                json={"account_id": other_id, "confirm": True},
                headers=headers,
            ).status_code
            == 200
        )
        assert client.get("/api/chatgpt/accounts").json()[1]["active"] is True
