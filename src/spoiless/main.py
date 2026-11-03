"""Local API entry point."""

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Spoiless")


class HealthResponse(BaseModel):
    status: str


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")
