"""Backend-only ChatGPT Responses API adapter, not a book-answer workflow."""

from collections.abc import Callable

import httpx
from openai import APIError, OpenAI

from src.chatgpt.auth import RESOURCE
from src.chatgpt.exchange import _client
from src.chatgpt.models import list_available_models
from src.chatgpt.session import get_valid_access_token


class InferenceError(Exception):
    """The inference request did not complete safely."""

    def __init__(self, message: str, *, code: str | None = None):
        super().__init__(message)
        self.code = code


def _known_code(code: object) -> str | None:
    if code in (
        "subscription_sharing_usage_limit_exceeded",
        "subscription_sharing_usage_unavailable",
    ):
        return code
    return None


def generate_response(
    account_id: str,
    model: str,
    prompt: str,
    *,
    before_send: Callable[[], None] | None = None,
) -> str:
    """Return text only after OpenAI confirms the streamed response completed."""
    if model not in {item["slug"] for item in list_available_models(account_id)}:
        raise InferenceError("This model is not available to the selected account.")
    token = get_valid_access_token(account_id)
    output = []
    output_size = 0
    completed = False
    guard_error: Exception | None = None
    try:

        def use_account_headers(request: httpx.Request) -> None:
            nonlocal guard_error
            if before_send is not None:
                try:
                    before_send()
                except Exception as exc:
                    guard_error = exc
                    raise
            allowed = {
                "host",
                "content-length",
                "content-type",
                "accept",
                "accept-encoding",
                "connection",
                "user-agent",
                "authorization",
            }
            for header in list(request.headers):
                if header.lower() not in allowed:
                    del request.headers[header]
            request.headers["Authorization"] = f"Bearer {token}"
            request.headers["Host"] = "api.openai.com"
            request.headers["Content-Type"] = "application/json"
            request.headers["Content-Length"] = str(len(request.content))

        with _client() as http_client:
            http_client.timeout = httpx.Timeout(120.0, connect=10.0)
            http_client.event_hooks["request"].append(use_account_headers)
            with OpenAI(
                api_key=token, base_url=RESOURCE, http_client=http_client, max_retries=0
            ) as client:
                with client.responses.create(
                    model=model,
                    input=[{"role": "user", "content": prompt}],
                    stream=True,
                    store=False,
                ) as stream:
                    for event in stream:
                        if event.type == "response.output_text.delta":
                            delta = getattr(event, "delta", None)
                            if not isinstance(delta, str):
                                raise InferenceError(
                                    "The ChatGPT response was invalid."
                                )
                            output_size += len(delta)
                            if output_size > 1_000_000:
                                raise InferenceError(
                                    "The ChatGPT response was too large."
                                )
                            output.append(delta)
                        elif event.type in {
                            "response.failed",
                            "response.incomplete",
                            "error",
                        }:
                            response = getattr(event, "response", None)
                            details = getattr(response, "error", None)
                            code = _known_code(getattr(details, "code", None))
                            raise InferenceError(
                                "The ChatGPT response failed or was incomplete.",
                                code=code,
                            )
                        elif event.type == "response.completed":
                            if (
                                getattr(
                                    getattr(event, "response", None), "status", None
                                )
                                != "completed"
                            ):
                                raise InferenceError(
                                    "The ChatGPT response was invalid."
                                )
                            completed = True
    except APIError as exc:
        if guard_error is not None:
            raise guard_error from None
        raise InferenceError(
            "The ChatGPT request could not be completed.", code=_known_code(exc.code)
        ) from None
    except (ValueError, TypeError, AttributeError):
        raise InferenceError("The ChatGPT response was invalid.") from None
    if not completed:
        raise InferenceError("The ChatGPT response did not complete.")
    return "".join(output)
