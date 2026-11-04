import os
import subprocess
import sys
import threading
import time

import pytest
from fastapi.testclient import TestClient

from spoiless import chatgpt_session, main
from spoiless.chatgpt_auth import VerifiedIdentity
from spoiless.chatgpt_credentials import CredentialStoreError
from spoiless.chatgpt_exchange import ConnectedAccount


class FakeSignIn:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.status = "pending"
        self.account = None
        self.closed = threading.Event()
        self.opened = False

    def open_browser(self):
        self.opened = True

    def close(self):
        if self.status == "pending":
            self.status = "cancelled"
            self.closed.set()

    def wait(self, timeout=None):
        return self.closed.wait(timeout)

    def complete(self):
        self.account = ConnectedAccount(
            "oaiapp_123",
            VerifiedIdentity("private-subject", "reader@example.test"),
            True,
        )
        self.status = "connected"
        self.closed.set()


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(chatgpt_session, "check_credential_store", lambda: None)
    sessions = []

    def make_session(**kwargs):
        session = FakeSignIn(**kwargs)
        sessions.append(session)
        return session

    monkeypatch.setattr(chatgpt_session, "LocalSignIn", make_session)
    manager = chatgpt_session.SignInManager()
    monkeypatch.setattr(main, "_sign_in", manager)
    yield manager, sessions
    if sessions and sessions[-1].status == "pending":
        manager.cancel()
    for session in sessions:
        session.closed.wait(2)


def test_single_attempt_state_and_no_credentials_in_response(setup):
    _, sessions = setup
    headers = {"Origin": "http://127.0.0.1:8000", "X-Spoiless-Action": "1"}
    with TestClient(
        main.app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50000)
    ) as client:
        idle = client.get("/api/chatgpt/sign-in")
        assert idle.json() == {
            "status": "idle",
            "email": None,
            "plan_usage_enabled": None,
        }
        assert idle.headers["cache-control"] == "no-store"
        started = client.post(
            "/api/chatgpt/sign-in", json={"confirm": True}, headers=headers
        )
        assert started.json()["status"] == "pending"
        assert sessions[0].opened
        assert (
            client.post(
                "/api/chatgpt/sign-in", json={"confirm": True}, headers=headers
            ).status_code
            == 409
        )
        sessions[0].complete()
        connected = client.get("/api/chatgpt/sign-in")
        assert connected.json() == {
            "status": "connected",
            "email": "reader@example.test",
            "plan_usage_enabled": True,
        }
        assert "private-subject" not in connected.text
        assert "oaiapp_123" not in connected.text
        assert "token" not in connected.text
        assert (
            client.post(
                "/api/chatgpt/sign-in/cancel", json={"confirm": True}, headers=headers
            ).status_code
            == 409
        )


def test_local_controls_reject_cross_origin_and_missing_intent(setup):
    _, sessions = setup
    good = {"Origin": "http://127.0.0.1:8000", "X-Spoiless-Action": "1"}
    with TestClient(
        main.app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50000)
    ) as client:
        for headers in (
            {},
            {"Origin": "https://attacker.example", "X-Spoiless-Action": "1"},
            {"Origin": "http://127.0.0.1:8000"},
            {"Origin": "null", "X-Spoiless-Action": "1"},
            {**good, "Host": "attacker.example"},
            {**good, "Host": "localhost.attacker.example"},
            {**good, "Host": "127.0.0.1:8000@attacker.example"},
        ):
            assert (
                client.post(
                    "/api/chatgpt/sign-in", json={"confirm": True}, headers=headers
                ).status_code
                == 403
            )
        assert (
            client.post(
                "/api/chatgpt/sign-in", json={"confirm": False}, headers=good
            ).status_code
            == 422
        )
        assert (
            client.get(
                "/api/chatgpt/sign-in", headers={"Host": "attacker.example"}
            ).status_code
            == 403
        )
        assert not sessions
        assert (
            client.post(
                "/api/chatgpt/sign-in", json={"confirm": True}, headers=good
            ).status_code
            == 200
        )
        cancelled = client.post(
            "/api/chatgpt/sign-in/cancel", json={"confirm": True}, headers=good
        )
        assert cancelled.json()["status"] == "cancelled"


def test_missing_secure_store_and_browser_failure_do_not_leak(setup, monkeypatch):
    manager, sessions = setup

    def unavailable():
        raise CredentialStoreError("System keyring unavailable.")

    monkeypatch.setattr(chatgpt_session, "check_credential_store", unavailable)
    with pytest.raises(CredentialStoreError):
        manager.start()
    assert not sessions
    monkeypatch.setattr(chatgpt_session, "check_credential_store", lambda: None)

    class FailingSignIn(FakeSignIn):
        def open_browser(self):
            raise RuntimeError("private-browser-details")

    failed = FailingSignIn()
    monkeypatch.setattr(chatgpt_session, "LocalSignIn", lambda: failed)
    with pytest.raises(chatgpt_session.SignInStartError) as error:
        manager.start()
    assert "private-browser-details" not in str(error.value)
    assert failed.status == "cancelled"
    assert failed.closed.wait(2)


def test_attempt_lock_is_shared_between_processes(setup):
    manager, sessions = setup
    manager.start()
    script = (
        "import os,sys\n"
        "from spoiless.chatgpt_session import _acquire_attempt_lock,SignInBusy\n"
        "\ntry: fd=_acquire_attempt_lock()\nexcept SignInBusy: sys.exit(9)\n"
        "os.close(fd)\n"
    )
    args = [sys.executable, "-c", script]
    locked = subprocess.run(args, env=os.environ.copy(), capture_output=True, text=True)
    assert locked.returncode == 9, locked.stderr
    manager.cancel()
    assert sessions[0].closed.wait(2)
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        released = subprocess.run(
            args, env=os.environ.copy(), capture_output=True, text=True
        )
        if released.returncode == 0:
            break
        time.sleep(0.05)
    assert released.returncode == 0, released.stderr


def test_remote_client_cannot_spoof_local_host(setup):
    _, sessions = setup
    headers = {"Origin": "http://127.0.0.1:8000", "X-Spoiless-Action": "1"}
    with TestClient(
        main.app, base_url="http://127.0.0.1:8000", client=("192.0.2.44", 50000)
    ) as client:
        assert client.get("/api/chatgpt/sign-in").status_code == 403
        assert (
            client.post(
                "/api/chatgpt/sign-in", json={"confirm": True}, headers=headers
            ).status_code
            == 403
        )
    assert not sessions


def test_processing_cannot_be_reported_as_cancelled(setup):
    manager, sessions = setup
    manager.start()
    sessions[0].status = "processing"
    with pytest.raises(chatgpt_session.SignInBusy):
        manager.cancel()
    assert manager.state().status == "processing"
    sessions[0].status = "pending"
    manager.cancel()


def test_lock_rejects_symlink_without_touching_target(setup, tmp_path):
    manager, sessions = setup
    data_dir = tmp_path / "spoiless"
    data_dir.mkdir()
    target = tmp_path / "other-file"
    target.write_text("preserve")
    (data_dir / "chatgpt-sign-in.lock").symlink_to(target)
    with pytest.raises(chatgpt_session.SignInStartError):
        manager.start()
    assert target.read_text() == "preserve"
    assert not sessions


def test_returning_signin_uses_only_selected_saved_identity(setup, monkeypatch):
    from spoiless import chatgpt_accounts as accounts
    from spoiless.chatgpt_credentials import CredentialRecord

    _, sessions = setup
    identity = VerifiedIdentity("selected-subject", "same@example.test")
    chosen = accounts.remember_verified("oaiapp_chosen", identity)
    accounts.remember_verified(
        "oaiapp_other", VerifiedIdentity("other-subject", identity.email)
    )
    record = CredentialRecord(
        client_id="oaiapp_chosen",
        subject=identity.subject,
        email=identity.email,
        id_token="private.jwt.hint",
        scope="openid profile email",
    )
    monkeypatch.setattr(chatgpt_session, "load_credentials", lambda client_id: record)
    headers = {"Origin": "http://127.0.0.1:8000", "X-Spoiless-Action": "1"}
    with TestClient(
        main.app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50000)
    ) as client:
        result = client.post(
            "/api/chatgpt/sign-in",
            json={"confirm": True, "account_id": chosen},
            headers=headers,
        )
        assert result.status_code == 200 and result.json()["status"] == "pending"
        assert sessions[0].kwargs == {
            "returning_client_id": "oaiapp_chosen",
            "expected_subject": "selected-subject",
            "id_token_hint": "private.jwt.hint",
        }
        assert "private.jwt.hint" not in result.text
        assert "selected-subject" not in result.text
        assert "oaiapp_chosen" not in result.text


def test_returning_signin_without_keyring_record_and_unknown_id(setup, monkeypatch):
    from spoiless import chatgpt_accounts as accounts

    manager, sessions = setup
    identity = VerifiedIdentity("reader", None)
    account_id = accounts.remember_verified("oaiapp_saved", identity)
    monkeypatch.setattr(chatgpt_session, "load_credentials", lambda client_id: None)
    with pytest.raises(accounts.AccountError):
        manager.start("missing")
    assert not sessions
    manager.start(account_id)
    assert sessions[0].kwargs == {
        "returning_client_id": "oaiapp_saved",
        "expected_subject": "reader",
        "id_token_hint": None,
    }


def test_mismatched_stored_identity_never_opens_browser(setup, monkeypatch):
    from spoiless import chatgpt_accounts as accounts
    from spoiless.chatgpt_credentials import CredentialRecord

    manager, sessions = setup
    identity = VerifiedIdentity("expected", None)
    account_id = accounts.remember_verified("oaiapp_saved", identity)
    record = CredentialRecord(
        client_id="oaiapp_saved",
        subject="different",
        email=None,
        id_token="private.jwt.hint",
        scope="openid",
    )
    monkeypatch.setattr(chatgpt_session, "load_credentials", lambda client_id: record)
    with pytest.raises(accounts.AccountError):
        manager.start(account_id)
    assert not sessions
    assert accounts.active_account() is None


def test_corrupt_keyring_cannot_start_returning_signin(setup, monkeypatch):
    from spoiless import chatgpt_accounts as accounts

    manager, sessions = setup
    account_id = accounts.remember_verified(
        "oaiapp_saved", VerifiedIdentity("reader", None)
    )

    def fail(client_id):
        raise CredentialStoreError("Saved account is unavailable.")

    monkeypatch.setattr(chatgpt_session, "load_credentials", fail)
    with pytest.raises(CredentialStoreError):
        manager.start(account_id)
    assert not sessions
    assert accounts.active_account() is None


def test_untrusted_hint_or_non_boolean_confirmation_is_rejected(setup):
    _, sessions = setup
    headers = {"Origin": "http://127.0.0.1:8000", "X-Spoiless-Action": "1"}
    with TestClient(
        main.app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50000)
    ) as client:
        for payload in (
            {"confirm": 1},
            {"confirm": False},
            {"confirm": True, "id_token_hint": "untrusted.jwt.hint"},
            {"confirm": True, "returning_client_id": "oaiapp_untrusted"},
        ):
            assert (
                client.post(
                    "/api/chatgpt/sign-in", json=payload, headers=headers
                ).status_code
                == 422
            )
    assert not sessions


def test_explicit_new_signin_can_follow_connected_attempt(setup):
    manager, sessions = setup
    manager.start()
    sessions[0].complete()
    assert manager.state().status == "connected"
    deadline = time.monotonic() + 3
    while True:
        try:
            manager.start()
            break
        except chatgpt_session.SignInBusy:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.05)
    assert len(sessions) == 2 and sessions[1].opened
    assert manager.state().status == "pending"
