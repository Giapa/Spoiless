"""Local API entry point."""

from typing import Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field

from spoiless import library
from spoiless.chatgpt_accounts import AccountError, list_accounts
from spoiless.chatgpt_credentials import CredentialStoreError
from spoiless.chatgpt_session import SignInBusy, SignInManager, SignInStartError
from spoiless.epub import MAX_ARCHIVE_BYTES, InvalidEpub, read_epub

app = FastAPI(title="Spoiless")
_sign_in = SignInManager()


class HealthResponse(BaseModel):
    status: str


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


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.get("/api/books", response_model=list[BookResponse])
def books() -> list[BookResponse]:
    return [
        BookResponse(
            id=book_id, title=title, section_count=count, chapters_confirmed=confirmed
        )
        for book_id, title, count, confirmed in library.list_books()
    ]


@app.post("/api/books", response_model=BookResponse, status_code=201)
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
    return BookResponse(id=book_id, title=book.title, section_count=len(book.sections))


@app.delete("/api/books/{book_id}", status_code=204)
def remove_book(book_id: str) -> Response:
    if not library.delete_book(book_id):
        raise HTTPException(404, "Book not found.")
    return Response(status_code=204)


@app.get("/api/books/{book_id}/sections", response_model=list[SectionResponse])
def sections(book_id: str) -> list[SectionResponse]:
    try:
        rows = library.get_sections(book_id)
    except library.BookNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    return [SectionResponse(position=position, text=text) for position, text in rows]


@app.get(
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


@app.get("/api/books/{book_id}/reading-units", response_model=list[ReadingUnitStart])
def reading_units(book_id: str) -> list[ReadingUnitStart]:
    try:
        units = library.get_reading_units(book_id)
    except library.BookNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    return [ReadingUnitStart(**vars(unit)) for unit in units]


@app.put("/api/books/{book_id}/reading-units", status_code=204)
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
    current_chapter: int = Field(ge=2, strict=True)


@app.get("/api/books/{book_id}/progress", response_model=ProgressResponse)
def reading_progress(book_id: str) -> ProgressResponse:
    try:
        return ProgressResponse(**vars(library.get_progress(book_id)))
    except library.BookNotFound as exc:
        raise HTTPException(404, str(exc)) from exc


@app.put("/api/books/{book_id}/progress", response_model=ProgressResponse)
def update_progress(book_id: str, request: ProgressRequest) -> ProgressResponse:
    try:
        return ProgressResponse(
            **vars(library.set_progress(book_id, request.current_chapter))
        )
    except library.BookNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


class KeywordSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)


class PassageResponse(BaseModel):
    section_position: int
    character_offset: int
    text: str


@app.post("/api/books/{book_id}/keyword-search", response_model=list[PassageResponse])
def keyword_search(
    book_id: str, request: KeywordSearchRequest
) -> list[PassageResponse]:
    from spoiless.retrieval import ProgressChanged
    from spoiless.retrieval import keyword_search as search

    try:
        return [
            PassageResponse(**vars(passage))
            for passage in search(book_id, request.query)
        ]
    except library.BookNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except ProgressChanged as exc:
        raise HTTPException(409, str(exc)) from exc


class ModelStatus(BaseModel):
    ready: bool


class ModelSetupRequest(BaseModel):
    consent: Literal[True]


@app.get("/api/semantic-model", response_model=ModelStatus)
def semantic_model_status() -> ModelStatus:
    from spoiless.embedding_model import model_ready

    return ModelStatus(ready=model_ready())


@app.post("/api/semantic-model", response_model=ModelStatus)
def setup_semantic_model(request: ModelSetupRequest) -> ModelStatus:
    from spoiless.embedding_model import setup_model

    try:
        setup_model()
    except Exception as exc:
        raise HTTPException(
            503, "Model setup failed. Check your connection and try again."
        ) from exc
    return ModelStatus(ready=True)


@app.post("/api/books/{book_id}/hybrid-search", response_model=list[PassageResponse])
def hybrid_search(book_id: str, request: KeywordSearchRequest) -> list[PassageResponse]:
    from spoiless.retrieval import ModelUnavailable, ProgressChanged
    from spoiless.retrieval import hybrid_search as search

    try:
        return [
            PassageResponse(**vars(passage))
            for passage in search(book_id, request.query)
        ]
    except library.BookNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except ProgressChanged as exc:
        raise HTTPException(409, str(exc)) from exc
    except ModelUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc


class SignInResponse(BaseModel):
    status: Literal[
        "idle",
        "saved",
        "pending",
        "processing",
        "connected",
        "denied",
        "failed",
        "expired",
        "cancelled",
    ]
    email: str | None = None
    plan_usage_enabled: bool | None = None


class SignInAction(BaseModel):
    confirm: Literal[True]


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


@app.get("/api/chatgpt/sign-in", response_model=SignInResponse)
def chatgpt_sign_in_status(request: Request, response: Response) -> SignInResponse:
    _local_request(request)
    response.headers["Cache-Control"] = "no-store"
    return SignInResponse(**vars(_sign_in.state()))


@app.post("/api/chatgpt/sign-in", response_model=SignInResponse)
def start_chatgpt_sign_in(
    request: Request, response: Response, action: SignInAction
) -> SignInResponse:
    _local_request(request, mutation=True)
    try:
        _sign_in.start()
    except SignInBusy as exc:
        raise HTTPException(409, str(exc)) from exc
    except (CredentialStoreError, SignInStartError) as exc:
        raise HTTPException(503, str(exc)) from exc
    response.headers["Cache-Control"] = "no-store"
    return SignInResponse(**vars(_sign_in.state()))


@app.post("/api/chatgpt/sign-in/cancel", response_model=SignInResponse)
def cancel_chatgpt_sign_in(
    request: Request, response: Response, action: SignInAction
) -> SignInResponse:
    _local_request(request, mutation=True)
    try:
        _sign_in.cancel()
    except SignInBusy as exc:
        raise HTTPException(409, str(exc)) from exc
    response.headers["Cache-Control"] = "no-store"
    return SignInResponse(**vars(_sign_in.state()))


class AccountResponse(BaseModel):
    id: str
    email: str | None
    active: bool


class AccountSelection(BaseModel):
    account_id: str = Field(min_length=1, max_length=64)
    confirm: Literal[True]


@app.get("/api/chatgpt/accounts", response_model=list[AccountResponse])
def chatgpt_accounts(request: Request, response: Response) -> list[AccountResponse]:
    _local_request(request)
    response.headers["Cache-Control"] = "no-store"
    return [
        AccountResponse(id=account.id, email=account.email, active=account.active)
        for account in list_accounts()
    ]


@app.post("/api/chatgpt/accounts/select", response_model=SignInResponse)
def select_chatgpt_account(
    request: Request, response: Response, selection: AccountSelection
) -> SignInResponse:
    _local_request(request, mutation=True)
    try:
        _sign_in.select_account(selection.account_id)
    except SignInBusy as exc:
        raise HTTPException(409, str(exc)) from exc
    except AccountError as exc:
        raise HTTPException(409, str(exc)) from exc
    except CredentialStoreError as exc:
        raise HTTPException(503, str(exc)) from exc
    response.headers["Cache-Control"] = "no-store"
    return SignInResponse(**vars(_sign_in.state()))
