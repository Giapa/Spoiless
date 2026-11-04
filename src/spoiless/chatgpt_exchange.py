"""Exchange a local authorization callback and verify the OpenAI identity.

This backend-only module is not yet connected to a listener or UI. The HTTP
client uses fixed OpenAI endpoints; callers cannot supply a URL or signing key.
"""

import json
import time
from dataclasses import dataclass
from typing import Literal

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from spoiless.chatgpt_accounts import activate_after_storage, remember_verified
from spoiless.chatgpt_auth import (
    ISSUER,
    RESOURCE,
    AuthorizationAttempt,
    InvalidAuthorization,
    VerifiedIdentity,
    has_plan_permission,
    verify_identity,
)
from spoiless.chatgpt_credentials import (
    CredentialRecord,
    CredentialStoreError,
    load_credentials,
    save_credentials,
)

TOKEN_URL = f"{ISSUER}/api/accounts/oauth/token"
JWKS_URL = f"{ISSUER}/.well-known/jwks.json"
MAX_RESPONSE_BYTES = 256 * 1024


class ExchangeError(Exception):
    """The authorization exchange or trusted-key lookup failed."""


@dataclass(frozen=True, repr=False)
class ConnectedAccount:
    client_id: str
    identity: VerifiedIdentity
    plan_usage_enabled: bool


class _TokenResponse(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")

    id_token: str = Field(min_length=1, max_length=65536, repr=False)
    scope: str = Field(min_length=1, max_length=8192)
    access_token: str | None = Field(
        default=None, min_length=1, max_length=65536, repr=False
    )
    refresh_token: str | None = Field(
        default=None, min_length=1, max_length=65536, repr=False
    )
    token_type: str | None = None
    expires_in: int | None = Field(default=None, gt=0, le=31536000)


def _client() -> httpx.Client:
    # Never send authorization codes to redirected endpoints or environment proxies.
    return httpx.Client(timeout=10.0, follow_redirects=False, trust_env=False)


def _json_request(client: httpx.Client, method: str, url: str, **kwargs) -> dict:
    try:
        with client.stream(
            method, url, headers={"Accept": "application/json"}, **kwargs
        ) as response:
            response.raise_for_status()
            body = bytearray()
            for chunk in response.iter_bytes():
                if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
                    raise ValueError("Response too large")
                body.extend(chunk)
        result = json.loads(body)
        if not isinstance(result, dict):
            raise ValueError("Unexpected response")
        return result
    except (httpx.HTTPError, ValueError, UnicodeError):
        # Never surface server bodies, callback codes, or tokens in an error.
        raise ExchangeError("Could not complete the OpenAI sign-in request.") from None


def _signing_key(client: httpx.Client, id_token: str) -> RSAPublicKey:
    try:
        header = jwt.get_unverified_header(id_token)
        kid = header.get("kid")
        if (
            header.get("alg") != "RS256"
            or not isinstance(kid, str)
            or not kid
            or len(kid) > 256
            or "crit" in header
        ):
            raise ValueError("Invalid token header")
        jwks = _json_request(client, "GET", JWKS_URL)
        keys = jwks.get("keys")
        if not isinstance(keys, list) or len(keys) > 100:
            raise ValueError("Invalid key set")
        matching = [
            key for key in keys if isinstance(key, dict) and key.get("kid") == kid
        ]
        if len(matching) != 1:
            raise ValueError("Signing key not found or ambiguous")
        key = matching[0]
        if (
            key.get("kty") != "RSA"
            or key.get("use", "sig") != "sig"
            or key.get("alg", "RS256") != "RS256"
            or (
                "key_ops" in key
                and (
                    not isinstance(key["key_ops"], list)
                    or "verify" not in key["key_ops"]
                )
            )
            or any(field in key for field in ("d", "p", "q", "dp", "dq", "qi", "oth"))
        ):
            raise ValueError("Unsupported signing key")
        public_key = jwt.PyJWK.from_dict(key, algorithm="RS256").key
        if not isinstance(public_key, RSAPublicKey) or public_key.key_size < 2048:
            raise ValueError("Invalid signing key")
        return public_key
    except ExchangeError:
        raise
    except (jwt.PyJWTError, ValueError, TypeError, KeyError):
        raise ExchangeError("Could not verify the OpenAI signing key.") from None


def exchange_and_store(
    attempt: AuthorizationAttempt,
    callback_query: str,
    *,
    expected_subject: str | None = None,
) -> ConnectedAccount:
    """Consume callback, exchange once, verify identity, then save in the OS keyring.

    For returning sign-ins, expected_subject must come from the selected saved
    registration. Neither tokens nor signing keys may come from the frontend.
    """
    if (attempt.returning_client_id is None) != (expected_subject is None):
        raise InvalidAuthorization("The selected account is missing or invalid.")
    if expected_subject is not None and (
        not isinstance(expected_subject, str) or not expected_subject.strip()
    ):
        raise InvalidAuthorization("The selected account is missing or invalid.")
    code, client_id = attempt.accept_callback(callback_query)
    with _client() as client:
        response = _json_request(
            client,
            "POST",
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "client_id": client_id,
                "code": code,
                "code_verifier": attempt.verifier,
                "redirect_uri": attempt.redirect_uri,
                "resource": RESOURCE,
            },
        )
        received_at = time.time()
        try:
            tokens = _TokenResponse.model_validate(response)
        except ValidationError:
            raise ExchangeError("The OpenAI sign-in response is invalid.") from None
        signing_key = _signing_key(client, tokens.id_token)
        identity = verify_identity(
            tokens.id_token, client_id, attempt.nonce, signing_key
        )
        if expected_subject is not None and identity.subject != expected_subject:
            raise InvalidAuthorization(
                "The signed-in account does not match the selected account."
            )
        token_type: Literal["Bearer"] | None = None
        if tokens.token_type is not None:
            if tokens.token_type.casefold() != "bearer":
                raise ExchangeError("The OpenAI sign-in response is invalid.")
            token_type = "Bearer"
        try:
            record = CredentialRecord(
                client_id=client_id,
                subject=identity.subject,
                email=identity.email,
                id_token=tokens.id_token,
                access_token=tokens.access_token,
                refresh_token=tokens.refresh_token,
                token_type=token_type,
                expires_at=(
                    float(received_at + tokens.expires_in)
                    if tokens.expires_in is not None
                    else None
                ),
                scope=tokens.scope,
            )
        except ValidationError:
            raise ExchangeError("The OpenAI sign-in response is invalid.") from None
    existing = load_credentials(client_id)
    if existing is not None and existing.subject != identity.subject:
        raise CredentialStoreError("The registered client belongs to another account.")
    account_id = remember_verified(client_id, identity)
    save_credentials(record, identity)
    activate_after_storage(account_id)
    return ConnectedAccount(client_id, identity, has_plan_permission(record.scope))
