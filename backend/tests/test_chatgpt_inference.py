import time

import httpx
import pytest

from src.chatgpt import accounts as chatgpt_accounts
from src.chatgpt import credentials as chatgpt_credentials
from src.chatgpt.auth import VerifiedIdentity
from src.chatgpt.credentials import CredentialRecord
from src.chatgpt.inference import generate_response


class MemoryKeyring:
    def __init__(self):
        self.values = {}

    def get_password(self, service, username):
        return self.values.get((service, username))

    def set_password(self, service, username, value):
        self.values[(service, username)] = value


@pytest.fixture
def saved_account(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    backend = MemoryKeyring()
    monkeypatch.setattr(chatgpt_credentials, "_backend", lambda: backend)
    identity = VerifiedIdentity("reader", "reader@example.test")
    account = chatgpt_accounts.remember_verified("oaiapp_reader", identity)
    record = CredentialRecord(
        client_id="oaiapp_reader",
        subject=identity.subject,
        email=identity.email,
        id_token="id-token",
        access_token="secret-access",
        refresh_token="secret-refresh",
        token_type="Bearer",
        expires_at=float(time.time() + 3600),
        scope="openid offline_access resource.invoke chatgpt.tokens.use.direct",
    )
    chatgpt_credentials.save_credentials(record, identity)
    return account


def test_completed_response_returns_text_and_uses_account_plan(
    saved_account, monkeypatch
):
    import json

    requests = []

    def handle(request):
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "slug": "allowed-model",
                            "display_name": "Allowed",
                            "visibility": "list",
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=(
                'event: response.output_text.delta\ndata: {"typ'
                'e":"response.output_text.delta","delta":"Hell'
                'o"}\n\n'
                'event: response.output_text.delta\ndata: {"typ'
                'e":"response.output_text.delta","delta":" wor'
                'ld"}\n\n'
                'event: response.completed\ndata: {"type":"resp'
                'onse.completed","response":{"status":"complet'
                'ed"}}\n\n'
                "data: [DONE]\n\n"
            ),
        )

    monkeypatch.setattr(
        httpx.HTTPTransport, "handle_request", lambda self, request: handle(request)
    )
    assert (
        generate_response(saved_account, "allowed-model", "Say hello") == "Hello world"
    )
    response_request = requests[-1]
    assert str(response_request.url) == "https://api.openai.com/v1/responses"
    assert response_request.headers["authorization"] == "Bearer secret-access"
    body = json.loads(response_request.content)
    assert body["model"] == "allowed-model"
    assert body["stream"] is True and body["store"] is False
    assert body["input"] == [{"role": "user", "content": "Say hello"}]


def test_failed_stream_never_returns_partial_text(saved_account, monkeypatch):
    from src.chatgpt.inference import InferenceError

    def handle(request):
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "slug": "allowed-model",
                            "display_name": "Allowed",
                            "visibility": "list",
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=(
                'event: response.output_text.delta\ndata: {"typ'
                'e":"response.output_text.delta","delta":"part'
                'ial private text"}\n\n'
                'event: response.failed\ndata: {"type":"respons'
                'e.failed","response":{"status":"failed","erro'
                'r":{"code":"subscription_sharing_usage_limit_'
                'exceeded"}}}\n\n'
                'event: response.completed\ndata: {"type":"resp'
                'onse.completed","response":{"status":"complet'
                'ed"}}\n\n'
            ),
        )

    monkeypatch.setattr(
        httpx.HTTPTransport, "handle_request", lambda self, request: handle(request)
    )
    with pytest.raises(InferenceError) as error:
        generate_response(saved_account, "allowed-model", "private prompt")
    assert "partial private text" not in str(error.value)
    assert "private prompt" not in str(error.value)


def test_http_errors_do_not_expose_prompts_or_tokens(saved_account, monkeypatch):
    from src.chatgpt.inference import InferenceError

    def handle(request):
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "slug": "allowed-model",
                            "display_name": "Allowed",
                            "visibility": "list",
                        }
                    ]
                },
            )
        return httpx.Response(
            503, json={"error": {"message": "private prompt and secret-access"}}
        )

    monkeypatch.setattr(
        httpx.HTTPTransport, "handle_request", lambda self, request: handle(request)
    )
    with pytest.raises(InferenceError) as error:
        generate_response(saved_account, "allowed-model", "private prompt")
    assert "secret-access" not in str(error.value)
    assert "private prompt" not in str(error.value)
    assert error.value.__cause__ is None


def test_environment_cannot_redirect_access_token(saved_account, monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://attacker.example/v1")
    requests = []

    def handle(request):
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "slug": "allowed-model",
                            "display_name": "Allowed",
                            "visibility": "list",
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=(
                'event: response.completed\ndata: {"type":"resp'
                'onse.completed","response":{"status":"complet'
                'ed"}}\n\n'
            ),
        )

    monkeypatch.setattr(
        httpx.HTTPTransport, "handle_request", lambda self, request: handle(request)
    )
    generate_response(saved_account, "allowed-model", "hello")
    assert all(request.url.host == "api.openai.com" for request in requests)


def test_interrupted_stream_does_not_return_partial_output(saved_account, monkeypatch):
    from src.chatgpt.inference import InferenceError

    def handle(request):
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "slug": "allowed-model",
                            "display_name": "Allowed",
                            "visibility": "list",
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=(
                'event: response.output_text.delta\ndata: {"typ'
                'e":"response.output_text.delta","delta":"part'
                'ial"}\n\n'
            ),
        )

    monkeypatch.setattr(
        httpx.HTTPTransport, "handle_request", lambda self, request: handle(request)
    )
    with pytest.raises(InferenceError):
        generate_response(saved_account, "allowed-model", "hello")


def test_unavailable_model_never_sends_prompt(saved_account, monkeypatch):
    from src.chatgpt.inference import InferenceError

    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "models": [
                    {
                        "slug": "allowed-model",
                        "display_name": "Allowed",
                        "visibility": "list",
                    }
                ]
            },
        )

    monkeypatch.setattr(
        httpx.HTTPTransport, "handle_request", lambda self, request: handle(request)
    )
    with pytest.raises(InferenceError):
        generate_response(saved_account, "not-allowed", "private prompt")
    assert all(request.method == "GET" for request in requests)


def test_malformed_stream_is_reported_as_a_safe_failure(saved_account, monkeypatch):
    from src.chatgpt.inference import InferenceError

    def handle(request):
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "slug": "allowed-model",
                            "display_name": "Allowed",
                            "visibility": "list",
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=(
                'event: response.output_text.delta\ndata: {"typ'
                'e":"response.output_text.delta","delta":{"pri'
                'vate":"secret"}}\n\n'
                'event: response.completed\ndata: {"type":"resp'
                'onse.completed","response":{"status":"complet'
                'ed"}}\n\n'
            ),
        )

    monkeypatch.setattr(
        httpx.HTTPTransport, "handle_request", lambda self, request: handle(request)
    )
    with pytest.raises(InferenceError) as error:
        generate_response(saved_account, "allowed-model", "private prompt")
    assert "secret" not in str(error.value)


def test_plan_limit_error_is_available_for_recovery(saved_account, monkeypatch):
    from src.chatgpt.inference import InferenceError

    def handle(request):
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "slug": "allowed-model",
                            "display_name": "Allowed",
                            "visibility": "list",
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=(
                'event: response.failed\ndata: {"type":"respons'
                'e.failed","response":{"status":"failed","erro'
                'r":{"code":"subscription_sharing_usage_limit_'
                'exceeded"}}}\n\n'
            ),
        )

    monkeypatch.setattr(
        httpx.HTTPTransport, "handle_request", lambda self, request: handle(request)
    )
    with pytest.raises(InferenceError) as error:
        generate_response(saved_account, "allowed-model", "hello")
    assert error.value.code == "subscription_sharing_usage_limit_exceeded"


def test_invalid_event_json_does_not_leak_private_text(saved_account, monkeypatch):
    from src.chatgpt.inference import InferenceError

    def handle(request):
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "slug": "allowed-model",
                            "display_name": "Allowed",
                            "visibility": "list",
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text="event: response.output_text.delta\ndata: private-secret\n\n",
        )

    monkeypatch.setattr(
        httpx.HTTPTransport, "handle_request", lambda self, request: handle(request)
    )
    with pytest.raises(InferenceError) as error:
        generate_response(saved_account, "allowed-model", "private prompt")
    assert "private-secret" not in str(error.value)


def test_environment_cannot_override_account_token_or_inject_headers(
    saved_account, monkeypatch
):
    monkeypatch.setenv(
        "OPENAI_CUSTOM_HEADERS",
        "Authorization: Bearer other-token\nX-Custom: p"
        "rivate\nHost: other.example\nContent-Type: text"
        "/plain",
    )
    monkeypatch.setenv("OPENAI_ORG_ID", "unrelated-organization")
    monkeypatch.setenv("OPENAI_PROJECT_ID", "unrelated-project")
    requests = []

    def handle(request):
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "slug": "allowed-model",
                            "display_name": "Allowed",
                            "visibility": "list",
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=(
                'event: response.completed\ndata: {"type":"resp'
                'onse.completed","response":{"status":"complet'
                'ed"}}\n\n'
            ),
        )

    monkeypatch.setattr(
        httpx.HTTPTransport, "handle_request", lambda self, request: handle(request)
    )
    generate_response(saved_account, "allowed-model", "hello")
    sent = requests[-1]
    assert sent.headers["authorization"] == "Bearer secret-access"
    assert sent.headers["host"] == "api.openai.com"
    assert sent.headers["content-type"] == "application/json"
    assert "x-custom" not in sent.headers
    assert "openai-organization" not in sent.headers
    assert "openai-project" not in sent.headers


def test_completed_event_must_contain_a_completed_response(saved_account, monkeypatch):
    from src.chatgpt.inference import InferenceError

    def handle(request):
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "slug": "allowed-model",
                            "display_name": "Allowed",
                            "visibility": "list",
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=(
                'event: response.completed\ndata: {"type":"resp'
                'onse.completed","response":{"status":"incompl'
                'ete"}}\n\n'
            ),
        )

    monkeypatch.setattr(
        httpx.HTTPTransport, "handle_request", lambda self, request: handle(request)
    )
    with pytest.raises(InferenceError):
        generate_response(saved_account, "allowed-model", "hello")
