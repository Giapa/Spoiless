"""Keyword retrieval over only the currently eligible book text."""

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


def keyword_search(book_id: str, query: str, limit: int = 5) -> list[Passage]:
    """Search an ephemeral index built *after* slicing to reading progress."""
    words = re.findall(r"[^\W_]+", query, re.UNICODE)
    if not words or len(query) > 500 or not 1 <= limit <= 20:
        raise ValueError("Enter a search of 1–500 characters containing a word.")
    passages = _passages(eligible_text(book_id))
    with sqlite3.connect(":memory:") as db:
        db.execute("CREATE VIRTUAL TABLE passages USING fts5(text)")
        db.executemany(
            "INSERT INTO passages(rowid, text) VALUES (?, ?)",
            ((i, passage.text) for i, passage in enumerate(passages, 1)),
        )
        # Quote terms instead of accepting FTS query syntax from readers.
        expression = " OR ".join(f'"{word}"' for word in words)
        rows = db.execute(
            "SELECT rowid FROM passages WHERE passages MATCH ? "
            "ORDER BY rank, rowid LIMIT ?",
            (expression, limit),
        ).fetchall()
    return [passages[row[0] - 1] for row in rows]
