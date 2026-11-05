"""Offline building blocks for local Sign in with ChatGPT.

These functions do not start a listener, exchange tokens, or store credentials.
"""

import base64
import hashlib
import secrets
import time
from dataclasses import dataclass, field
from threading import Lock
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import uuid4

import jwt

from spoiless.database import connect

ISSUER = "https://auth.openai.com"
AUTHORIZE_URL = f"{ISSUER}/api/accounts/authorize"
RESOURCE = "https://api.openai.com/v1"
DYNAMIC_CLIENT = "dynamic_agent_client"
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
ATTEMPT_SECONDS = 600


class InvalidAuthorization(ValueError):
    """An authorization attempt or identity token could not be verified."""


class AuthorizationDenied(InvalidAuthorization):
    """The reader declined the authorization request."""


def host_id() -> str:
    """Persist an opaque host identifier; this identifier is not a credential."""
    with connect() as db, db:
        db.execute(
            "INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)",
            ("chatgpt_host_id", f"urn:uuid:{uuid4()}"),
        )
        row = db.execute(
            "SELECT value FROM app_settings WHERE key = ?", ("chatgpt_host_id",)
        ).fetchone()
    return row[0]


def _client_id(value: str) -> bool:
    return (
        bool(value)
        and len(value) <= 512
        and value.isascii()
        and not any(char.isspace() or not char.isprintable() for char in value)
    )


@dataclass(repr=False)
class AuthorizationAttempt:
    """One short-lived transaction; only a matching callback consumes it."""

    redirect_uri: str
    state: str = field(default_factory=lambda: secrets.token_urlsafe(32), init=False)
    nonce: str = field(default_factory=lambda: secrets.token_urlsafe(32), init=False)
    verifier: str = field(default_factory=lambda: secrets.token_urlsafe(64), init=False)
    created: float = field(default_factory=time.monotonic, init=False)
    returning_client_id: str | None = None
    _used: bool = field(default=False, init=False)
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        try:
            parts = urlsplit(self.redirect_uri)
            port = parts.port
            valid_redirect = (
                port is not None
                and 1 <= port <= 65535
                and self.redirect_uri == f"http://127.0.0.1:{port}/auth/callback"
            )
        except ValueError:
            valid_redirect = False
        if not valid_redirect:
            raise InvalidAuthorization("Invalid local callback address.")
        if self.returning_client_id is not None and (
            not _client_id(self.returning_client_id)
            or self.returning_client_id == DYNAMIC_CLIENT
        ):
            raise InvalidAuthorization("Invalid registered client ID.")

    def authorization_url(
        self, agent_host_id: str, *, id_token_hint: str | None = None
    ) -> str:
        """Build the request; callers must never log the URL or its ID-token hint."""
        if id_token_hint is not None and (
            self.returning_client_id is None
            or not isinstance(id_token_hint, str)
            or not id_token_hint
            or len(id_token_hint) > 65536
            or not id_token_hint.isascii()
            or not all(
                char.isprintable() and not char.isspace() for char in id_token_hint
            )
        ):
            raise InvalidAuthorization("Invalid sign-in hint.")
        try:
            from uuid import UUID

            value = agent_host_id.removeprefix("urn:uuid:")
            parsed = UUID(value)
            valid_host = parsed.version == 4 and agent_host_id == f"urn:uuid:{parsed}"
        except (ValueError, AttributeError):
            valid_host = False
        if not valid_host:
            raise InvalidAuthorization("Invalid host identifier.")
        with self._lock:
            if self._used or time.monotonic() - self.created > ATTEMPT_SECONDS:
                raise InvalidAuthorization(
                    "Authorization attempt is invalid or expired."
                )
        challenge = (
            base64.urlsafe_b64encode(
                hashlib.sha256(self.verifier.encode("ascii")).digest()
            )
            .decode("ascii")
            .rstrip("=")
        )
        params = {
            "client_id": self.returning_client_id or DYNAMIC_CLIENT,
            "ext_agent_host_id": agent_host_id,
            "response_type": "code",
            "redirect_uri": self.redirect_uri,
            "scope": SCOPES,
            "resource": RESOURCE,
            "state": self.state,
            "nonce": self.nonce,
            "code_challenge_method": "S256",
            "code_challenge": challenge,
        }
        if self.returning_client_id is None:
            params["agent_name_hint"] = "Spoiless"
        elif id_token_hint is not None:
            params["id_token_hint"] = id_token_hint
        with self._lock:
            if self._used or time.monotonic() - self.created > ATTEMPT_SECONDS:
                raise InvalidAuthorization(
                    "Authorization attempt is invalid or expired."
                )
            return f"{AUTHORIZE_URL}?{urlencode(params)}"

    def accept_callback(self, query: str) -> tuple[str, str]:
        """Return code and issued client ID after validating a one-time callback."""
        if len(query) > 8192:
            raise InvalidAuthorization("Invalid authorization callback.")
        try:
            params = parse_qs(query, keep_blank_values=True, max_num_fields=30)
        except ValueError as exc:
            raise InvalidAuthorization("Invalid authorization callback.") from exc
        with self._lock:
            states = params.get("state", [])
            if (
                self._used
                or time.monotonic() - self.created > ATTEMPT_SECONDS
                or len(states) != 1
                or not secrets.compare_digest(states[0].encode(), self.state.encode())
            ):
                raise InvalidAuthorization("Authorization state is invalid or expired.")
            # Consume before checking errors or code, so a callback cannot be replayed.
            self._used = True
            if any(
                len(params.get(name, [])) > 1 for name in ("code", "client_id", "error")
            ):
                raise InvalidAuthorization("Invalid authorization callback.")
            if "error" in params:
                if params["error"] == ["access_denied"]:
                    raise AuthorizationDenied("Authorization was declined.")
                raise InvalidAuthorization("Authorization failed.")
            codes = params.get("code", [])
            client_ids = params.get("client_id", [])
            client_id = client_ids[0] if client_ids else self.returning_client_id
            if (
                len(codes) != 1
                or not codes[0]
                or len(codes[0]) > 4096
                or not client_id
                or not _client_id(client_id)
                or client_id == DYNAMIC_CLIENT
                or (self.returning_client_id and client_id != self.returning_client_id)
            ):
                raise InvalidAuthorization("Authorization callback is incomplete.")
            return codes[0], client_id


@dataclass(frozen=True, repr=False)
class VerifiedIdentity:
    subject: str
    email: str | None


def verify_identity(
    token: str, client_id: str, nonce: str, trusted_key
) -> VerifiedIdentity:
    """Verify a token using a signing key obtained from OpenAI's trusted JWKS.

    The future network layer must obtain the key from OpenAI, never from the caller.
    This function accepts a key as an offline testing seam and is not an API route.
    """
    if not _client_id(client_id) or client_id == DYNAMIC_CLIENT or not nonce:
        raise InvalidAuthorization("Invalid identity verification parameters.")
    try:
        claims = jwt.decode(
            token,
            trusted_key,
            algorithms=["RS256"],
            audience=client_id,
            issuer=ISSUER,
            leeway=5,
            options={"require": ["sub", "exp", "iat", "nonce"]},
        )
        subject = claims.get("sub")
        token_nonce = claims.get("nonce")
        email = claims.get("email")
        session_id = claims.get("sid")
        audience = claims.get("aud")
        if (
            not isinstance(subject, str)
            or not subject.strip()
            or not isinstance(token_nonce, str)
            or not secrets.compare_digest(token_nonce.encode(), nonce.encode())
            or (email is not None and not isinstance(email, str))
            or (
                session_id is not None
                and (not isinstance(session_id, str) or not session_id.strip())
            )
            or (
                isinstance(audience, list)
                and len(audience) > 1
                and claims.get("azp") != client_id
            )
        ):
            raise InvalidAuthorization("Identity token claims are invalid.")
    except jwt.PyJWTError as exc:
        raise InvalidAuthorization("Identity token verification failed.") from exc
    return VerifiedIdentity(subject=subject, email=email)


def has_plan_permission(granted_scopes: str) -> bool:
    """A verified identity alone does not grant ChatGPT plan usage."""
    return "chatgpt.tokens.use.direct" in granted_scopes.split()
