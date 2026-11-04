import base64
import hashlib
import time
from urllib.parse import parse_qs, urlencode, urlsplit

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from spoiless.chatgpt_auth import (
    ATTEMPT_SECONDS,
    AUTHORIZE_URL,
    DYNAMIC_CLIENT,
    ISSUER,
    RESOURCE,
    AuthorizationAttempt,
    AuthorizationDenied,
    InvalidAuthorization,
    has_plan_permission,
    host_id,
    verify_identity,
)


def test_host_and_authorization_request(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    first_host = host_id()
    assert first_host == host_id()
    assert first_host.startswith("urn:uuid:")
    attempt = AuthorizationAttempt("http://127.0.0.1:1455/auth/callback")
    second = AuthorizationAttempt("http://127.0.0.1:1455/auth/callback")
    assert len({attempt.state, attempt.nonce, second.state, second.nonce}) == 4
    url = urlsplit(attempt.authorization_url(first_host))
    params = parse_qs(url.query)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(attempt.verifier.encode()).digest())
        .decode()
        .rstrip("=")
    )
    assert url._replace(query="").geturl() == AUTHORIZE_URL
    assert params["client_id"] == [DYNAMIC_CLIENT]
    assert params["agent_name_hint"] == ["Spoiless"]
    assert params["ext_agent_host_id"] == [first_host]
    assert params["code_challenge"] == [challenge]
    assert params["code_challenge_method"] == ["S256"]
    assert params["resource"] == [RESOURCE]
    assert params["state"] == [attempt.state]
    assert params["nonce"] == [attempt.nonce]
    assert attempt.verifier not in url.query
    assert attempt.verifier not in repr(attempt)
    assert has_plan_permission("openid resource.invoke chatgpt.tokens.use.direct")
    assert not has_plan_permission("openid resource.invoke")
    assert not has_plan_permission("openid chatgpt.tokens.use.direct.extra")


@pytest.mark.parametrize(
    "redirect",
    [
        "http://localhost:1455/auth/callback",
        "http://127.0.0.1:1455/callback",
        "https://127.0.0.1:1455/auth/callback",
        "http://127.0.0.1:1455/auth/callback?x=1",
        "http://127.0.0.1/auth/callback",
    ],
)
def test_only_loopback_callback_is_accepted(redirect):
    with pytest.raises(InvalidAuthorization):
        AuthorizationAttempt(redirect)


def test_callback_state_and_one_time_use():
    attempt = AuthorizationAttempt("http://127.0.0.1:1455/auth/callback")
    with pytest.raises(InvalidAuthorization):
        attempt.accept_callback("state=wrong&code=secret&client_id=oaiapp_123")
    query = urlencode(
        {"state": attempt.state, "code": "secret", "client_id": "oaiapp_123"}
    )
    assert attempt.accept_callback(query) == ("secret", "oaiapp_123")
    with pytest.raises(InvalidAuthorization):
        attempt.accept_callback(query)
    with pytest.raises(InvalidAuthorization):
        attempt.authorization_url("urn:uuid:db8a1b8a-5552-4b28-94ee-bddf8fb096b3")


def test_callback_decline_expiry_and_mismatched_client():
    redirect = "http://127.0.0.1:1455/auth/callback"
    denied = AuthorizationAttempt(redirect)
    with pytest.raises(AuthorizationDenied):
        denied.accept_callback(
            urlencode({"state": denied.state, "error": "access_denied"})
        )
    with pytest.raises(InvalidAuthorization):
        denied.accept_callback(urlencode({"state": denied.state, "code": "x"}))
    expired = AuthorizationAttempt(redirect)
    expired.created -= ATTEMPT_SECONDS + 1
    with pytest.raises(InvalidAuthorization):
        expired.accept_callback(urlencode({"state": expired.state, "code": "x"}))
    returning = AuthorizationAttempt(redirect, returning_client_id="oaiapp_original")
    with pytest.raises(InvalidAuthorization):
        returning.accept_callback(
            urlencode({"state": returning.state, "code": "x", "client_id": "different"})
        )
    valid = AuthorizationAttempt(redirect, returning_client_id="oaiapp_original")
    assert valid.accept_callback(urlencode({"state": valid.state, "code": "x"})) == (
        "x",
        "oaiapp_original",
    )
    duplicate = AuthorizationAttempt(redirect)
    query = urlencode(
        {"state": duplicate.state, "code": "one", "client_id": "oaiapp_123"}
    )
    with pytest.raises(InvalidAuthorization):
        duplicate.accept_callback(query + "&code=two")


def test_identity_requires_signature_and_all_bound_claims():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "aud": "oaiapp_123",
        "sub": "verified-subject",
        "iat": now,
        "exp": now + 300,
        "nonce": "expected-nonce",
        "email": "reader@example.test",
    }
    token = jwt.encode(claims, key, algorithm="RS256")
    identity = verify_identity(token, "oaiapp_123", "expected-nonce", key.public_key())
    assert identity.subject == "verified-subject"
    assert identity.email == "reader@example.test"
    assert "reader@example.test" not in repr(identity)
    with pytest.raises(InvalidAuthorization):
        verify_identity(token, "oaiapp_123", "expected-nonce", other_key.public_key())
    for update in (
        {"iss": "https://wrong.example"},
        {"aud": "wrong"},
        {"exp": now - 60},
        {"nonce": "wrong"},
        {"sub": ""},
        {"sid": " "},
        {"aud": ["oaiapp_123", "another"], "azp": "another"},
    ):
        invalid = jwt.encode({**claims, **update}, key, algorithm="RS256")
        with pytest.raises(InvalidAuthorization):
            verify_identity(invalid, "oaiapp_123", "expected-nonce", key.public_key())
