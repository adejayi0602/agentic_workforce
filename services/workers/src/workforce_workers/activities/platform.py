from pydantic import BaseModel
from temporalio import activity


class EchoInput(BaseModel):
    message: str
    correlation_id: str


class EchoResult(BaseModel):
    message: str
    correlation_id: str
    handled_by: str


@activity.defn
async def echo(payload: EchoInput) -> EchoResult:
    """Smoke-test activity: proves a worker can receive, process and return typed payloads."""
    return EchoResult(
        message=payload.message,
        correlation_id=payload.correlation_id,
        handled_by="workforce-workers",
    )
