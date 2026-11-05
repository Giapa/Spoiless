"""Isolated browser-test server; replaces only OpenAI and OS keyring access."""

import json
import os
import threading
import time
from pathlib import Path

import httpx
import uvicorn
from fastapi.staticfiles import StaticFiles

from spoiless import chatgpt_accounts, chatgpt_credentials, library
from spoiless.chatgpt_auth import VerifiedIdentity
from spoiless.chatgpt_credentials import CredentialRecord
from spoiless.epub import Book, Section
from spoiless.main import app


class MemoryKeyring:
    def __init__(self):
        self.values = {}

    def get_password(self, service, key):
        return self.values.get((service, key))

    def set_password(self, service, key, value):
        self.values[(service, key)] = value

    def delete_password(self, service, key):
        del self.values[(service, key)]


backend = MemoryKeyring()
chatgpt_credentials._backend = lambda: backend
for suffix in ("a", "b", "c", "d"):
    identity = VerifiedIdentity(f"reader-{suffix}", f"{suffix}@example.test")
    client_id = f"oaiapp_{suffix}"
    account_id = chatgpt_accounts.remember_verified(client_id, identity)
    record = CredentialRecord(
        client_id=client_id,
        subject=identity.subject,
        email=identity.email,
        id_token="test-id",
        access_token=f"token-{suffix}",
        refresh_token=f"refresh-{suffix}",
        token_type="Bearer",
        expires_at=float(time.time() + 3600),
        scope="openid offline_access resource.invoke chatgpt.tokens.use.direct",
    )
    chatgpt_credentials.save_credentials(record, identity)
    if suffix == "a":
        chatgpt_accounts.activate_after_storage(account_id)


text = "Mira found the key. "
book_id = library.add_book(
    Book("The Sample Book", (Section(text + "UNREAD_SECRET ending."),))
)
library.confirm_reading_units(
    book_id,
    [
        library.ReadingUnitStart("chapter", 0, 0),
        library.ReadingUnitStart("chapter", 0, len(text)),
    ],
)
library.set_progress(book_id, 2)


started = threading.Event()


@app.get("/__test__/question_started")
def question_started():
    return {"started": started.is_set()}


def fake_openai(self, request):
    if request.url == "https://api.openai.com/v1/models":
        token = request.headers.get("authorization")
        if token == "Bearer token-a":
            values = [
                ("a1", "Model A1"),
                ("a2", "Model A2"),
                ("a3", "Slow model"),
                ("a4", "Invalid citation model"),
            ]
        elif token == "Bearer token-b":
            values = [("b1", "Model B1")]
        elif token == "Bearer token-c":
            values = []
        elif token == "Bearer token-d":
            return httpx.Response(503, text="secret-provider-details")
        else:
            return httpx.Response(401)
        return httpx.Response(
            200,
            json={
                "models": [
                    {"slug": slug, "display_name": name, "visibility": "list"}
                    for slug, name in values
                ]
            },
        )
    if (
        request.url == "https://api.openai.com/v1/responses"
        and request.method == "POST"
    ):
        body = json.loads(request.content)
        prompt = body["input"][0]["content"]
        if body["model"] != "a3" and (
            "UNREAD_SECRET" in prompt or "Mira found the key" not in prompt
        ):
            return httpx.Response(400)
        if body["model"] == "a4":
            answer = json.dumps(
                {
                    "answer": "UNREAD_SECRET",
                    "citations": [{"passage": 0, "quote": "UNREAD_SECRET"}],
                }
            )
            delta = json.dumps({"type": "response.output_text.delta", "delta": answer})
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text=(
                    f"data: {delta}\n\n"
                    'data: {"type":"response.completed","respon'
                    'se":{"status":"completed"}}\n\n'
                ),
            )
        if body["model"] == "a3":
            started.set()
            time.sleep(1.5)
            answer = json.dumps(
                {
                    "answer": "UNREAD_SECRET",
                    "citations": [{"passage": 0, "quote": "UNREAD_SECRET"}],
                }
            )
            delta = json.dumps({"type": "response.output_text.delta", "delta": answer})
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text=(
                    f"data: {delta}\n\n"
                    'data: {"type":"response.completed","respon'
                    'se":{"status":"completed"}}\n\n'
                ),
            )
        if body["model"] == "a2":
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text=(
                    'data: {"type":"response.failed","response"'
                    ':{"status":"failed","error":{"code":"subsc'
                    'ription_sharing_usage_limit_exceeded"}}}\n\n'
                ),
            )
        answer = json.dumps(
            {
                "answer": "Mira found the key.",
                "citations": [{"passage": 0, "quote": "found the key"}],
            }
        )
        delta = json.dumps({"type": "response.output_text.delta", "delta": answer})
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=(
                f"data: {delta}\n\n"
                'data: {"type":"response.completed","respon'
                'se":{"status":"completed"}}\n\n'
            ),
        )
    return httpx.Response(503)


httpx.HTTPTransport.handle_request = fake_openai
app.mount(
    "/", StaticFiles(directory=Path(__file__).resolve().parents[2] / "dist", html=True)
)
uvicorn.run(
    app,
    host="127.0.0.1",
    port=int(os.environ["SPOILESS_TEST_PORT"]),
    log_level="warning",
    access_log=False,
)
