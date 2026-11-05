"""Short-lived loopback listener for a local ChatGPT sign-in attempt.

No web route or UI uses this yet. The caller must keep the session in the backend
and must not expose its authorization URL, verifier, callback, or tokens in logs.
"""

import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Literal
from urllib.parse import parse_qs, urlsplit

from spoiless.chatgpt.auth import (
    ATTEMPT_SECONDS,
    AuthorizationAttempt,
    AuthorizationDenied,
    host_id,
)
from spoiless.chatgpt.exchange import ConnectedAccount, exchange_and_store

Status = Literal[
    "pending", "processing", "connected", "denied", "failed", "expired", "cancelled"
]


class _LoopbackServer(HTTPServer):
    # Slow local connections must not hold the listener indefinitely.
    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(2.0)
        return connection, address

    def handle_error(self, request, client_address):
        # Never print the request path: it may contain a one-use code.
        pass


class LocalSignIn:
    """Own one loopback callback listener and one server-side authorization attempt."""

    def __init__(
        self,
        *,
        returning_client_id: str | None = None,
        expected_subject: str | None = None,
        id_token_hint: str | None = None,
    ) -> None:
        if (returning_client_id is None) != (expected_subject is None) or (
            id_token_hint is not None and returning_client_id is None
        ):
            raise ValueError("Invalid returning account.")
        if expected_subject is not None and (
            not isinstance(expected_subject, str) or not expected_subject.strip()
        ):
            raise ValueError("Invalid returning account.")
        self._expected_subject = expected_subject
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._closed = threading.Event()
        self._status: Status = "pending"
        self._account: ConnectedAccount | None = None
        self._opened = False
        owner = self

        class CallbackHandler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                # BaseHTTPRequestHandler normally logs the complete callback URL.
                pass

            def do_GET(self):
                owner._callback(self)

        self._server = _LoopbackServer(("127.0.0.1", 0), CallbackHandler)
        self._server.timeout = 0.25
        self._port = self._server.server_address[1]
        try:
            self._attempt = AuthorizationAttempt(
                f"http://127.0.0.1:{self._port}/auth/callback",
                returning_client_id=returning_client_id,
            )
            self._url = self._attempt.authorization_url(
                host_id(), id_token_hint=id_token_hint
            )
            self._deadline = self._attempt.created + ATTEMPT_SECONDS
            self._thread = threading.Thread(target=self._serve, daemon=True)
            self._thread.start()
        except BaseException:
            self._server.server_close()
            raise

    def open_browser(self) -> None:
        """Open OpenAI only after the listener is running; never log the URL."""
        with self._lock:
            if (
                self._status != "pending"
                or self._opened
                or time.monotonic() >= self._deadline
            ):
                raise RuntimeError("This sign-in attempt is no longer available.")
            self._opened = True
        try:
            opened = webbrowser.open(self._url)
        except Exception:
            opened = False
        if not opened:
            with self._lock:
                if self._status == "pending":
                    self._opened = False
            raise RuntimeError("Could not open your browser.")

    @property
    def status(self) -> Status:
        with self._lock:
            return self._status

    @property
    def account(self) -> ConnectedAccount | None:
        """Backend-only result. Never send credentials to a browser."""
        with self._lock:
            return self._account

    def close(self) -> None:
        """Cancel a pending listener; an exchange already in progress may finish."""
        with self._lock:
            if self._status == "pending":
                self._status = "cancelled"
                self._stop.set()

    def wait(self, timeout: float | None = None) -> bool:
        """Wait until the server socket has closed."""
        return self._closed.wait(timeout)

    def _serve(self) -> None:
        try:
            while not self._stop.is_set():
                if time.monotonic() >= self._deadline:
                    with self._lock:
                        if self._status == "pending":
                            self._status = "expired"
                    break
                self._server.handle_request()
        finally:
            self._server.server_close()
            self._closed.set()

    def _callback(self, request: BaseHTTPRequestHandler) -> None:
        def reply(status: int, message: str) -> None:
            body = message.encode("utf-8")
            request.send_response(status)
            request.send_header("Content-Type", "text/plain; charset=utf-8")
            request.send_header("Content-Length", str(len(body)))
            request.send_header("Cache-Control", "no-store")
            request.send_header("Referrer-Policy", "no-referrer")
            request.send_header("X-Content-Type-Options", "nosniff")
            request.send_header(
                "Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"
            )
            request.send_header("Connection", "close")
            request.end_headers()
            request.wfile.write(body)

        try:
            parts = urlsplit(request.path)
            if (
                parts.scheme
                or parts.netloc
                or parts.path != "/auth/callback"
                or request.headers.get_all("Host", []) != [f"127.0.0.1:{self._port}"]
                or len(parts.query) > 8192
            ):
                reply(400, "Invalid sign-in callback.")
                return
            params = parse_qs(parts.query, keep_blank_values=True, max_num_fields=30)
            states = params.get("state", [])
            if len(states) != 1 or not secrets.compare_digest(
                states[0].encode(), self._attempt.state.encode()
            ):
                reply(400, "Invalid sign-in callback.")
                return
        except (ValueError, UnicodeError):
            reply(400, "Invalid sign-in callback.")
            return
        with self._lock:
            if self._status != "pending":
                reply(400, "Sign-in attempt is no longer available.")
                return
            self._status = "processing"
        try:
            if self._expected_subject is None:
                account = exchange_and_store(self._attempt, parts.query)
            else:
                account = exchange_and_store(
                    self._attempt, parts.query, expected_subject=self._expected_subject
                )
        except AuthorizationDenied:
            with self._lock:
                self._status = "denied"
            reply(200, "Sign-in was declined. You can return to Spoiless.")
        except Exception:
            with self._lock:
                self._status = "failed"
            reply(400, "Sign-in could not be completed. You can return to Spoiless.")
        else:
            with self._lock:
                self._account = account
                self._status = "connected"
            reply(200, "Sign-in complete. You can return to Spoiless.")
        finally:
            self._stop.set()
