"""Explicit setup of the local semantic-search model."""

from pathlib import Path
from threading import Lock

from spoiless.library import database_path

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
_lock = Lock()


def model_dir() -> Path:
    return database_path().parent / "models"


def model_ready() -> bool:
    """A marker records a completed setup; loading still checks cached files."""
    return (model_dir() / "minilm-ready").is_file()


def setup_model() -> None:
    """Download only on explicit request; mark ready after a successful load."""
    from fastembed import TextEmbedding

    with _lock:
        directory = model_dir()
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        marker = directory / "minilm-ready"
        marker.unlink(missing_ok=True)
        TextEmbedding(MODEL_NAME, cache_dir=str(directory), threads=2)
        marker.touch(mode=0o600)


def load_model():
    """Never initiate a download from a search or status request."""
    if not model_ready():
        raise ValueError("Download the semantic search model first.")
    from fastembed import TextEmbedding

    return TextEmbedding(
        MODEL_NAME, cache_dir=str(model_dir()), threads=2, local_files_only=True
    )
