import json

import pytest
from pydantic import ValidationError

from spoiless import chatgpt_credentials as credentials
from spoiless.chatgpt_auth import VerifiedIdentity


class MemoryKeyring:
    """Test-only keyring; production never falls back to this backend."""

    def __init__(self):
        self.values = {}

    def get_password(self, service, username):
        return self.values.get((service, username))

    def set_password(self, service, username, value):
        self.values[(service, username)] = value

    def delete_password(self, service, username):
        del self.values[(service, username)]


@pytest.fixture
def store(monkeypatch):
    backend = MemoryKeyring()
    monkeypatch.setattr(credentials, "_backend", lambda: backend)
    return backend


def account(client_id="oaiapp_123", subject="reader-a", email="a@example.test"):
    return credentials.CredentialRecord(
        client_id=client_id,
        subject=subject,
        email=email,
        id_token="id-token-secret",
        access_token="access-token-secret",
        refresh_token="refresh-token-secret",
        token_type="Bearer",
        expires_at=2000000000.0,
        scope="openid resource.invoke chatgpt.tokens.use.direct",
    )


def test_store_separate_accounts_rotate_and_delete(store):
    first = account()
    second = account(client_id="oaiapp_456", subject="reader-b", email="a@example.test")
    first_identity = VerifiedIdentity(first.subject, first.email)
    second_identity = VerifiedIdentity(second.subject, second.email)
    assert credentials.load_credentials(first.client_id) is None
    credentials.save_credentials(first, first_identity)
    credentials.save_credentials(second, second_identity)
    assert credentials.load_credentials(first.client_id) == first
    assert credentials.load_credentials(second.client_id) == second
    assert first.access_token not in repr(first)
    assert first.refresh_token not in repr(first)
    assert all(first.client_id not in username for _, username in store.values)
    replacement = first.model_copy(update={"refresh_token": "new-refresh-token"})
    credentials.save_credentials(replacement, first_identity)
    assert credentials.load_credentials(first.client_id) == replacement
    assert credentials.load_credentials(second.client_id) == second
    assert credentials.delete_credentials(first.client_id)
    assert not credentials.delete_credentials(first.client_id)
    assert credentials.load_credentials(second.client_id) == second


def test_unverified_or_changed_identity_cannot_replace_saved_credentials(store):
    original = account()
    identity = VerifiedIdentity(original.subject, original.email)
    credentials.save_credentials(original, identity)
    other = account(subject="different-reader")
    with pytest.raises(credentials.CredentialStoreError):
        credentials.save_credentials(
            other, VerifiedIdentity(other.subject, other.email)
        )
    with pytest.raises(credentials.CredentialStoreError):
        credentials.save_credentials(
            original, VerifiedIdentity("other", original.email)
        )
    with pytest.raises(credentials.CredentialStoreError):
        credentials.save_credentials(original, object())
    assert credentials.load_credentials(original.client_id) == original


def test_corrupt_records_and_keyring_failures_do_not_leak_secrets(store, monkeypatch):
    original = account()
    key = credentials._account_key(original.client_id)
    store.values[(credentials.SERVICE, key)] = '{"access_token":"leaked-secret"}'
    with pytest.raises(credentials.CredentialStoreError) as error:
        credentials.load_credentials(original.client_id)
    assert "leaked-secret" not in str(error.value)
    assert error.value.__cause__ is None
    with pytest.raises(credentials.CredentialStoreError):
        credentials.save_credentials(
            original, VerifiedIdentity(original.subject, original.email)
        )
    assert json.loads(store.values[(credentials.SERVICE, key)]) == {
        "access_token": "leaked-secret"
    }

    def failed(*args):
        raise RuntimeError("sensitive-backend-details")

    monkeypatch.setattr(store, "get_password", failed)
    with pytest.raises(credentials.CredentialStoreError) as error:
        credentials.load_credentials(original.client_id)
    assert "sensitive-backend-details" not in str(error.value)
    assert error.value.__cause__ is None


def test_no_plaintext_fallback_and_invalid_records(monkeypatch):
    # The real backend exposes a class property; this simulates its failure.
    class Meta(type):
        @property
        def priority(cls):
            raise RuntimeError("unavailable")

    class Backend(metaclass=Meta):
        pass

    monkeypatch.setattr(credentials.SecretService, "Keyring", Backend)
    with pytest.raises(credentials.CredentialStoreError):
        credentials._backend()
    with pytest.raises(ValidationError):
        account(client_id="dynamic_agent_client")
    with pytest.raises(ValidationError):
        credentials.CredentialRecord.model_validate(
            account().model_copy(update={"refresh_token": " "}).model_dump()
        )


def test_write_and_delete_errors_do_not_disclose_backend_details(store, monkeypatch):
    original = account()
    identity = VerifiedIdentity(original.subject, original.email)

    def failed(*args):
        raise RuntimeError("sensitive-backend-details")

    with monkeypatch.context() as patch:
        patch.setattr(store, "set_password", failed)
        with pytest.raises(credentials.CredentialStoreError) as error:
            credentials.save_credentials(original, identity)
        assert "sensitive-backend-details" not in str(error.value)
        assert error.value.__cause__ is None
    credentials.save_credentials(original, identity)
    monkeypatch.setattr(store, "delete_password", failed)
    with pytest.raises(credentials.CredentialStoreError) as error:
        credentials.delete_credentials(original.client_id)
    assert "sensitive-backend-details" not in str(error.value)
    assert error.value.__cause__ is None
    assert credentials.load_credentials(original.client_id) == original


def test_identity_without_plan_permission_can_be_saved(store):
    identity = VerifiedIdentity("identity-only", None)
    record = credentials.CredentialRecord(
        client_id="oaiapp_identity",
        subject=identity.subject,
        email=None,
        id_token="identity-token",
        scope="openid profile email",
    )
    credentials.save_credentials(record, identity)
    assert credentials.load_credentials(record.client_id) == record
    assert not credentials.has_plan_permission(record.scope)
    with pytest.raises(ValidationError):
        credentials.CredentialRecord.model_validate(
            {**record.model_dump(), "scope": "openid chatgpt.tokens.use.direct"}
        )
    with pytest.raises(ValidationError):
        credentials.CredentialRecord.model_validate(
            {**record.model_dump(), "refresh_token": "refresh-without-access"}
        )
