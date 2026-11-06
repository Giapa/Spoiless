"""Local storage for imported books and their unconfirmed sections."""

import sqlite3
from dataclasses import dataclass
from typing import Literal
from uuid import uuid4

from src.database import connect
from src.library.epub import Book, NavigationEntry


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
        db.executemany(
            """INSERT INTO navigation_entries
               (book_id, position, title, section_position, character_offset)
               VALUES (?, ?, ?, ?, ?)""",
            (
                (
                    book_id,
                    index,
                    entry.title,
                    entry.section_position,
                    entry.character_offset,
                )
                for index, entry in enumerate(book.navigation)
            ),
        )
    return book_id


def list_books() -> list[tuple[str, str, int, bool]]:
    with connect() as db:
        rows = db.execute("""
            SELECT books.id, books.title, COUNT(sections.position),
                   EXISTS(SELECT 1 FROM reading_units WHERE book_id = books.id)
            FROM books JOIN sections ON books.id = sections.book_id
            GROUP BY books.id ORDER BY books.created_at DESC, books.rowid DESC
        """).fetchall()
    return [
        (book_id, title, count, bool(confirmed))
        for book_id, title, count, confirmed in rows
    ]


def delete_book(book_id: str) -> bool:
    with connect() as db, db:
        return db.execute("DELETE FROM books WHERE id = ?", (book_id,)).rowcount == 1


@dataclass(frozen=True)
class ReadingUnitStart:
    kind: Literal["front_matter", "chapter"]
    section_position: int
    character_offset: int


class BookNotFound(ValueError):
    """The requested book is not in the local library."""


def get_navigation(book_id: str) -> list[NavigationEntry]:
    """Return ordered, unconfirmed navigation links, including unresolved links."""
    with connect() as db:
        if (
            db.execute("SELECT 1 FROM books WHERE id = ?", (book_id,)).fetchone()
            is None
        ):
            raise BookNotFound("Book not found.")
        rows = db.execute(
            """SELECT title, section_position, character_offset FROM navigation_entries
               WHERE book_id = ? ORDER BY position""",
            (book_id,),
        ).fetchall()
    return [NavigationEntry(*row) for row in rows]


def get_sections(book_id: str) -> list[tuple[int, str]]:
    """Return full section text only for an explicitly requested book."""
    with connect() as db:
        if (
            db.execute("SELECT 1 FROM books WHERE id = ?", (book_id,)).fetchone()
            is None
        ):
            raise BookNotFound("Book not found.")
        return db.execute(
            "SELECT position, text FROM sections WHERE book_id = ? ORDER BY position",
            (book_id,),
        ).fetchall()


def confirm_reading_units(book_id: str, units: list[ReadingUnitStart]) -> None:
    """Replace confirmed starts; offsets count Unicode code points in section text."""
    with connect() as db, db:
        db.execute("BEGIN IMMEDIATE")
        rows = db.execute(
            "SELECT position, text FROM sections WHERE book_id = ? ORDER BY position",
            (book_id,),
        ).fetchall()
        if not rows:
            raise BookNotFound("Book not found.")
        lengths = {position: len(text) for position, text in rows}
        if not units or (units[0].section_position, units[0].character_offset) != (
            0,
            0,
        ):
            raise ValueError("Reading units must begin at the start of the book.")
        if not any(unit.kind == "chapter" for unit in units):
            raise ValueError("At least one chapter is required.")
        previous = (-1, -1)
        for index, unit in enumerate(units):
            point = (unit.section_position, unit.character_offset)
            if unit.kind not in ("front_matter", "chapter"):
                raise ValueError("Unknown reading unit kind.")
            if unit.kind == "front_matter" and index != 0:
                raise ValueError("Front matter must be the first reading unit.")
            length = lengths.get(unit.section_position)
            if (
                length is None
                or not 0 <= unit.character_offset < length
                or point <= previous
            ):
                raise ValueError(
                    "Reading unit starts must be valid and strictly ordered."
                )
            previous = point
        # Changing the chapter map invalidates the old progress boundary.
        db.execute(
            "UPDATE conversation_turns SET active = 0 WHERE book_id = ? AND active = 1",
            (book_id,),
        )
        db.execute("DELETE FROM reading_progress WHERE book_id = ?", (book_id,))
        db.execute("DELETE FROM reading_units WHERE book_id = ?", (book_id,))
        db.executemany(
            """INSERT INTO reading_units
               (book_id, position, kind, section_position, character_offset)
               VALUES (?, ?, ?, ?, ?)""",
            (
                (
                    book_id,
                    position,
                    unit.kind,
                    unit.section_position,
                    unit.character_offset,
                )
                for position, unit in enumerate(units)
            ),
        )


def get_reading_units(book_id: str) -> list[ReadingUnitStart]:
    with connect() as db:
        if (
            db.execute("SELECT 1 FROM books WHERE id = ?", (book_id,)).fetchone()
            is None
        ):
            raise BookNotFound("Book not found.")
        rows = db.execute(
            """SELECT kind, section_position, character_offset FROM reading_units
               WHERE book_id = ? ORDER BY position""",
            (book_id,),
        ).fetchall()
    return [ReadingUnitStart(*row) for row in rows]


@dataclass(frozen=True)
class ReadingProgress:
    chapter_count: int
    current_chapter: int | None


def _progress(db: sqlite3.Connection, book_id: str) -> ReadingProgress:
    row = db.execute(
        """SELECT (SELECT COUNT(*) FROM reading_units
                   WHERE book_id = books.id AND kind = 'chapter'),
                  (SELECT current_chapter FROM reading_progress
                   WHERE book_id = books.id)
           FROM books WHERE id = ?""",
        (book_id,),
    ).fetchone()
    if row is None:
        raise BookNotFound("Book not found.")
    return ReadingProgress(*row)


def get_progress(book_id: str) -> ReadingProgress:
    with connect() as db:
        return _progress(db, book_id)


def set_progress(book_id: str, current_chapter: int) -> ReadingProgress:
    with connect() as db, db:
        db.execute("BEGIN IMMEDIATE")
        progress = _progress(db, book_id)
        if (
            type(current_chapter) is not int
            or not 2 <= current_chapter <= progress.chapter_count + 1
        ):
            raise ValueError("Confirm chapters and choose a valid current chapter.")
        if (
            progress.current_chapter is not None
            and current_chapter < progress.current_chapter
        ):
            db.execute(
                "UPDATE conversation_turns SET active = 0 "
                "WHERE book_id = ? AND active = 1",
                (book_id,),
            )
        db.execute(
            """INSERT INTO reading_progress (book_id, current_chapter) VALUES (?, ?)
               ON CONFLICT(book_id) DO UPDATE
               SET current_chapter = excluded.current_chapter""",
            (book_id, current_chapter),
        )
        return ReadingProgress(progress.chapter_count, current_chapter)


def eligible_text(book_id: str) -> list[tuple[int, str]]:
    """Only confirmed text before the current chapter; finished includes all text.

    Must be used before retrieval or model context is assembled. Reads the boundary
    and text in one transaction so a chapter-map update cannot mix revisions.
    """
    with connect() as db:
        db.execute("BEGIN")
        progress = _progress(db, book_id)
        if (
            progress.current_chapter is None
            or not 2 <= progress.current_chapter <= progress.chapter_count + 1
        ):
            raise ValueError("Confirm chapters and select reading progress first.")
        boundary = db.execute(
            """SELECT section_position, character_offset FROM reading_units
               WHERE book_id = ? AND kind = 'chapter'
               ORDER BY position LIMIT 1 OFFSET ?""",
            (book_id, progress.current_chapter - 1),
        ).fetchone()
        if boundary is None:
            return db.execute(
                "SELECT position, text FROM sections "
                "WHERE book_id = ? ORDER BY position",
                (book_id,),
            ).fetchall()
        section, offset = boundary
        return db.execute(
            """SELECT position,
                      CASE WHEN position = ? THEN substr(text, 1, ?) ELSE text END
               FROM sections WHERE book_id = ?
               AND (position < ? OR (position = ? AND ? > 0))
               ORDER BY position""",
            (section, offset, book_id, section, section, offset),
        ).fetchall()
