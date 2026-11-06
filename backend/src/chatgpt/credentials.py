"""Local ChatGPT credential records backed only by Linux Secret Service.

These functions are backend-only. They must be called after identity verification;
no credentials are sent to the browser or written to the library database.
"""

import hashlib
import json
import sys
from typing import Literal

from keyring.backends import SecretService
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from src.chatgpt.auth import (
    DYNAMIC_CLIENT,
    VerifiedIdentity,
    _client_id,
    has_plan_permission,
)

SERVICE = "Spoiless ChatGPT"


class CredentialStoreError(Exception):
    """The secure store is unavailable or the stored record is invalid."""


class CredentialRecord(BaseModel):
    """One validated account registration, including its complete token set."""

    model_config = ConfigDict(extra="forbid", strict=True)

    version: Literal[1] = 1
    client_id: str = Field(min_length=1, max_length=512)
    subject: str = Field(min_length=1, max_length=2048, repr=False)
    email: str | None = Field(default=None, max_length=2048, repr=False)
    id_token: str = Field(min_length=1, max_length=65536, repr=False)
    access_token: str | None = Field(
        default=None, min_length=1, max_length=65536, repr=False
    )
    refresh_token: str | None = Field(
        default=None, min_length=1, max_length=65536, repr=False
    )
    token_type: Literal["Bearer"] | None = None
    expires_at: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    scope: str = Field(min_length=1, max_length=8192)

    @field_validator("client_id")
    @classmethod
    def valid_client(cls, value: str) -> str:
        if not _client_id(value) or value == DYNAMIC_CLIENT:
            raise ValueError("Invalid registered client ID.")
        return value

    @field_validator("subject", "id_token", "scope")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A required value is blank.")
        return value

    @field_validator("access_token", "refresh_token")
    @classmethod
    def token_not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("A token is blank.")
        return value

    @model_validator(mode="after")
    def coherent_token_set(self):
        if self.access_token is None:
            if (
                self.refresh_token is not None
                or self.token_type is not None
                or self.expires_at is not None
                or has_plan_permission(self.scope)
            ):
                raise ValueError("The access token is missing.")
        elif self.token_type is None or self.expires_at is None:
            raise ValueError("The access token metadata is missing.")
        return self


def _backend() -> SecretService.Keyring:
    """Select the Linux OS service explicitly; do not fall back to file backends."""
    if sys.platform != "linux":
        raise CredentialStoreError(
            "Secure credential storage is only supported on Linux so far."
        )
    try:
        if SecretService.Keyring.priority <= 0:
            raise RuntimeError("Secret Service unavailable")
        return SecretService.Keyring()
    except Exception:
        raise CredentialStoreError(
            "Linux Secret Service is unavailable. Unlock or enable your system keyring."
        ) from None


def check_credential_store() -> None:
    """Check for the Linux service without reading or writing credentials."""
    _backend()


def _account_key(client_id: str) -> str:
    if not _client_id(client_id) or client_id == DYNAMIC_CLIENT:
        raise CredentialStoreError("Invalid registered client ID.")
    # Avoid exposing account identifiers in the keyring's searchable attributes.
    return hashlib.sha256(client_id.encode("ascii")).hexdigest()


def _load(backend, client_id: str) -> CredentialRecord | None:
    key = _account_key(client_id)
    try:
        value = backend.get_password(SERVICE, key)
    except Exception:
        raise CredentialStoreError("Could not read the system keyring.") from None
    if value is None:
        return None
    try:
        record = CredentialRecord.model_validate_json(value)
        if record.client_id != client_id or not record.subject.strip():
            raise ValueError("Account mismatch")
        return record
    except (ValidationError, ValueError, TypeError):
        # Do not include the stored payload or validation errors in logs or output.
        raise CredentialStoreError("The stored account record is invalid.") from None


def load_credentials(client_id: str) -> CredentialRecord | None:
    """Return a registration only to the backend; None means no saved record."""
    return _load(_backend(), client_id)


def save_credentials(record: CredentialRecord, identity: VerifiedIdentity) -> None:
    """Store one complete token set after the caller verifies its ID token.

    A registration cannot be overwritten by credentials for a different identity.
    Refresh callers must serialize read/refresh/write across processes.
    """
    try:
        record = CredentialRecord.model_validate(record.model_dump())
    except (ValidationError, AttributeError, TypeError):
        raise CredentialStoreError("The account record is invalid.") from None
    key = _account_key(record.client_id)
    if (
        not isinstance(identity, VerifiedIdentity)
        or not identity.subject.strip()
        or record.subject != identity.subject
        or record.email != identity.email
        or not record.id_token.strip()
        or not record.scope.strip()
    ):
        raise CredentialStoreError(
            "The account record does not match the verified identity."
        )
    backend = _backend()
    existing = _load(backend, record.client_id)
    if existing is not None and existing.subject != identity.subject:
        raise CredentialStoreError("The registered client belongs to another account.")
    # Keep all rotating tokens together in one keyring item.
    payload = json.dumps(record.model_dump(), separators=(",", ":"))
    try:
        backend.set_password(SERVICE, key, payload)
    except Exception:
        raise CredentialStoreError(
            "Could not save credentials in the system keyring."
        ) from None


def delete_credentials(client_id: str) -> bool:
    """Remove locally stored credentials; remote revocation is a separate action."""
    backend = _backend()
    key = _account_key(client_id)
    if _load(backend, client_id) is None:
        return False
    try:
        backend.delete_password(SERVICE, key)
    except Exception:
        raise CredentialStoreError(
            "Could not remove credentials from the system keyring."
        ) from None
    return True
