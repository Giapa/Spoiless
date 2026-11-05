import pytest
from fastapi.testclient import TestClient

from spoiless import main
from spoiless.chatgpt import accounts
from spoiless.chatgpt import session as chatgpt_session
from spoiless.chatgpt.auth import VerifiedIdentity
from spoiless.chatgpt.credentials import CredentialRecord
from spoiless.database import connect


def record(client_id, subject, email="same@example.test"):
    return CredentialRecord(
        client_id=client_id,
        subject=subject,
        email=email,
        id_token="private-id-token",
        access_token="private-access-token",
        refresh_token="private-refresh-token",
        token_type="Bearer",
        expires_at=2000000000.0,
        scope="openid offline_access resource.invoke chatgpt.tokens.use.direct",
    )


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    values = {}
    monkeypatch.setattr(
        accounts, "load_credentials", lambda client_id: values.get(client_id)
    )
    return values


def test_registry_keeps_accounts_separate_and_recovers_selection(store):
    first = record("oaiapp_first", "subject-one")
    second = record("oaiapp_second", "subject-two")
    a = accounts.remember_verified(
        first.client_id, VerifiedIdentity(first.subject, first.email)
    )
    b = accounts.remember_verified(
        second.client_id, VerifiedIdentity(second.subject, second.email)
    )
    assert a != b
    assert (
        accounts.remember_verified(
            first.client_id, VerifiedIdentity(first.subject, first.email)
        )
        == a
    )
    with pytest.raises(accounts.AccountError):
        accounts.remember_verified(
            first.client_id, VerifiedIdentity("other-subject", first.email)
        )
    assert accounts.active_account() is None
    store[first.client_id] = first
    accounts.select_saved_account(a)
    assert accounts.active_account().id == a
    with pytest.raises(accounts.AccountError):
        accounts.select_saved_account(b)
    assert accounts.active_account().id == a
    store[second.client_id] = second
    accounts.select_saved_account(b)
    assert accounts.active_account().id == b
    listed = accounts.list_accounts()
    assert len(listed) == 2 and [item.email for item in listed] == [
        first.email,
        second.email,
    ]
    assert sum(item.active for item in listed) == 1
    with connect() as db:
        dump = "\n".join(db.iterdump())
    for token in (first.id_token, first.access_token, first.refresh_token):
        assert token not in dump


def test_registry_refuses_keyring_subject_mismatch_without_changing_active(store):
    first = record("oaiapp_first", "subject-one")
    second = record("oaiapp_second", "subject-two")
    a = accounts.remember_verified(
        first.client_id, VerifiedIdentity(first.subject, first.email)
    )
    b = accounts.remember_verified(
        second.client_id, VerifiedIdentity(second.subject, second.email)
    )
    store[first.client_id] = first
    accounts.select_saved_account(a)
    store[second.client_id] = record(second.client_id, "wrong-subject")
    with pytest.raises(accounts.AccountError):
        accounts.select_saved_account(b)
    assert accounts.active_account().id == a


def test_new_manager_reports_saved_account_without_claiming_token_validity(store):
    saved = record("oaiapp_first", "subject-one")
    account_id = accounts.remember_verified(
        saved.client_id, VerifiedIdentity(saved.subject, saved.email)
    )
    store[saved.client_id] = saved
    accounts.select_saved_account(account_id)
    state = chatgpt_session.SignInManager().state()
    assert state.status == "saved" and state.email == saved.email
    assert state.plan_usage_enabled is None


def test_registry_api_exposes_no_tokens_and_only_selects_valid_accounts(
    store, monkeypatch
):
    saved = record("oaiapp_first", "subject-one")
    account_id = accounts.remember_verified(
        saved.client_id, VerifiedIdentity(saved.subject, saved.email)
    )
    manager = chatgpt_session.SignInManager()
    monkeypatch.setattr(main, "_sign_in", manager)
    headers = {"Origin": "http://127.0.0.1:8000", "X-Spoiless-Action": "1"}
    with TestClient(
        main.app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50000)
    ) as client:
        listed = client.get("/api/chatgpt/accounts")
        assert listed.json() == [
            {"id": account_id, "email": saved.email, "active": False}
        ]
        assert listed.headers["cache-control"] == "no-store"
        assert saved.subject not in listed.text and saved.client_id not in listed.text
        assert "private-" not in listed.text
        body = {"account_id": account_id, "confirm": True}
        assert client.post("/api/chatgpt/accounts/select", json=body).status_code == 403
        assert (
            client.post(
                "/api/chatgpt/accounts/select", json=body, headers=headers
            ).status_code
            == 409
        )
        store[saved.client_id] = saved
        selected = client.post(
            "/api/chatgpt/accounts/select", json=body, headers=headers
        )
        assert selected.json() == {
            "status": "saved",
            "email": saved.email,
            "plan_usage_enabled": None,
        }
        assert client.get("/api/chatgpt/accounts").json()[0]["active"] is True


def test_selecting_account_is_blocked_during_another_process_signin(store):
    import os

    saved = record("oaiapp_first", "subject-one")
    account_id = accounts.remember_verified(
        saved.client_id, VerifiedIdentity(saved.subject, saved.email)
    )
    store[saved.client_id] = saved
    fd = chatgpt_session._acquire_attempt_lock()
    try:
        with pytest.raises(chatgpt_session.SignInBusy):
            chatgpt_session.SignInManager().select_account(account_id)
        assert accounts.active_account() is None
    finally:
        os.close(fd)
    chatgpt_session.SignInManager().select_account(account_id)
    assert accounts.active_account().id == account_id
