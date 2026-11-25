from uuid import uuid4

from workforce_contracts import ErrorBody, ErrorCode, ErrorEnvelope


def test_error_envelope_matches_spec_shape() -> None:
    correlation_id = uuid4()
    envelope = ErrorEnvelope(
        error=ErrorBody(
            code=ErrorCode.REQUIREMENT_AMBIGUOUS,
            message="Execution is blocked pending clarification.",
            correlation_id=correlation_id,
            details={"requirement_id": "REQ-PAY-014", "blocked_task_ids": []},
        )
    )

    payload = envelope.model_dump(mode="json")

    assert payload == {
        "error": {
            "code": "REQUIREMENT_AMBIGUOUS",
            "message": "Execution is blocked pending clarification.",
            "correlation_id": str(correlation_id),
            "details": {"requirement_id": "REQ-PAY-014", "blocked_task_ids": []},
        }
    }


def test_error_codes_are_unique() -> None:
    values = [code.value for code in ErrorCode]
    assert len(values) == len(set(values))
