"""Local storage for imported books and their unconfirmed sections."""

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from spoiless.epub import Book


def database_path() -> Path:
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    return data_home / "spoiless" / "library.sqlite3"


@contextmanager
def connect():
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    db = sqlite3.connect(path)
    try:
        db.execute("PRAGMA foreign_keys = ON")
        db.executescript("""
            CREATE TABLE IF NOT EXISTS books (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS sections (
                book_id TEXT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
                position INTEGER NOT NULL,
                text TEXT NOT NULL,
                PRIMARY KEY (book_id, position)
            );
        """)
        yield db
    finally:
        db.close()


def add_book(book: Book) -> str:
    book_id = str(uuid4())
    with connect() as db, db:
        db.execute("INSERT INTO books (id, title) VALUES (?, ?)", (book_id, book.title))
        db.executemany(
            "INSERT INTO sections (book_id, position, text) VALUES (?, ?, ?)",
            (
                (book_id, position, section.text)
                for position, section in enumerate(book.sections)
            ),
        )
    return book_id


def list_books() -> list[tuple[str, str, int]]:
    with connect() as db:
        return db.execute("""
            SELECT books.id, books.title, COUNT(sections.position)
            FROM books JOIN sections ON books.id = sections.book_id
            GROUP BY books.id ORDER BY books.created_at DESC, books.rowid DESC
        """).fetchall()


def delete_book(book_id: str) -> bool:
    with connect() as db, db:
        return db.execute("DELETE FROM books WHERE id = ?", (book_id,)).rowcount == 1
