"""Local API entry point."""

from fastapi import FastAPI
from pydantic import BaseModel

from spoiless.book_assistant.api import router as book_assistant_router
from spoiless.chatgpt.api import router as chatgpt_router
from spoiless.library.api import router as library_router
from spoiless.retrieval.api import router as retrieval_router

app = FastAPI(title="Spoiless")
app.include_router(book_assistant_router)
app.include_router(chatgpt_router)
app.include_router(library_router)
app.include_router(retrieval_router)


class HealthResponse(BaseModel):
    status: str


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")
