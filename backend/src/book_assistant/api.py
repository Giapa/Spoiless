"""Book questions, recaps, and conversation API routes."""

from collections.abc import Callable
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from src.book_assistant.citations import ValidatedAnswer
from src.chatgpt.accounts import AccountError
from src.chatgpt.credentials import CredentialStoreError
from src.chatgpt.session import SignInBusy, SignInStartError
from src.database import connect
from src.library import storage as library
from src.local_security import _local_request

router = APIRouter()


class AnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=500, strict=True)
    model: str = Field(min_length=1, max_length=256, strict=True)
    confirm: bool = Field(strict=True)


class AnswerCitation(BaseModel):
    section_position: int
    character_offset: int
    quote: str


class AnswerResponse(BaseModel):
    answer: str
    citations: list[AnswerCitation]


class ConversationTurn(AnswerResponse):
    question: str


@router.get("/api/books/{book_id}/conversation", response_model=list[ConversationTurn])
def conversation(
    book_id: str, request: Request, response: Response
) -> list[ConversationTurn]:
    import json

    _local_request(request)
    with connect() as db:
        db.execute("BEGIN")
        try:
            progress = library._progress(db, book_id)
        except library.BookNotFound:
            raise HTTPException(404, "Book not found.") from None
        if progress.current_chapter is None or not (
            2 <= progress.current_chapter <= progress.chapter_count + 1
        ):
            raise HTTPException(
                422, "Confirm chapters and select reading progress first."
            )
        rows = db.execute(
            "SELECT question, answer, citations FROM conversation_turns "
            "WHERE book_id = ? AND active = 1 ORDER BY id",
            (book_id,),
        ).fetchall()
    response.headers["Cache-Control"] = "no-store"
    return [
        ConversationTurn(question=q, answer=a, citations=json.loads(c))
        for q, a, c in rows
    ]


def _run_book_generation(
    request: Request,
    response: Response,
    confirm: bool,
    generate: Callable[[str], ValidatedAnswer],
) -> AnswerResponse:
    from src.book_assistant.citations import CitationValidationError
    from src.chatgpt.accounts import active_account
    from src.chatgpt.exchange import ExchangeError
    from src.chatgpt.inference import InferenceError
    from src.chatgpt.models import ModelCatalogError
    from src.retrieval.search import ModelUnavailable, ProgressChanged

    _local_request(request, mutation=True)
    if not confirm:
        raise HTTPException(422, "Confirmation is required.")
    account = active_account()
    if account is None:
        raise HTTPException(409, "Connect a ChatGPT account first.")
    try:
        result = generate(account.id)
    except library.BookNotFound:
        raise HTTPException(404, "Book not found.") from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    except CitationValidationError:
        raise HTTPException(
            502, "Could not verify the answer citations. Please retry."
        ) from None
    except ProgressChanged:
        raise HTTPException(409, "Reading progress changed. Please retry.") from None
    except ModelUnavailable:
        raise HTTPException(
            503,
            "Local search model unavailable. "
            "Download it in Local search settings and retry.",
        ) from None
    except AccountError:
        raise HTTPException(409, "This account needs to sign in again.") from None
    except (CredentialStoreError, SignInStartError):
        raise HTTPException(
            503, "The ChatGPT credential store is unavailable."
        ) from None
    except SignInBusy:
        raise HTTPException(409, "ChatGPT account is busy. Please retry.") from None
    except ExchangeError:
        raise HTTPException(
            503, "Could not refresh the ChatGPT connection. Please retry."
        ) from None
    except ModelCatalogError:
        raise HTTPException(
            503, "Could not load ChatGPT models. Please retry."
        ) from None
    except InferenceError as exc:
        if exc.code == "subscription_sharing_usage_limit_exceeded":
            raise HTTPException(
                429,
                {
                    "code": exc.code,
                    "message": "Review your usage limit in ChatGPT settings.",
                },
            ) from None
        if exc.code == "subscription_sharing_usage_unavailable":
            raise HTTPException(
                503,
                {
                    "code": exc.code,
                    "message": "ChatGPT usage is unavailable. Please retry.",
                },
            ) from None
        raise HTTPException(
            503, "Could not get a response from ChatGPT. Please retry."
        ) from None
    response.headers["Cache-Control"] = "no-store"
    return AnswerResponse(
        answer=result.answer,
        citations=[AnswerCitation(**vars(item)) for item in result.citations],
    )


class RecapRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chapter: int = Field(ge=1, strict=True)
    mode: Literal["chapter", "through"] = "chapter"
    model: str = Field(min_length=1, max_length=256, strict=True)
    confirm: bool = Field(strict=True)


@router.post("/api/books/{book_id}/answer", response_model=AnswerResponse)
def answer_book(
    book_id: str, request: Request, response: Response, action: AnswerRequest
) -> AnswerResponse:
    from src.book_assistant.questions import answer_book_question

    return _run_book_generation(
        request,
        response,
        action.confirm,
        lambda account: answer_book_question(
            book_id, account, action.model, action.question
        ),
    )


@router.post("/api/books/{book_id}/recap", response_model=AnswerResponse)
def recap_book(
    book_id: str, request: Request, response: Response, action: RecapRequest
) -> AnswerResponse:
    from src.book_assistant.recaps import recap_chapter

    return _run_book_generation(
        request,
        response,
        action.confirm,
        lambda account: recap_chapter(
            book_id, account, action.model, action.chapter, action.mode
        ),
    )
