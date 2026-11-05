from spoiless.book_assistant.citations import validate_answer
from spoiless.retrieval.search import Passage


def test_valid_citation_resolves_to_the_exact_retrieved_passage():
    passages = [
        Passage(
            section_position=4,
            character_offset=120,
            text="Mira found the key in the garden.",
        )
    ]
    result = validate_answer(
        '{"answer":"Mira found a key.",'
        '"citations":[{"passage":0,"quote":"found the key"}]}',
        passages,
    )
    assert result.answer == "Mira found a key."
    assert len(result.citations) == 1
    assert result.citations[0].section_position == 4
    assert result.citations[0].character_offset == 125
    assert result.citations[0].quote == "found the key"


def test_citations_cannot_point_to_unretrieved_passages():
    import pytest

    from spoiless.book_assistant.citations import CitationValidationError

    passages = [Passage(0, 0, "Read passage"), Passage(1, 0, "Another passage")]
    with pytest.raises(CitationValidationError):
        validate_answer(
            '{"answer":"claim","citations":[{"passage":-1,"quote":"Another passage"}]}',
            passages,
        )


def test_fabricated_quote_is_rejected_without_leaking_answer():
    import pytest

    from spoiless.book_assistant.citations import CitationValidationError

    with pytest.raises(CitationValidationError) as error:
        validate_answer(
            '{"answer":"private generated text",'
            '"citations":[{"passage":0,"quote":"unread revelation"}]}',
            [Passage(0, 0, "Only completed text")],
        )
    assert "private generated text" not in str(error.value)
    assert "unread revelation" not in str(error.value)


def test_uncited_answers_are_withheld():
    import pytest

    from spoiless.book_assistant.citations import CitationValidationError

    with pytest.raises(CitationValidationError):
        validate_answer(
            '{"answer":"Unsupported claim","citations":[]}',
            [Passage(0, 0, "Read passage")],
        )


def test_blank_quotes_cannot_be_used_as_evidence():
    import pytest

    from spoiless.book_assistant.citations import CitationValidationError

    for quote in ("", " "):
        import json

        raw = json.dumps(
            {"answer": "claim", "citations": [{"passage": 0, "quote": quote}]}
        )
        with pytest.raises(CitationValidationError):
            validate_answer(raw, [Passage(0, 0, "Read passage")])


def test_malformed_response_is_rejected_without_exposing_its_contents():
    import pytest

    from spoiless.book_assistant.citations import CitationValidationError

    with pytest.raises(CitationValidationError) as error:
        validate_answer(
            '{"answer":"private spoiler","citations":"incorrect"}',
            [Passage(0, 0, "A passage")],
        )
    assert "private spoiler" not in str(error.value)
    assert error.value.__cause__ is None


def test_citation_offset_uses_unicode_characters():
    import json

    raw = json.dumps(
        {
            "answer": "A key was found.",
            "citations": [{"passage": 0, "quote": "found a key"}],
        }
    )
    result = validate_answer(raw, [Passage(3, 20, "🗝️ Mira found a key.")])
    assert result.citations[0].character_offset == 28


def test_blank_answer_is_not_returned():
    import pytest

    from spoiless.book_assistant.citations import CitationValidationError

    with pytest.raises(CitationValidationError):
        validate_answer(
            '{"answer":"  ","citations":[{"passage":0,"quote":"Read"}]}',
            [Passage(0, 0, "Read passage")],
        )


def test_invalid_passage_ids_and_mixed_validity_withhold_whole_answer():
    import json

    import pytest

    from spoiless.book_assistant.citations import CitationValidationError

    passages = [Passage(0, 0, "A known passage")]
    for wrong in (1, True, "0"):
        raw = json.dumps(
            {
                "answer": "claim",
                "citations": [
                    {"passage": 0, "quote": "known"},
                    {"passage": wrong, "quote": "known"},
                ],
            }
        )
        with pytest.raises(CitationValidationError):
            validate_answer(raw, passages)
