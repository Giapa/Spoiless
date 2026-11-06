"""Library and reading-progress API routes."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from src.library import storage as library
from src.library.epub import MAX_ARCHIVE_BYTES, InvalidEpub, read_epub

router = APIRouter()


class BookResponse(BaseModel):
    id: str
    title: str
    section_count: int
    chapters_confirmed: bool = False


class SectionResponse(BaseModel):
    position: int
    text: str


class NavigationEntryResponse(BaseModel):
    title: str | None
    section_position: int | None
    character_offset: int | None


class ReadingUnitStart(BaseModel):
    kind: Literal["front_matter", "chapter"]
    section_position: int = Field(ge=0, strict=True)
    character_offset: int = Field(ge=0, strict=True)


class ReadingUnitsRequest(BaseModel):
    units: list[ReadingUnitStart] = Field(min_length=1, max_length=10000)


class ChapterAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str = Field(min_length=1, max_length=256, strict=True)
    confirm: bool = Field(strict=True)


@router.post("/api/books/{book_id}/analyze-chapters", status_code=204)
def analyze_chapters(
    book_id: str, request: Request, action: ChapterAnalysisRequest
) -> Response:
    from src.chatgpt.accounts import AccountError, active_account
    from src.chatgpt.credentials import CredentialStoreError
    from src.chatgpt.exchange import ExchangeError
    from src.chatgpt.inference import InferenceError
    from src.chatgpt.models import ModelCatalogError
    from src.chatgpt.session import SignInBusy, SignInStartError
    from src.library.chapter_analysis import analyze_chapters as analyze
    from src.local_security import _local_request

    _local_request(request, mutation=True)
    if not action.confirm:
        raise HTTPException(422, "Confirmation is required.")
    account = active_account()
    if account is None:
        raise HTTPException(409, "Connect a ChatGPT account first.")
    try:
        analyze(book_id, account.id, action.model)
    except library.BookNotFound:
        raise HTTPException(404, "Book not found.") from None
    except library.ChapterMapChanged as exc:
        raise HTTPException(409, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    except AccountError:
        raise HTTPException(409, "This account needs to sign in again.") from None
    except SignInBusy:
        raise HTTPException(409, "ChatGPT account is busy. Please retry.") from None
    except (
        CredentialStoreError,
        SignInStartError,
        ExchangeError,
        ModelCatalogError,
        InferenceError,
    ):
        raise HTTPException(
            503, "Could not analyze chapters with ChatGPT. Please retry."
        ) from None
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


@router.get("/api/books", response_model=list[BookResponse])
def books() -> list[BookResponse]:
    return [
        BookResponse(
            id=book_id, title=title, section_count=count, chapters_confirmed=confirmed
        )
        for book_id, title, count, confirmed in library.list_books()
    ]


@router.post("/api/books", response_model=BookResponse, status_code=201)
async def import_book(request: Request) -> BookResponse:
    if (
        request.headers.get("content-type", "").split(";")[0].strip()
        != "application/epub+zip"
    ):
        raise HTTPException(
            415, "Upload an EPUB with content type application/epub+zip."
        )
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > MAX_ARCHIVE_BYTES:
            raise HTTPException(413, "EPUB exceeds the 25 MB upload limit.")
        data.extend(chunk)
    try:
        book = read_epub(bytes(data))
    except InvalidEpub as exc:
        raise HTTPException(422, str(exc)) from exc
    book_id = library.add_book(book)
    return BookResponse(
        id=book_id,
        title=book.title,
        section_count=len(book.sections),
        chapters_confirmed=bool(book.chapters),
    )


@router.delete("/api/books/{book_id}", status_code=204)
def remove_book(book_id: str) -> Response:
    if not library.delete_book(book_id):
        raise HTTPException(404, "Book not found.")
    return Response(status_code=204)


@router.get("/api/books/{book_id}/sections", response_model=list[SectionResponse])
def sections(book_id: str) -> list[SectionResponse]:
    try:
        rows = library.get_sections(book_id)
    except library.BookNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    return [SectionResponse(position=position, text=text) for position, text in rows]


@router.get(
    "/api/books/{book_id}/navigation", response_model=list[NavigationEntryResponse]
)
def navigation(
    book_id: str, include_titles: bool = False
) -> list[NavigationEntryResponse]:
    try:
        entries = library.get_navigation(book_id)
    except library.BookNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    return [
        NavigationEntryResponse(
            title=entry.title if include_titles else None,
            section_position=entry.section_position,
            character_offset=entry.character_offset,
        )
        for entry in entries
    ]


@router.get("/api/books/{book_id}/reading-units", response_model=list[ReadingUnitStart])
def reading_units(book_id: str) -> list[ReadingUnitStart]:
    try:
        units = library.get_reading_units(book_id)
    except library.BookNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    return [ReadingUnitStart(**vars(unit)) for unit in units]


@router.put("/api/books/{book_id}/reading-units", status_code=204)
def confirm_units(book_id: str, request: ReadingUnitsRequest) -> Response:
    units = [library.ReadingUnitStart(**unit.model_dump()) for unit in request.units]
    try:
        library.confirm_reading_units(book_id, units)
    except library.BookNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return Response(status_code=204)


class ProgressResponse(BaseModel):
    chapter_count: int
    current_chapter: int | None


class ProgressRequest(BaseModel):
    current_chapter: int = Field(ge=1, strict=True)


@router.get("/api/books/{book_id}/progress", response_model=ProgressResponse)
def reading_progress(book_id: str) -> ProgressResponse:
    try:
        return ProgressResponse(**vars(library.get_progress(book_id)))
    except library.BookNotFound as exc:
        raise HTTPException(404, str(exc)) from exc


@router.put("/api/books/{book_id}/progress", response_model=ProgressResponse)
def update_progress(book_id: str, request: ProgressRequest) -> ProgressResponse:
    try:
        return ProgressResponse(
            **vars(library.set_progress(book_id, request.current_chapter))
        )
    except library.BookNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
