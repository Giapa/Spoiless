"""Retrieval over only the currently eligible book text."""

import math
import re
import sqlite3
from dataclasses import dataclass

from spoiless.library import eligible_text

# ponytail: rebuild the small eligible index per search; persist it once profiling
# shows this is too slow, while preserving filtering before any ranking.
PASSAGE_CHARS = 800


@dataclass(frozen=True)
class Passage:
    section_position: int
    character_offset: int
    text: str


def _passages(sections: list[tuple[int, str]]) -> list[Passage]:
    passages = []
    for position, text in sections:
        start = 0
        while start < len(text):
            end = min(start + PASSAGE_CHARS, len(text))
            if end < len(text) and not text[end].isspace():
                space = max(text.rfind(char, start + 1, end) for char in " \t\r\n")
                if space > start:
                    end = space
            passage = text[start:end]
            if passage.strip():
                passages.append(Passage(position, start, passage))
            start = end
    return passages


class ModelUnavailable(Exception):
    """The local embedding model could not be loaded or used."""


class ProgressChanged(Exception):
    """The eligible book text changed while searching."""


def _validate_query(query: str, limit: int) -> list[str]:
    words = re.findall(r"[^\W_]+", query, re.UNICODE)
    if not words or len(query) > 500 or not 1 <= limit <= 20:
        raise ValueError("Enter a search of 1–500 characters containing a word.")
    return words


def _keyword_ranking(passages: list[Passage], words: list[str]) -> list[int]:
    with sqlite3.connect(":memory:") as db:
        db.execute("CREATE VIRTUAL TABLE passages USING fts5(text)")
        db.executemany(
            "INSERT INTO passages(rowid, text) VALUES (?, ?)",
            ((i, passage.text) for i, passage in enumerate(passages, 1)),
        )
        expression = " OR ".join(f'"{word}"' for word in words)
        rows = db.execute(
            "SELECT rowid FROM passages WHERE passages MATCH ? ORDER BY rank, rowid",
            (expression,),
        ).fetchall()
    return [row[0] - 1 for row in rows]


def _check_snapshot(book_id: str, snapshot: list[tuple[int, str]]) -> None:
    try:
        current = eligible_text(book_id)
    except ValueError as exc:
        raise ProgressChanged("Reading progress changed; retry the search.") from exc
    if snapshot != current:
        raise ProgressChanged("Reading progress changed; retry the search.")


def keyword_search(book_id: str, query: str, limit: int = 5) -> list[Passage]:
    """Search an index built after slicing to reading progress."""
    words = _validate_query(query, limit)
    snapshot = eligible_text(book_id)
    passages = _passages(snapshot)
    ranking = _keyword_ranking(passages, words)
    _check_snapshot(book_id, snapshot)
    return [passages[i] for i in ranking[:limit]]


def hybrid_search(book_id: str, query: str, limit: int = 5) -> list[Passage]:
    """Combine keyword and semantic rankings for eligible passages."""
    from spoiless.embedding_model import load_model

    words = _validate_query(query, limit)
    snapshot = eligible_text(book_id)
    passages = _passages(snapshot)
    if not passages:
        return []
    try:
        vectors = list(load_model().embed([query, *(p.text for p in passages)]))
        if len(vectors) != len(passages) + 1:
            raise ValueError("Unexpected embedding count.")
        vectors = [[float(value) for value in vector] for vector in vectors]
        if not vectors[0] or any(
            len(vector) != len(vectors[0]) or not all(map(math.isfinite, vector))
            for vector in vectors
        ):
            raise ValueError("Invalid embedding vectors.")
        norms = [
            math.sqrt(sum(value * value for value in vector)) for vector in vectors
        ]
        if any(not math.isfinite(norm) or norm == 0 for norm in norms):
            raise ValueError("Invalid embedding vector magnitude.")
        similarities = [
            sum(a * b for a, b in zip(vectors[0], vector, strict=True))
            / (norms[0] * norms[index + 1])
            for index, vector in enumerate(vectors[1:])
        ]
        if not all(map(math.isfinite, similarities)):
            raise ValueError("Invalid embedding similarities.")
    except Exception as exc:
        raise ModelUnavailable(
            "Local model unavailable; check its setup and retry."
        ) from exc
    semantic = sorted(range(len(passages)), key=lambda i: (-similarities[i], i))
    keyword = _keyword_ranking(passages, words)
    scores = [0.0] * len(passages)
    for ranking in (semantic, keyword):
        for rank, index in enumerate(ranking, 1):
            scores[index] += 1 / (60 + rank)
    order = sorted(range(len(passages)), key=lambda i: (-scores[i], i))
    _check_snapshot(book_id, snapshot)
    return [passages[i] for i in order[:limit]]
