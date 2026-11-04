import json
import time
from urllib.parse import parse_qs, urlencode

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from spoiless import chatgpt_exchange as exchange
from spoiless.chatgpt_auth import AuthorizationAttempt, InvalidAuthorization


@pytest.fixture
def fixture(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    attempt = AuthorizationAttempt("http://127.0.0.1:1455/auth/callback")
    claims = {
        "iss": "https://auth.openai.com",
        "aud": "oaiapp_123",
        "sub": "reader-subject",
        "email": "reader@example.test",
        "iat": int(time.time()),
        "exp": int(time.time()) + 300,
        "nonce": attempt.nonce,
    }
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key(), as_dict=True)
    jwk.update({"kid": "test-key", "use": "sig", "alg": "RS256"})
    token = jwt.encode(claims, key, algorithm="RS256", headers={"kid": "test-key"})
    body = {
        "id_token": token,
        "access_token": "access-secret",
        "refresh_token": "refresh-secret",
        "token_type": "Bearer",
        "expires_in": 3600,
        "scope": "openid offline_access resource.invoke chatgpt.tokens.use.direct",
    }
    saved = []
    monkeypatch.setattr(exchange, "load_credentials", lambda client_id: None)
    monkeypatch.setattr(
        exchange,
        "save_credentials",
        lambda record, identity: saved.append((record, identity)),
    )
    return key, attempt, claims, jwk, body, saved


def wire(monkeypatch, handler):
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        exchange,
        "_client",
        lambda: httpx.Client(
            transport=transport, follow_redirects=False, trust_env=False
        ),
    )


def callback(attempt):
    return urlencode(
        {"state": attempt.state, "code": "one-use-code", "client_id": "oaiapp_123"}
    )


def test_exchange_saves_only_after_openai_signature_verification(fixture, monkeypatch):
    _, attempt, _, jwk, body, saved = fixture
    requests = []

    def handler(request):
        requests.append(request)
        if str(request.url) == exchange.TOKEN_URL:
            assert request.method == "POST"
            form = parse_qs(request.content.decode())
            assert form == {
                "grant_type": ["authorization_code"],
                "client_id": ["oaiapp_123"],
                "code": ["one-use-code"],
                "code_verifier": [attempt.verifier],
                "redirect_uri": [attempt.redirect_uri],
                "resource": [exchange.RESOURCE],
            }
            assert "one-use-code" not in str(request.url)
            return httpx.Response(200, json=body)
        assert str(request.url) == exchange.JWKS_URL and request.method == "GET"
        assert not saved
        return httpx.Response(200, json={"keys": [jwk]})

    wire(monkeypatch, handler)
    account = exchange.exchange_and_store(attempt, callback(attempt))
    assert len(requests) == 2 and len(saved) == 1
    from spoiless import chatgpt_accounts as accounts

    assert accounts.active_account().client_id == account.client_id
    assert account.client_id == "oaiapp_123" and account.plan_usage_enabled
    assert account.identity.subject == "reader-subject"
    assert "access-secret" not in repr(account)
    record, identity = saved[0]
    assert record.subject == identity.subject == "reader-subject"
    assert (
        record.access_token == "access-secret"
        and record.refresh_token == "refresh-secret"
    )
    assert record.expires_at > time.time()
    with pytest.raises(InvalidAuthorization):
        exchange.exchange_and_store(attempt, callback(attempt))


def test_identity_only_signin_is_not_marked_plan_enabled(fixture, monkeypatch):
    _, attempt, _, jwk, body, saved = fixture
    body = {"id_token": body["id_token"], "scope": "openid profile email"}
    wire(
        monkeypatch,
        lambda request: httpx.Response(
            200, json=body if request.method == "POST" else {"keys": [jwk]}
        ),
    )
    account = exchange.exchange_and_store(attempt, callback(attempt))
    assert not account.plan_usage_enabled
    assert saved[0][0].access_token is None


@pytest.mark.parametrize(
    "failure",
    [
        "signature",
        "nonce",
        "issuer",
        "audience",
        "unknown_kid",
        "duplicate_kid",
        "private_jwk",
        "token_missing_scope",
    ],
)
def test_invalid_identity_or_key_never_reaches_storage(fixture, monkeypatch, failure):
    key, attempt, claims, jwk, body, saved = fixture
    if failure == "signature":
        other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        body["id_token"] = jwt.encode(
            claims, other, algorithm="RS256", headers={"kid": "test-key"}
        )
    if failure in {"nonce", "issuer", "audience"}:
        name = {"nonce": "nonce", "issuer": "iss", "audience": "aud"}[failure]
        body["id_token"] = jwt.encode(
            {**claims, name: "wrong"},
            key,
            algorithm="RS256",
            headers={"kid": "test-key"},
        )
    if failure == "unknown_kid":
        jwk["kid"] = "different-key"
    if failure == "private_jwk":
        jwk["d"] = "private"
    if failure == "token_missing_scope":
        del body["scope"]
    keys = [jwk, jwk] if failure == "duplicate_kid" else [jwk]
    wire(
        monkeypatch,
        lambda request: httpx.Response(
            200, json=body if request.method == "POST" else {"keys": keys}
        ),
    )
    with pytest.raises((exchange.ExchangeError, InvalidAuthorization)):
        exchange.exchange_and_store(attempt, callback(attempt))
    assert not saved
    from spoiless import chatgpt_accounts as accounts

    assert accounts.list_accounts() == []


def test_returning_account_mismatch_and_callback_rejection(fixture, monkeypatch):
    key, _, claims, jwk, body, saved = fixture
    attempt = AuthorizationAttempt(
        "http://127.0.0.1:1455/auth/callback", returning_client_id="oaiapp_123"
    )
    body["id_token"] = jwt.encode(
        {**claims, "nonce": attempt.nonce},
        key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )
    wire(
        monkeypatch,
        lambda request: httpx.Response(
            200, json=body if request.method == "POST" else {"keys": [jwk]}
        ),
    )
    with pytest.raises(InvalidAuthorization):
        exchange.exchange_and_store(
            attempt, callback(attempt), expected_subject="different-reader"
        )
    assert not saved
    other = AuthorizationAttempt("http://127.0.0.1:1455/auth/callback")
    with pytest.raises(InvalidAuthorization):
        exchange.exchange_and_store(
            other, "state=wrong&code=private&client_id=oaiapp_123"
        )
    assert not saved


@pytest.mark.parametrize("status", [302, 400, 500])
def test_http_errors_do_not_retry_or_expose_secrets(fixture, monkeypatch, status):
    _, attempt, _, _, _, saved = fixture
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            status,
            headers={"Location": "https://attacker.invalid"},
            json={"error": "sensitive-response"},
        )

    wire(monkeypatch, handler)
    with pytest.raises(exchange.ExchangeError) as error:
        exchange.exchange_and_store(attempt, callback(attempt))
    assert len(requests) == 1
    assert "sensitive-response" not in str(error.value)
    assert "one-use-code" not in str(error.value)
    assert not saved


def test_oversized_server_response_is_rejected(fixture, monkeypatch):
    _, attempt, _, _, _, saved = fixture
    wire(
        monkeypatch,
        lambda request: httpx.Response(
            200, content=json.dumps({"x": "a" * exchange.MAX_RESPONSE_BYTES})
        ),
    )
    with pytest.raises(exchange.ExchangeError):
        exchange.exchange_and_store(attempt, callback(attempt))
    assert not saved


def test_untrusted_header_key_url_is_never_requested(fixture, monkeypatch):
    key, attempt, claims, jwk, body, saved = fixture
    body["id_token"] = jwt.encode(
        claims,
        key,
        algorithm="RS256",
        headers={"kid": "test-key", "jku": "https://attacker.invalid/keys"},
    )
    endpoints = []

    def handler(request):
        endpoints.append(str(request.url))
        return httpx.Response(
            200, json=body if request.method == "POST" else {"keys": [jwk]}
        )

    wire(monkeypatch, handler)
    exchange.exchange_and_store(attempt, callback(attempt))
    assert endpoints == [exchange.TOKEN_URL, exchange.JWKS_URL]
    assert len(saved) == 1


def test_store_failure_does_not_report_connected(fixture, monkeypatch):
    from spoiless.chatgpt_credentials import CredentialStoreError

    _, attempt, _, jwk, body, _ = fixture
    wire(
        monkeypatch,
        lambda request: httpx.Response(
            200, json=body if request.method == "POST" else {"keys": [jwk]}
        ),
    )

    def fail(*args):
        raise CredentialStoreError("System keyring unavailable.")

    monkeypatch.setattr(exchange, "save_credentials", fail)
    with pytest.raises(CredentialStoreError):
        exchange.exchange_and_store(attempt, callback(attempt))


def test_failed_keyring_save_preserves_previous_active_account(fixture, monkeypatch):
    from spoiless import chatgpt_accounts as accounts
    from spoiless.chatgpt_auth import VerifiedIdentity
    from spoiless.chatgpt_credentials import CredentialStoreError

    _, attempt, _, jwk, body, _ = fixture
    old = accounts.remember_verified(
        "oaiapp_old", VerifiedIdentity("old-subject", None)
    )
    accounts.activate_after_storage(old)
    wire(
        monkeypatch,
        lambda request: httpx.Response(
            200, json=body if request.method == "POST" else {"keys": [jwk]}
        ),
    )

    def fail(*args):
        raise CredentialStoreError("Keyring unavailable.")

    monkeypatch.setattr(exchange, "save_credentials", fail)
    with pytest.raises(CredentialStoreError):
        exchange.exchange_and_store(attempt, callback(attempt))
    assert accounts.active_account().id == old
    staged = [
        item for item in accounts.list_accounts() if item.client_id == "oaiapp_123"
    ]
    assert len(staged) == 1 and not staged[0].active
    monkeypatch.setattr(accounts, "load_credentials", lambda client_id: None)
    with pytest.raises(accounts.AccountError):
        accounts.select_saved_account(staged[0].id)
    assert accounts.active_account().id == old


def test_saved_credentials_can_be_recovered_after_activation_failure(
    fixture, monkeypatch
):
    from spoiless import chatgpt_accounts as accounts

    _, attempt, _, jwk, body, saved = fixture
    wire(
        monkeypatch,
        lambda request: httpx.Response(
            200, json=body if request.method == "POST" else {"keys": [jwk]}
        ),
    )

    def fail(*args):
        raise OSError("Simulated interruption")

    monkeypatch.setattr(exchange, "activate_after_storage", fail)
    with pytest.raises(OSError):
        exchange.exchange_and_store(attempt, callback(attempt))
    assert len(saved) == 1
    staged = accounts.list_accounts()[0]
    assert not staged.active
    monkeypatch.setattr(accounts, "load_credentials", lambda client_id: saved[0][0])
    accounts.select_saved_account(staged.id)
    assert accounts.active_account().id == staged.id


def test_existing_keyring_identity_mismatch_is_not_registered(fixture, monkeypatch):
    from spoiless import chatgpt_accounts as accounts
    from spoiless.chatgpt_credentials import CredentialStoreError

    _, attempt, _, jwk, body, saved = fixture
    wire(
        monkeypatch,
        lambda request: httpx.Response(
            200, json=body if request.method == "POST" else {"keys": [jwk]}
        ),
    )
    monkeypatch.setattr(
        exchange,
        "load_credentials",
        lambda client_id: type("Old", (), {"subject": "other"})(),
    )
    with pytest.raises(CredentialStoreError):
        exchange.exchange_and_store(attempt, callback(attempt))
    assert not saved and not accounts.list_accounts()
