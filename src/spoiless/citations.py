"""Validate model citations against passages supplied by the caller.

The caller must enforce the book's eligibility boundary before and after
inference. Citation matching alone does not verify factual support.
"""

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, ValidationError

from spoiless.retrieval import Passage


class CitationValidationError(Exception):
    """The response or its citations could not be verified."""


@dataclass(frozen=True)
class Citation:
    section_position: int
    character_offset: int
    quote: str


@dataclass(frozen=True)
class ValidatedAnswer:
    answer: str
    citations: tuple[Citation, ...]


class _CitationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    passage: int
    quote: str


class _AnswerInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    answer: str
    citations: list[_CitationInput]


def validate_answer(raw: str, passages: list[Passage]) -> ValidatedAnswer:
    """Resolve quoted citations against the supplied retrieved passages."""
    try:
        response = _AnswerInput.model_validate_json(raw)
    except (ValidationError, ValueError, TypeError):
        raise CitationValidationError(
            "Could not verify the answer citations."
        ) from None
    if not response.answer.strip() or not response.citations:
        raise CitationValidationError("Could not verify the answer citations.")
    citations = []
    for item in response.citations:
        if not item.quote.strip() or item.passage < 0 or item.passage >= len(passages):
            raise CitationValidationError("Could not verify the answer citations.")
        passage = passages[item.passage]
        offset = passage.text.find(item.quote)
        if offset < 0:
            raise CitationValidationError("Could not verify the answer citations.")
        citations.append(
            Citation(
                passage.section_position, passage.character_offset + offset, item.quote
            )
        )
    return ValidatedAnswer(response.answer, tuple(citations))
