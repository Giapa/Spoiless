"""Control one local sign-in attempt without exposing credentials to the UI.

The sign-in attempt is process-local. Backend token access uses the shared OS
lock to coordinate with other local processes.
"""

import os
import stat
import time
from dataclasses import dataclass
from threading import Lock, Thread
from typing import Literal
from urllib.parse import urlsplit

import httpx

try:
    import fcntl
except ImportError:  # The rest of the app can still run on unverified platforms.
    fcntl = None

from spoiless.chatgpt.accounts import (
    AccountError,
    active_account,
    clear_active_account,
    get_account,
    select_saved_account,
)
from spoiless.chatgpt.auth import (
    ISSUER,
    RESOURCE,
    VerifiedIdentity,
    has_plan_permission,
)
from spoiless.chatgpt.credentials import (
    CredentialStoreError,
    check_credential_store,
    delete_credentials,
    load_credentials,
    save_credentials,
)
from spoiless.chatgpt.exchange import (
    TOKEN_URL,
    ExchangeError,
    RefreshTokenInvalid,
    _client,
    _json_request,
)
from spoiless.chatgpt.listener import LocalSignIn, Status
from spoiless.database import database_path


class SignInBusy(Exception):
    """A sign-in is already active or cannot be cancelled."""


class SignInStartError(Exception):
    """The listener or browser could not be started."""


@dataclass(frozen=True)
class SignInState:
    status: Status | Literal["idle", "saved"]
    email: str | None = None
    plan_usage_enabled: bool | None = None


def _acquire_attempt_lock() -> int:
    """Prevent overlapping browser sign-ins across local server processes."""
    if fcntl is None:
        raise SignInStartError("Local sign-in is only supported on Linux so far.")
    path = database_path().parent / "chatgpt-sign-in.lock"
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or info.st_mode & 0o077
            ):
                raise OSError("Invalid sign-in lock file")
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except BaseException:
            os.close(fd)
            raise
    except BlockingIOError:
        raise SignInBusy("A sign-in is already active.") from None
    except OSError:
        raise SignInStartError("Could not secure the local sign-in attempt.") from None


class SignInManager:
    """Own one active attempt; preserve a connected account in this process."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._session: LocalSignIn | None = None

    def state(self) -> SignInState:
        with self._lock:
            session = self._session
            if session is None:
                account = active_account()
                return (
                    SignInState("saved", account.email)
                    if account
                    else SignInState("idle")
                )
            status = session.status
            if status == "connected":
                account = session.account
                if account is None:
                    return SignInState("failed")
                return SignInState(
                    "connected", account.identity.email, account.plan_usage_enabled
                )
            return SignInState(status)

    def start(self, account_id: str | None = None) -> None:
        with self._lock:
            if self._session is not None and self._session.status in {
                "pending",
                "processing",
            }:
                raise SignInBusy("A sign-in is already active.")
            # Hold the OS lock until the listener closes, including during exchange.
            fd = _acquire_attempt_lock()
            try:
                check_credential_store()
                if account_id is None:
                    session = LocalSignIn()
                else:
                    account = get_account(account_id)
                    record = load_credentials(account.client_id)
                    if record is not None and record.subject != account.subject:
                        raise AccountError("The saved account identity does not match.")
                    session = LocalSignIn(
                        returning_client_id=account.client_id,
                        expected_subject=account.subject,
                        id_token_hint=record.id_token if record is not None else None,
                    )
            except (CredentialStoreError, AccountError):
                os.close(fd)
                raise
            except Exception:
                os.close(fd)
                raise SignInStartError("Could not start local sign-in.") from None
            except BaseException:
                os.close(fd)
                raise
            self._session = session

            def release_after_close() -> None:
                try:
                    session.wait()
                finally:
                    os.close(fd)

            try:
                Thread(target=release_after_close, daemon=True).start()
            except Exception:
                session.close()
                session.wait()
                os.close(fd)
                raise SignInStartError("Could not start local sign-in.") from None
        try:
            session.open_browser()
        except Exception:
            session.close()
            raise SignInStartError("Could not open the browser for sign-in.") from None

    def cancel(self) -> None:
        with self._lock:
            if self._session is None or self._session.status != "pending":
                raise SignInBusy("There is no pending sign-in to cancel.")
            self._session.close()
            if self._session.status != "cancelled":
                raise SignInBusy("Sign-in is already being processed.")

    def select_account(self, account_id: str) -> None:
        """Switch saved registrations without claiming their tokens are current."""
        with self._lock:
            if self._session is not None and self._session.status in {
                "pending",
                "processing",
            }:
                raise SignInBusy("A sign-in is already active.")
            fd = _acquire_attempt_lock()
            try:
                select_saved_account(account_id)
            finally:
                os.close(fd)
            self._session = None

    def sign_out(self) -> bool:
        """Revoke and remove the selected account's credentials."""
        with self._lock:
            if self._session is not None and self._session.status in {
                "pending",
                "processing",
            }:
                raise SignInBusy("A sign-in is already active.")
            fd = _acquire_attempt_lock()
            try:
                account = active_account()
                if account is None:
                    raise AccountError("No active account.")
                record = load_credentials(account.client_id)
                if record is not None and record.subject != account.subject:
                    raise AccountError("This account needs to sign in again.")
                confirmed = False
                if record is not None and record.refresh_token:
                    for attempt in range(3):
                        retry = False
                        try:
                            with _client() as client:
                                discovery = _json_request(
                                    client,
                                    "GET",
                                    f"{ISSUER}/.well-known/openid-configuration",
                                )
                                endpoint = discovery.get("revocation_endpoint")
                                if not isinstance(endpoint, str):
                                    raise ValueError("Invalid endpoint")
                                parsed = urlsplit(endpoint)
                                if (
                                    parsed.scheme != "https"
                                    or parsed.netloc != "auth.openai.com"
                                    or parsed.query
                                    or parsed.fragment
                                    or not parsed.path.startswith("/")
                                ):
                                    raise ValueError("Invalid endpoint")
                                with client.stream(
                                    "POST",
                                    endpoint,
                                    data={
                                        "token": record.refresh_token,
                                        "token_type_hint": "refresh_token",
                                        "client_id": record.client_id,
                                    },
                                ) as response:
                                    confirmed = response.status_code == 200
                                    retry = response.status_code >= 500
                        except (httpx.HTTPError, ExchangeError):
                            retry = True
                        except ValueError:
                            break
                        if confirmed or not retry or attempt == 2:
                            break
                        time.sleep(0.2 * 2**attempt)
                delete_credentials(account.client_id)
                clear_active_account()
                self._session = None
                return confirmed
            finally:
                os.close(fd)


def get_valid_access_token(account_id: str) -> str:
    """Get a saved account's usable access token for backend requests only."""
    # ponytail: one lock serializes sign-ins and refreshes; split per account if needed.
    fd = _acquire_attempt_lock()
    try:
        account = get_account(account_id)
        record = load_credentials(account.client_id)
        if (
            record is None
            or record.subject != account.subject
            or record.access_token is None
            or not has_plan_permission(record.scope)
        ):
            raise AccountError("This account needs to sign in again.")
        if record.expires_at > time.time() + 60:
            return record.access_token
        if record.refresh_token is None:
            raise AccountError("This account needs to sign in again.")
        try:
            with _client() as client:
                response = _json_request(
                    client,
                    "POST",
                    TOKEN_URL,
                    refresh=True,
                    data={
                        "grant_type": "refresh_token",
                        "client_id": record.client_id,
                        "refresh_token": record.refresh_token,
                        "resource": RESOURCE,
                    },
                )
        except RefreshTokenInvalid:
            delete_credentials(record.client_id)
            raise AccountError("This account needs to sign in again.") from None
        try:
            expires_in = response["expires_in"]
            if (
                type(expires_in) is not int
                or not 0 < expires_in <= 31536000
                or not isinstance(response["token_type"], str)
                or response["token_type"].casefold() != "bearer"
            ):
                raise ValueError
            updated = type(record).model_validate(
                {
                    **record.model_dump(),
                    "access_token": response["access_token"],
                    "refresh_token": response["refresh_token"],
                    "expires_at": float(time.time() + expires_in),
                    "scope": response.get("scope", record.scope),
                }
            )
            if not updated.refresh_token:
                raise ValueError
        except (KeyError, ValueError, TypeError):
            raise ExchangeError("The OpenAI refresh response is invalid.") from None
        save_credentials(updated, VerifiedIdentity(record.subject, record.email))
        if not has_plan_permission(updated.scope):
            raise AccountError("This account needs to sign in again.")
        return updated.access_token
    finally:
        os.close(fd)
