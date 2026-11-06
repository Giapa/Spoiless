"""Shared local SQLite database and schema."""

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path


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
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS chatgpt_accounts (
                id TEXT PRIMARY KEY,
                client_id TEXT UNIQUE NOT NULL,
                subject TEXT NOT NULL,
                email TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
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
            CREATE TABLE IF NOT EXISTS reading_units (
                book_id TEXT NOT NULL,
                position INTEGER NOT NULL,
                kind TEXT NOT NULL CHECK (kind IN ('front_matter', 'chapter')),
                section_position INTEGER NOT NULL,
                character_offset INTEGER NOT NULL CHECK (character_offset >= 0),
                PRIMARY KEY (book_id, position),
                FOREIGN KEY (book_id, section_position)
                    REFERENCES sections(book_id, position) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS reading_progress (
                book_id TEXT PRIMARY KEY REFERENCES books(id) ON DELETE CASCADE,
                current_chapter INTEGER NOT NULL CHECK (current_chapter >= 2)
            );
            CREATE TABLE IF NOT EXISTS conversation_turns (
                id INTEGER PRIMARY KEY,
                book_id TEXT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                citations TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
            );
            CREATE TABLE IF NOT EXISTS passage_embeddings (
                book_id TEXT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
                section_position INTEGER NOT NULL,
                character_offset INTEGER NOT NULL,
                content_hash TEXT NOT NULL,
                model_revision TEXT NOT NULL,
                vector TEXT NOT NULL,
                PRIMARY KEY (book_id, section_position, character_offset),
                FOREIGN KEY (book_id, section_position)
                    REFERENCES sections(book_id, position) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS navigation_entries (
                book_id TEXT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
                position INTEGER NOT NULL,
                title TEXT NOT NULL,
                section_position INTEGER,
                character_offset INTEGER,
                CHECK ((section_position IS NULL AND character_offset IS NULL) OR
                       (section_position IS NOT NULL AND character_offset IS NOT NULL
                        AND character_offset >= 0)),
                FOREIGN KEY (book_id, section_position)
                    REFERENCES sections(book_id, position) ON DELETE CASCADE,
                PRIMARY KEY (book_id, position)
            );
        """)
        yield db
    finally:
        db.close()
