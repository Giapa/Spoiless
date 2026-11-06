"""Isolated browser-test server; replaces only OpenAI and OS keyring access."""

import os
import time
from pathlib import Path

import httpx
import uvicorn
from fastapi.staticfiles import StaticFiles

from src.chatgpt import accounts as chatgpt_accounts
from src.chatgpt import credentials as chatgpt_credentials
from src.chatgpt.auth import VerifiedIdentity
from src.chatgpt.credentials import CredentialRecord
from src.main import app


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


def fake_openai(self, request):
    if request.url == "https://api.openai.com/v1/models":
        token = request.headers.get("authorization")
        if token == "Bearer token-a":
            values = [("a1", "Model A1"), ("a2", "Model A2")]
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
