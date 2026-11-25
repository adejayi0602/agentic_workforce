import uuid

import pytest
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import ActivityEnvironment, WorkflowEnvironment
from temporalio.worker import Worker

from workforce_workers.activities.platform import EchoInput, echo
from workforce_workers.workflows.platform_check import PlatformCheckInput, PlatformCheckWorkflow


async def test_echo_activity_returns_typed_result() -> None:
    result = await ActivityEnvironment().run(echo, EchoInput(message="hello", correlation_id="c-1"))
    assert result.message == "hello"
    assert result.correlation_id == "c-1"
    assert result.handled_by == "workforce-workers"


@pytest.mark.integration
async def test_workflow_waits_for_acknowledgement_signal() -> None:
    """Needs the Temporal test server, which is downloaded on first use."""
    async with await WorkflowEnvironment.start_time_skipping(
        data_converter=pydantic_data_converter
    ) as env:
        task_queue = f"test-{uuid.uuid4()}"
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[PlatformCheckWorkflow],
            activities=[echo],
        ):
            handle = await env.client.start_workflow(
                PlatformCheckWorkflow.run,
                PlatformCheckInput(message="hi", correlation_id="c-2"),
                id=f"platform-check-{uuid.uuid4()}",
                task_queue=task_queue,
            )
            await handle.signal(PlatformCheckWorkflow.acknowledge, "user-123")
            result = await handle.result()

    assert result.echo.message == "hi"
    assert result.acknowledged_by == "user-123"


@pytest.mark.integration
async def test_workflow_fails_closed_without_acknowledgement() -> None:
    async with await WorkflowEnvironment.start_time_skipping(
        data_converter=pydantic_data_converter
    ) as env:
        task_queue = f"test-{uuid.uuid4()}"
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[PlatformCheckWorkflow],
            activities=[echo],
        ):
            result = await env.client.execute_workflow(
                PlatformCheckWorkflow.run,
                PlatformCheckInput(
                    message="hi", correlation_id="c-3", acknowledgement_timeout_seconds=60
                ),
                id=f"platform-check-{uuid.uuid4()}",
                task_queue=task_queue,
            )

    assert result.acknowledged_by is None
