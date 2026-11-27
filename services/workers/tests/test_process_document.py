"""ProcessDocumentWorkflow orchestration, with stub activities (Temporal time-skipping)."""

import uuid
from collections import deque

import pytest
from temporalio import activity
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from workforce_workers.activities.documents import ExtractResult, VersionRef
from workforce_workers.workflows.process_document import ProcessDocumentWorkflow, ProcessResult

pytestmark = pytest.mark.integration


class Stubs:
    """Scripted scan verdicts. "pending" raises, like the real activity, so Temporal retries."""

    def __init__(self, verdicts: list[str]) -> None:
        self.verdicts = deque(verdicts)
        self.scans = 0
        self.extracts = 0

    @activity.defn(name="scan_document_version")
    async def scan(self, ref: VersionRef) -> str:
        self.scans += 1
        verdict = self.verdicts.popleft() if len(self.verdicts) > 1 else self.verdicts[0]
        if verdict == "pending":
            raise ApplicationError("pending", type="ScanNotReady")
        return verdict

    @activity.defn(name="extract_document_version")
    async def extract(self, ref: VersionRef) -> ExtractResult:
        self.extracts += 1
        return ExtractResult(status="ready", run_id="run-1")


async def run(stubs: Stubs) -> ProcessResult:
    async with await WorkflowEnvironment.start_time_skipping(
        data_converter=pydantic_data_converter
    ) as env:
        queue = f"test-{uuid.uuid4()}"
        async with Worker(
            env.client,
            task_queue=queue,
            workflows=[ProcessDocumentWorkflow],
            activities=[stubs.scan, stubs.extract],
        ):
            ref = VersionRef(organisation_id=uuid.uuid4(), version_id=uuid.uuid4())
            return await env.client.execute_workflow(
                ProcessDocumentWorkflow.run,
                ref,
                id=f"process-document-{ref.version_id}",
                task_queue=queue,
                result_type=ProcessResult,
            )


async def test_clean_file_is_extracted() -> None:
    stubs = Stubs(["clean"])
    result = await run(stubs)
    assert result.outcome == "ready"
    assert result.run_id == "run-1"
    assert stubs.extracts == 1


async def test_infected_file_is_never_extracted() -> None:
    stubs = Stubs(["quarantined"])
    result = await run(stubs)
    assert result.outcome == "scan_quarantined"
    assert stubs.extracts == 0


async def test_pending_verdict_is_retried_until_clean() -> None:
    stubs = Stubs(["pending", "pending", "pending", "clean"])
    result = await run(stubs)
    assert result.outcome == "ready"
    assert stubs.scans == 4


async def test_repeated_scanner_failure_stops_without_extracting() -> None:
    stubs = Stubs(["failed"])
    result = await run(stubs)
    assert result.outcome == "scan_failed"
    assert stubs.scans == 3
    assert stubs.extracts == 0


async def test_a_scan_that_never_gets_a_verdict_fails_closed() -> None:
    stubs = Stubs(["pending"])  # GuardDuty never tags the object
    result = await run(stubs)
    assert result.outcome == "scan_timed_out"
    assert stubs.extracts == 0
