"""ProcessDocumentWorkflow: scan, then extract, one document version (spec §9, ADR-0012).

Deterministic orchestration only. Activities do the I/O and are safe to retry. The workflow id
is derived from the version id, so a version can't be processed twice at the same time.
"""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from workforce_workers.activities.documents import ExtractResult, VersionRef

SCAN_FAILURE_RETRIES = 3

# "Pending" (GuardDuty hasn't tagged the object yet) and "not ready" (upload not committed)
# are retried with backoff for up to 30 minutes.
SCAN_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=3),
    backoff_coefficient=1.6,
    maximum_interval=timedelta(seconds=60),
    maximum_attempts=0,  # bounded by schedule_to_close below
)
EXTRACT_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=5),
    maximum_attempts=3,  # only unexpected errors retry; bad files return a result instead
)


def workflow_id_for(version_id: str) -> str:
    return f"process-document-{version_id}"


class ProcessResult(VersionRef):
    outcome: str
    run_id: str | None = None
    error_code: str | None = None


@workflow.defn
class ProcessDocumentWorkflow:
    @workflow.run
    async def run(self, ref: VersionRef) -> ProcessResult:
        verdict = "failed"
        for attempt in range(1, SCAN_FAILURE_RETRIES + 1):
            try:
                verdict = await workflow.execute_activity(
                    "scan_document_version",
                    ref,
                    result_type=str,
                    start_to_close_timeout=timedelta(minutes=2),
                    schedule_to_close_timeout=timedelta(minutes=30),
                    retry_policy=SCAN_RETRY,
                )
            except ActivityError:
                verdict = "timed_out"
                break
            if verdict != "failed":
                break
            if attempt < SCAN_FAILURE_RETRIES:
                await workflow.sleep(timedelta(seconds=30 * attempt))

        if verdict != "clean":
            # quarantined, a scanner that kept failing, or a scan that never got a verdict.
            # Nothing is parsed (fail closed).
            return ProcessResult(**ref.model_dump(), outcome=f"scan_{verdict}")

        extracted = await workflow.execute_activity(
            "extract_document_version",
            ref,
            result_type=ExtractResult,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=EXTRACT_RETRY,
        )
        return ProcessResult(
            **ref.model_dump(),
            outcome=extracted.status,
            run_id=extracted.run_id,
            error_code=extracted.error_code,
        )
