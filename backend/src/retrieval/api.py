"""Local retrieval and semantic model API routes."""

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.library import storage as library

router = APIRouter()


class KeywordSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)


class PassageResponse(BaseModel):
    section_position: int
    character_offset: int
    text: str


@router.post(
    "/api/books/{book_id}/keyword-search", response_model=list[PassageResponse]
)
def keyword_search(
    book_id: str, request: KeywordSearchRequest
) -> list[PassageResponse]:
    from src.retrieval.search import ProgressChanged
    from src.retrieval.search import keyword_search as search

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


@router.get("/api/semantic-model", response_model=ModelStatus)
def semantic_model_status() -> ModelStatus:
    from src.retrieval.embedding_model import model_ready

    return ModelStatus(ready=model_ready())


@router.post("/api/semantic-model", response_model=ModelStatus)
def setup_semantic_model(request: ModelSetupRequest) -> ModelStatus:
    from src.retrieval.embedding_model import setup_model

    try:
        setup_model()
    except Exception as exc:
        raise HTTPException(
            503, "Model setup failed. Check your connection and try again."
        ) from exc
    return ModelStatus(ready=True)


@router.post("/api/books/{book_id}/hybrid-search", response_model=list[PassageResponse])
def hybrid_search(book_id: str, request: KeywordSearchRequest) -> list[PassageResponse]:
    from src.retrieval.search import ModelUnavailable, ProgressChanged
    from src.retrieval.search import hybrid_search as search

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
