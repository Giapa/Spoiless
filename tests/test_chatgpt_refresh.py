import time

import pytest

from spoiless import chatgpt_accounts, chatgpt_credentials
from spoiless.chatgpt_auth import VerifiedIdentity
from spoiless.chatgpt_credentials import CredentialRecord
from spoiless.chatgpt_session import get_valid_access_token


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
def saved_account(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    backend = MemoryKeyring()
    monkeypatch.setattr(chatgpt_credentials, "_backend", lambda: backend)
    identity = VerifiedIdentity("reader", "reader@example.test")
    account_id = chatgpt_accounts.remember_verified("oaiapp_reader", identity)
    record = CredentialRecord(
        client_id="oaiapp_reader",
        subject=identity.subject,
        email=identity.email,
        id_token="id-token",
        access_token="existing-token",
        refresh_token="refresh-token",
        token_type="Bearer",
        expires_at=float(time.time() + 3600),
        scope="openid offline_access resource.invoke chatgpt.tokens.use.direct",
    )
    chatgpt_credentials.save_credentials(record, identity)
    return account_id


def test_unexpired_access_token_is_reused(saved_account):
    assert get_valid_access_token(saved_account) == "existing-token"


def test_expired_token_is_refreshed_and_replacement_is_saved(
    saved_account, monkeypatch
):
    import httpx

    original = chatgpt_credentials.load_credentials("oaiapp_reader")
    identity = VerifiedIdentity(original.subject, original.email)
    chatgpt_credentials.save_credentials(
        original.model_copy(update={"expires_at": float(time.time() - 10)}), identity
    )
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "access_token": "new-access",
                "refresh_token": "new-refresh",
                "token_type": "Bearer",
                "expires_in": 3600,
                "scope": original.scope,
            },
        )

    real_client = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handle), **kwargs),
    )
    assert get_valid_access_token(saved_account) == "new-access"
    assert get_valid_access_token(saved_account) == "new-access"
    assert len(requests) == 1
    assert str(requests[0].url) == "https://auth.openai.com/api/accounts/oauth/token"
    from urllib.parse import parse_qs

    assert parse_qs(requests[0].content.decode()) == {
        "grant_type": ["refresh_token"],
        "client_id": ["oaiapp_reader"],
        "refresh_token": ["refresh-token"],
        "resource": ["https://api.openai.com/v1"],
    }
    saved = chatgpt_credentials.load_credentials("oaiapp_reader")
    assert saved.access_token == "new-access"
    assert saved.refresh_token == "new-refresh"


def test_terminal_refresh_error_requires_sign_in_and_clears_unusable_tokens(
    saved_account, monkeypatch
):
    import httpx

    from spoiless.chatgpt_accounts import AccountError

    original = chatgpt_credentials.load_credentials("oaiapp_reader")
    chatgpt_credentials.save_credentials(
        original.model_copy(update={"expires_at": float(time.time() - 10)}),
        VerifiedIdentity(original.subject, original.email),
    )
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(400, json={"error": "invalid_grant"})
            ),
            **kwargs,
        ),
    )
    with pytest.raises(AccountError, match="sign in again"):
        get_valid_access_token(saved_account)
    assert chatgpt_credentials.load_credentials("oaiapp_reader") is None


def test_temporary_failure_preserves_credentials(saved_account, monkeypatch):
    import httpx

    from spoiless.chatgpt_exchange import ExchangeError

    original = chatgpt_credentials.load_credentials("oaiapp_reader")
    expired = original.model_copy(update={"expires_at": float(time.time() - 10)})
    chatgpt_credentials.save_credentials(
        expired, VerifiedIdentity(original.subject, original.email)
    )
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(503, json={"error": "invalid_grant"})
            ),
            **kwargs,
        ),
    )
    with pytest.raises(ExchangeError):
        get_valid_access_token(saved_account)
    assert chatgpt_credentials.load_credentials("oaiapp_reader") == expired


def test_refresh_leaves_other_saved_account_unchanged(saved_account, monkeypatch):
    import httpx

    original = chatgpt_credentials.load_credentials("oaiapp_reader")
    chatgpt_credentials.save_credentials(
        original.model_copy(update={"expires_at": float(time.time() - 10)}),
        VerifiedIdentity(original.subject, original.email),
    )
    other_identity = VerifiedIdentity("other", "reader@example.test")
    other_id = chatgpt_accounts.remember_verified("oaiapp_other", other_identity)
    other = original.model_copy(
        update={
            "client_id": "oaiapp_other",
            "subject": "other",
            "access_token": "other-access",
        }
    )
    chatgpt_credentials.save_credentials(other, other_identity)
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json={
                        "access_token": "new-access",
                        "refresh_token": "new-refresh",
                        "token_type": "Bearer",
                        "expires_in": 3600,
                        "scope": original.scope,
                    },
                )
            ),
            **kwargs,
        ),
    )
    assert get_valid_access_token(saved_account) == "new-access"
    assert get_valid_access_token(other_id) == "other-access"
    assert chatgpt_credentials.load_credentials("oaiapp_other") == other


def test_malformed_provider_error_does_not_leak_or_erase_credentials(
    saved_account, monkeypatch
):
    import httpx

    from spoiless.chatgpt_exchange import ExchangeError

    original = chatgpt_credentials.load_credentials("oaiapp_reader")
    expired = original.model_copy(update={"expires_at": float(time.time() - 10)})
    chatgpt_credentials.save_credentials(
        expired, VerifiedIdentity(original.subject, original.email)
    )
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    400, json={"error": {"secret": "do-not-leak"}}
                )
            ),
            **kwargs,
        ),
    )
    with pytest.raises(ExchangeError) as error:
        get_valid_access_token(saved_account)
    assert "do-not-leak" not in str(error.value)
    assert chatgpt_credentials.load_credentials("oaiapp_reader") == expired


def test_refresh_saves_rotated_token_even_if_plan_permission_was_removed(
    saved_account, monkeypatch
):
    import httpx

    from spoiless.chatgpt_accounts import AccountError

    original = chatgpt_credentials.load_credentials("oaiapp_reader")
    chatgpt_credentials.save_credentials(
        original.model_copy(update={"expires_at": float(time.time() - 10)}),
        VerifiedIdentity(original.subject, original.email),
    )
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json={
                        "access_token": "new-access",
                        "refresh_token": "new-refresh",
                        "token_type": "Bearer",
                        "expires_in": 3600,
                        "scope": "openid offline_access",
                    },
                )
            ),
            **kwargs,
        ),
    )
    with pytest.raises(AccountError):
        get_valid_access_token(saved_account)
    assert (
        chatgpt_credentials.load_credentials("oaiapp_reader").refresh_token
        == "new-refresh"
    )


def test_overlapping_refresh_cannot_reuse_rotating_token(saved_account, monkeypatch):
    import threading

    import httpx

    from spoiless.chatgpt_session import SignInBusy

    original = chatgpt_credentials.load_credentials("oaiapp_reader")
    chatgpt_credentials.save_credentials(
        original.model_copy(update={"expires_at": float(time.time() - 10)}),
        VerifiedIdentity(original.subject, original.email),
    )
    started, release = threading.Event(), threading.Event()

    def handle(request):
        started.set()
        assert release.wait(3)
        return httpx.Response(
            200,
            json={
                "access_token": "new-access",
                "refresh_token": "new-refresh",
                "token_type": "Bearer",
                "expires_in": 3600,
                "scope": original.scope,
            },
        )

    real_client = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handle), **kwargs),
    )
    result = []
    worker = threading.Thread(
        target=lambda: result.append(get_valid_access_token(saved_account))
    )
    worker.start()
    try:
        assert started.wait(3)
        with pytest.raises(SignInBusy):
            get_valid_access_token(saved_account)
    finally:
        release.set()
        worker.join(3)
    assert result == ["new-access"]
    assert get_valid_access_token(saved_account) == "new-access"
