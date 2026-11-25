import asyncio
import logging

from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.worker import Worker

from workforce_workers.activities.platform import echo
from workforce_workers.config import WorkerSettings
from workforce_workers.workflows.platform_check import PlatformCheckWorkflow

WORKFLOWS = [PlatformCheckWorkflow]
ACTIVITIES = [echo]


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = WorkerSettings()
    client = await Client.connect(
        settings.temporal_address,
        namespace=settings.temporal_namespace,
        data_converter=pydantic_data_converter,
    )
    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=WORKFLOWS,
        activities=ACTIVITIES,
    )
    logging.getLogger(__name__).info(
        "Worker started on task queue %s", settings.temporal_task_queue
    )
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
