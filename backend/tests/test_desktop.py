"""Check production UI routing and the desktop process lifetime contract."""

import queue
import subprocess
import sys
import threading

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src import desktop


def test_desktop_serves_ui_api_and_rejects_foreign_hosts(tmp_path, monkeypatch):
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<title>Spoiless</title>")
    monkeypatch.setattr(desktop, "__file__", str(tmp_path / "desktop.py"))
    monkeypatch.setattr(desktop, "app", FastAPI(routes=list(desktop.app.routes)))
    app = desktop.desktop_app()
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.get("/").text == "<title>Spoiless</title>"
        assert client.get("/api/health").json() == {"status": "ok"}
        assert client.get("/", headers={"host": "evil.example"}).status_code == 400
        assert (
            client.get("/api/health", headers={"host": "evil.example"}).status_code
            == 400
        )
        assert client.get("/api/missing").status_code == 404


def test_parent_pipe_eof_stops_backend_without_orphan(tmp_path):
    # Supply a built UI without modifying the checkout.
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("Spoiless")
    script = (
        "import sys; from src import desktop; "
        "desktop.__file__ = sys.argv[1]; desktop.main()"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(tmp_path / "desktop.py")],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        ready = queue.Queue()
        threading.Thread(
            target=lambda: ready.put(process.stdout.readline()), daemon=True
        ).start()
        assert ready.get(timeout=15).startswith(b"SPOILESS_READY ")
        process.stdin.close()
        assert process.wait(timeout=10) == 0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
