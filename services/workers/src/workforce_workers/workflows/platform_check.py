"""PlatformCheckWorkflow: the Sprint 0 smoke test for durable execution.

It runs one activity, then waits durably for an `acknowledge` signal, the same pattern the
real approval and clarification gates use (spec §9, §10.3). It proves end to end that the
worker, the Temporal server and typed payloads work together.
"""

from contextlib import suppress
from datetime import timedelta

from pydantic import BaseModel
from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from workforce_workers.activities.platform import EchoInput, EchoResult, echo


class PlatformCheckInput(BaseModel):
    message: str
    correlation_id: str
    acknowledgement_timeout_seconds: int = 3600


class PlatformCheckResult(BaseModel):
    echo: EchoResult
    acknowledged_by: str | None


@workflow.defn
class PlatformCheckWorkflow:
    def __init__(self) -> None:
        self._acknowledged_by: str | None = None

    @workflow.signal
    def acknowledge(self, actor_id: str) -> None:
        self._acknowledged_by = actor_id

    @workflow.run
    async def run(self, payload: PlatformCheckInput) -> PlatformCheckResult:
        result = await workflow.execute_activity(
            echo,
            EchoInput(message=payload.message, correlation_id=payload.correlation_id),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        # Fail closed: on timeout the result is returned unacknowledged.
        with suppress(TimeoutError):
            await workflow.wait_condition(
                lambda: self._acknowledged_by is not None,
                timeout=timedelta(seconds=payload.acknowledgement_timeout_seconds),
            )
        return PlatformCheckResult(echo=result, acknowledged_by=self._acknowledged_by)
