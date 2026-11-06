import time

import httpx
import pytest

from src.chatgpt import accounts as chatgpt_accounts
from src.chatgpt import credentials as chatgpt_credentials
from src.chatgpt.auth import VerifiedIdentity
from src.chatgpt.credentials import CredentialRecord
from src.chatgpt.models import list_available_models


class MemoryKeyring:
    def __init__(self):
        self.values = {}

    def get_password(self, service, username):
        return self.values.get((service, username))

    def set_password(self, service, username, value):
        self.values[(service, username)] = value


@pytest.fixture
def saved_account(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    backend = MemoryKeyring()
    monkeypatch.setattr(chatgpt_credentials, "_backend", lambda: backend)
    identity = VerifiedIdentity("reader", "reader@example.test")
    account = chatgpt_accounts.remember_verified("oaiapp_reader", identity)
    record = CredentialRecord(
        client_id="oaiapp_reader",
        subject=identity.subject,
        email=identity.email,
        id_token="id-token",
        access_token="secret-access",
        refresh_token="secret-refresh",
        token_type="Bearer",
        expires_at=float(time.time() + 3600),
        scope="openid offline_access resource.invoke chatgpt.tokens.use.direct",
    )
    chatgpt_credentials.save_credentials(record, identity)
    return account


def test_model_list_uses_account_token_and_preserves_display_order(
    saved_account, monkeypatch
):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "models": [
                    {
                        "slug": "second",
                        "display_name": "Second model",
                        "visibility": "list",
                    },
                    {"slug": "hidden", "display_name": "Hidden", "visibility": "hide"},
                    {
                        "slug": "first",
                        "display_name": "First model",
                        "visibility": "list",
                    },
                ]
            },
        )

    real_client = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handle), **kwargs),
    )
    assert list_available_models(saved_account) == [
        {"slug": "second", "display_name": "Second model"},
        {"slug": "first", "display_name": "First model"},
    ]
    assert len(requests) == 1
    assert str(requests[0].url) == "https://api.openai.com/v1/models"
    assert requests[0].headers["authorization"] == "Bearer secret-access"


def test_identity_only_account_cannot_request_plan_model_catalog(tmp_path, monkeypatch):
    from src.chatgpt.accounts import AccountError

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    backend = MemoryKeyring()
    monkeypatch.setattr(chatgpt_credentials, "_backend", lambda: backend)
    identity = VerifiedIdentity("reader", None)
    account = chatgpt_accounts.remember_verified("oaiapp_identity", identity)
    record = CredentialRecord(
        client_id="oaiapp_identity",
        subject="reader",
        id_token="id-token",
        scope="openid profile email",
    )
    chatgpt_credentials.save_credentials(record, identity)
    real_client = httpx.Client
    requests = []
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(lambda req: requests.append(req)), **kwargs
        ),
    )
    with pytest.raises(AccountError):
        list_available_models(account)
    assert requests == []


def test_malformed_model_catalog_fails_without_exposing_provider_data(
    saved_account, monkeypatch
):
    from src.chatgpt.models import ModelCatalogError

    real_client = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json={
                        "models": [
                            {"visibility": "list", "slug": "secret-provider-value"}
                        ]
                    },
                )
            ),
            **kwargs,
        ),
    )
    with pytest.raises(ModelCatalogError) as error:
        list_available_models(saved_account)
    assert "secret-provider-value" not in str(error.value)


def test_each_account_uses_its_own_credentials(saved_account, monkeypatch):
    identity = VerifiedIdentity("other-reader", "reader@example.test")
    other_id = chatgpt_accounts.remember_verified("oaiapp_other", identity)
    other = CredentialRecord(
        client_id="oaiapp_other",
        subject=identity.subject,
        email=identity.email,
        id_token="other-id",
        access_token="other-secret",
        refresh_token="other-refresh",
        token_type="Bearer",
        expires_at=float(time.time() + 3600),
        scope="openid offline_access resource.invoke chatgpt.tokens.use.direct",
    )
    chatgpt_credentials.save_credentials(other, identity)

    def handle(request):
        model = (
            "other-model"
            if request.headers["authorization"] == "Bearer other-secret"
            else "reader-model"
        )
        return httpx.Response(
            200,
            json={
                "models": [{"slug": model, "display_name": model, "visibility": "list"}]
            },
        )

    real_client = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handle), **kwargs),
    )
    assert list_available_models(saved_account)[0]["slug"] == "reader-model"
    assert list_available_models(other_id)[0]["slug"] == "other-model"


def test_expired_token_is_refreshed_before_catalog_request(saved_account, monkeypatch):
    original = chatgpt_credentials.load_credentials("oaiapp_reader")
    chatgpt_credentials.save_credentials(
        original.model_copy(update={"expires_at": float(time.time() - 1)}),
        VerifiedIdentity(original.subject, original.email),
    )

    def handle(request):
        if str(request.url) == "https://auth.openai.com/api/accounts/oauth/token":
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
        assert request.headers["authorization"] == "Bearer new-access"
        return httpx.Response(
            200,
            json={
                "models": [
                    {"slug": "allowed", "display_name": "Allowed", "visibility": "list"}
                ]
            },
        )

    real_client = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handle), **kwargs),
    )
    assert list_available_models(saved_account) == [
        {"slug": "allowed", "display_name": "Allowed"}
    ]


def test_provider_failure_does_not_expose_or_delete_credentials(
    saved_account, monkeypatch
):
    from src.chatgpt.models import ModelCatalogError

    real_client = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    503, text="sensitive error secret-access"
                )
            ),
            **kwargs,
        ),
    )
    with pytest.raises(ModelCatalogError) as error:
        list_available_models(saved_account)
    assert "secret-access" not in str(error.value)
    assert error.value.__cause__ is None
    assert (
        chatgpt_credentials.load_credentials("oaiapp_reader").access_token
        == "secret-access"
    )


@pytest.mark.parametrize(
    ("status", "expected"),
    [(401, "connection"), (403, "eligibility"), (429, "rate limiting")],
)
def test_provider_errors_explain_recovery(saved_account, monkeypatch, status, expected):
    from src.chatgpt.models import ModelCatalogError

    real_client = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(status, text="secret-access")
            ),
            **kwargs,
        ),
    )
    with pytest.raises(ModelCatalogError, match=expected) as error:
        list_available_models(saved_account)
    assert "secret-access" not in str(error.value)
