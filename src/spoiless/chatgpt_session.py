"""Control one local sign-in attempt without exposing credentials to the UI.

The session is process-local and is not a persistent account manager. Do not
use it for inference, refresh, or multiple-worker deployments.
"""

import os
import stat
from dataclasses import dataclass
from threading import Lock, Thread
from typing import Literal

try:
    import fcntl
except ImportError:  # The rest of the app can still run on unverified platforms.
    fcntl = None

from spoiless.chatgpt_credentials import CredentialStoreError, check_credential_store
from spoiless.chatgpt_listener import LocalSignIn, Status
from spoiless.library import database_path


class SignInBusy(Exception):
    """A sign-in is already active or cannot be cancelled."""


class SignInStartError(Exception):
    """The listener or browser could not be started."""


@dataclass(frozen=True)
class SignInState:
    status: Status | Literal["idle"]
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
                return SignInState("idle")
            status = session.status
            if status == "connected":
                account = session.account
                if account is None:
                    return SignInState("failed")
                return SignInState(
                    "connected", account.identity.email, account.plan_usage_enabled
                )
            return SignInState(status)

    def start(self) -> None:
        with self._lock:
            if self._session is not None and self._session.status in {
                "pending",
                "processing",
                "connected",
            }:
                raise SignInBusy("A sign-in is already active.")
            # Hold the OS lock until the listener closes, including during exchange.
            fd = _acquire_attempt_lock()
            try:
                check_credential_store()
                session = LocalSignIn()
            except CredentialStoreError:
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
