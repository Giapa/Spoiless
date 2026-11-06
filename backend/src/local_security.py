"""Security checks for sensitive local API requests."""

from urllib.parse import urlsplit

from fastapi import HTTPException, Request


def _local_request(request: Request, *, mutation: bool = False) -> None:
    """Limit sensitive local controls to loopback, same-origin browser requests."""
    host = request.headers.get("host", "")
    try:
        parsed = urlsplit(f"http://{host}")
        valid = (
            request.client is not None
            and request.client.host == "127.0.0.1"
            and request.headers.getlist("host") == [host]
            and parsed.hostname in {"127.0.0.1", "localhost"}
            and parsed.username is None
            and parsed.password is None
            and parsed.path == ""
            and parsed.query == ""
            and parsed.fragment == ""
            and (parsed.port is None or 1 <= parsed.port <= 65535)
            and parsed.netloc == host
        )
    except ValueError:
        valid = False
    if not valid:
        raise HTTPException(403, "Local access only.")
    if mutation and (
        request.headers.getlist("origin") != [f"http://{host}"]
        or request.headers.get("x-spoiless-action") != "1"
        or request.headers.get("content-type", "").split(";")[0].strip().lower()
        != "application/json"
    ):
        raise HTTPException(403, "A same-origin app action is required.")
