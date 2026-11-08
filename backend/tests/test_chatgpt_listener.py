from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import pytest

from src.chatgpt import listener
from src.chatgpt.auth import AuthorizationDenied, VerifiedIdentity
from src.chatgpt.exchange import ConnectedAccount


@pytest.fixture
def session(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    item = listener.LocalSignIn()
    yield item
    item.close()
    assert item.wait(3)


def url_for(session, query=""):
    uri = session._attempt.redirect_uri
    return f"{uri}?{query}" if query else uri


def test_listener_starts_before_browser_and_filters_wrong_callbacks(
    session, monkeypatch, capsys
):
    opened = []
    monkeypatch.setattr(
        listener.webbrowser, "open", lambda url: opened.append(url) or True
    )
    seen = []

    def exchange(attempt, query):
        seen.append(attempt.accept_callback(query))
        return ConnectedAccount("oaiapp_123", VerifiedIdentity("reader", None), True)

    monkeypatch.setattr(listener, "exchange_and_store", exchange)
    session.open_browser()
    assert len(opened) == 1
    params = parse_qs(urlsplit(opened[0]).query)
    assert params["redirect_uri"] == [session._attempt.redirect_uri]
    assert params["state"] == [session._attempt.state]
    with pytest.raises(RuntimeError):
        session.open_browser()
    with httpx.Client(trust_env=False) as client:
        wrong_state = client.get(url_for(session, "state=wrong&code=secret"))
        assert wrong_state.status_code == 400
        wrong_host = client.get(url_for(session), headers={"Host": "attacker.invalid"})
        assert wrong_host.status_code == 400
        wrong_path = client.get(url_for(session).replace("/auth/callback", "/other"))
        assert wrong_path.status_code == 400
        assert session.status == "pending" and not seen
        query = urlencode(
            {
                "state": session._attempt.state,
                "code": "private-code",
                "client_id": "oaiapp_123",
            }
        )
        response = client.get(url_for(session, query))
    assert response.status_code == 200
    assert "private-code" not in response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert seen == [("private-code", "oaiapp_123")]
    assert session.wait(3) and session.status == "connected"
    assert session.account is not None and session.account.plan_usage_enabled
    assert "private-code" not in capsys.readouterr().err
    assert "private-code" not in repr(session)


def test_denied_or_failed_attempts_close_without_leaking_error(
    session, monkeypatch, capsys
):
    def denied(attempt, query):
        raise AuthorizationDenied("private-denial-detail")

    monkeypatch.setattr(listener, "exchange_and_store", denied)
    query = urlencode({"state": session._attempt.state, "error": "access_denied"})
    with httpx.Client(trust_env=False) as client:
        response = client.get(url_for(session, query))
    assert response.status_code == 200
    assert "private-denial-detail" not in response.text
    assert session.wait(3) and session.status == "denied"
    assert session.account is None
    assert "access_denied" not in capsys.readouterr().err


def test_failed_exchange_does_not_expose_secrets(session, monkeypatch, capsys):
    def fail(attempt, query):
        raise RuntimeError("secret-token")

    monkeypatch.setattr(listener, "exchange_and_store", fail)
    query = urlencode(
        {
            "state": session._attempt.state,
            "code": "private-code",
            "client_id": "oaiapp_123",
        }
    )
    with httpx.Client(trust_env=False) as client:
        response = client.get(url_for(session, query))
    assert response.status_code == 400
    assert "secret-token" not in response.text and "private-code" not in response.text
    assert session.wait(3) and session.status == "failed"
    assert session.account is None
    captured = capsys.readouterr()
    assert "secret-token" not in captured.err and "private-code" not in captured.err


def test_cancel_and_expiry_close_the_listener(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    session = listener.LocalSignIn()
    session.close()
    assert session.wait(3) and session.status == "cancelled"
    monkeypatch.setattr(listener, "ATTEMPT_SECONDS", 0.01)
    expired = listener.LocalSignIn()
    assert expired.wait(3) and expired.status == "expired"
    with pytest.raises(RuntimeError):
        expired.open_browser()


def test_browser_launch_failure_can_retry(session, monkeypatch):
    monkeypatch.setattr(listener.webbrowser, "open", lambda url: False)
    with pytest.raises(RuntimeError):
        session.open_browser()
    monkeypatch.setattr(listener.webbrowser, "open", lambda url: True)
    session.open_browser()
    assert session.status == "pending"


def test_listener_and_exchange_work_together_without_real_account(
    session, monkeypatch, capsys
):
    import time

    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa

    from src.chatgpt import exchange

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key(), as_dict=True)
    jwk.update({"kid": "test-key", "use": "sig", "alg": "RS256"})
    now = int(time.time())
    token = jwt.encode(
        {
            "iss": "https://auth.openai.com",
            "aud": "oaiapp_123",
            "sub": "reader",
            "nonce": session._attempt.nonce,
            "iat": now,
            "exp": now + 300,
        },
        key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )
    body = {
        "id_token": token,
        "access_token": "mock-access-token",
        "refresh_token": "mock-refresh-token",
        "token_type": "Bearer",
        "expires_in": 3600,
        "scope": "openid offline_access resource.invoke chatgpt.tokens.use.direct",
    }
    endpoints = []

    def handler(request):
        endpoints.append(str(request.url))
        return httpx.Response(
            200, json=body if request.method == "POST" else {"keys": [jwk]}
        )

    monkeypatch.setattr(
        exchange,
        "_client",
        lambda: httpx.Client(
            transport=httpx.MockTransport(handler),
            trust_env=False,
            follow_redirects=False,
        ),
    )
    saved = []
    monkeypatch.setattr(exchange, "load_credentials", lambda client_id: None)
    monkeypatch.setattr(
        exchange, "save_credentials", lambda record, identity: saved.append(record)
    )
    query = urlencode(
        {
            "state": session._attempt.state,
            "code": "mock-private-code",
            "client_id": "oaiapp_123",
        }
    )
    with httpx.Client(trust_env=False) as client:
        response = client.get(url_for(session, query))
    assert response.status_code == 200
    assert session.wait(3) and session.status == "connected"
    assert session.account is not None and session.account.plan_usage_enabled
    assert endpoints == [exchange.TOKEN_URL, exchange.JWKS_URL]
    assert len(saved) == 1 and saved[0].subject == "reader"
    captured = capsys.readouterr()
    for secret in (
        "mock-private-code",
        "mock-access-token",
        "mock-refresh-token",
        token,
    ):
        assert secret not in response.text
        assert secret not in captured.err
        assert secret not in captured.out


def test_returning_listener_passes_selected_identity_without_logging_hint(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    opened = []
    monkeypatch.setattr(
        listener.webbrowser, "open", lambda url: opened.append(url) or True
    )
    seen = []

    def exchange(attempt, query, *, expected_subject):
        code, client_id = attempt.accept_callback(query)
        seen.append((code, client_id, expected_subject))
        return ConnectedAccount(
            client_id, VerifiedIdentity(expected_subject, None), True
        )

    monkeypatch.setattr(listener, "exchange_and_store", exchange)
    session = listener.LocalSignIn(
        returning_client_id="oaiapp_saved",
        expected_subject="reader-identity",
        id_token_hint="private.jwt.hint",
    )
    try:
        session.open_browser()
        params = parse_qs(urlsplit(opened[0]).query)
        assert params["client_id"] == ["oaiapp_saved"]
        assert params["id_token_hint"] == ["private.jwt.hint"]
        assert "agent_name_hint" not in params
        query = urlencode({"state": session._attempt.state, "code": "private-code"})
        with httpx.Client(trust_env=False) as client:
            response = client.get(url_for(session, query))
        assert response.status_code == 200
        assert seen == [("private-code", "oaiapp_saved", "reader-identity")]
        assert session.wait(3) and session.status == "connected"
        assert "private.jwt.hint" not in response.text
        assert "private.jwt.hint" not in repr(session)
        captured = capsys.readouterr()
        assert "private.jwt.hint" not in captured.out + captured.err
        assert "private-code" not in captured.out + captured.err
    finally:
        session.close()
        assert session.wait(3)


@pytest.mark.skipif(listener.sys.platform != "linux", reason="Linux packaging behavior")
def test_frozen_linux_browser_uses_system_library_path(session, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(listener.sys, "frozen", True, raising=False)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/bundled/python/libs")
    monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "/system/libs")
    calls = []

    def launch(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(listener.subprocess, "run", launch)
    session.open_browser()
    command, options = calls[0]
    assert command == ["xdg-open", session._url]
    assert options["env"]["LD_LIBRARY_PATH"] == "/system/libs"
    assert "LD_LIBRARY_PATH_ORIG" not in options["env"]
