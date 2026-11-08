"""Desktop-only server: serve the built UI and API on one loopback origin."""

import asyncio
import os
import socket
import sys
import threading
from pathlib import Path

import uvicorn
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from src.main import app


def desktop_app():
    # PyInstaller includes the production frontend beside this module.
    frontend = Path(__file__).parent / "web"
    if not frontend.is_dir():
        raise RuntimeError("Build the desktop frontend before starting Spoiless.")
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1"])
    app.mount("/", StaticFiles(directory=frontend, html=True), name="desktop")
    return app


class DesktopServer(uvicorn.Server):
    async def startup(self, sockets=None):
        await super().startup(sockets=sockets)
        if self.started:
            print(f"SPOILESS_READY {sockets[0].getsockname()[1]}", flush=True)


def main():
    # The parent holds the write end. EOF covers normal close and parent crashes.
    def parent_closed():
        os.read(sys.stdin.fileno(), 1)
        os._exit(0)

    threading.Thread(target=parent_closed, daemon=True).start()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        config = uvicorn.Config(
            desktop_app(), log_level="error", access_log=False, proxy_headers=False
        )
        asyncio.run(DesktopServer(config).serve(sockets=[listener]))


if __name__ == "__main__":
    main()
