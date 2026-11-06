"""Discover the models available to a saved ChatGPT account."""

from src.chatgpt.auth import RESOURCE
from src.chatgpt.exchange import ExchangeError, _client, _json_request
from src.chatgpt.session import get_valid_access_token


class ModelCatalogError(Exception):
    """The model catalog could not be retrieved or was invalid."""


def list_available_models(account_id: str) -> list[dict[str, str]]:
    """Return displayable models in OpenAI's order, without exposing credentials."""
    token = get_valid_access_token(account_id)
    try:
        with _client() as client:
            client.headers["Authorization"] = f"Bearer {token}"
            result = _json_request(
                client, "GET", f"{RESOURCE}/models", max_response_bytes=2 * 1024 * 1024
            )
        models = result["models"]
        if not isinstance(models, list):
            raise ValueError
        visible = []
        for model in models:
            if not isinstance(model, dict) or not isinstance(
                model.get("visibility"), str
            ):
                raise ValueError
            if model["visibility"] != "list":
                continue
            slug, name = model["slug"], model["display_name"]
            if (
                not isinstance(slug, str)
                or not slug.strip()
                or not isinstance(name, str)
                or not name.strip()
            ):
                raise ValueError
            visible.append({"slug": slug, "display_name": name})
        return visible
    except ExchangeError as exc:
        messages = {
            401: "ChatGPT did not accept this connection. "
            "Check the selected account and sign in again if needed.",
            403: "ChatGPT denied access to models for this account. "
            "Check account eligibility and permissions.",
            429: "ChatGPT is rate limiting model requests. Please retry later.",
        }
        raise ModelCatalogError(
            messages.get(
                exc.status_code, "Could not load ChatGPT models. Please retry."
            )
        ) from None
    except (KeyError, ValueError, TypeError):
        raise ModelCatalogError("Could not load the ChatGPT model catalog.") from None
