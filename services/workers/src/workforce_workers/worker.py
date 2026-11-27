import asyncio
import logging
from collections.abc import Callable
from typing import Any

from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.worker import Worker

from workforce_api.db import Database
from workforce_api.storage import ObjectStore
from workforce_intake.scanning import EicarScanner, GuardDutyScanner, Scanner
from workforce_workers.activities.documents import DocumentActivities
from workforce_workers.activities.platform import echo
from workforce_workers.config import WorkerSettings
from workforce_workers.workflows.platform_check import PlatformCheckWorkflow
from workforce_workers.workflows.process_document import ProcessDocumentWorkflow

WORKFLOWS = [PlatformCheckWorkflow, ProcessDocumentWorkflow]


def build_activities(settings: WorkerSettings) -> list[Callable[..., Any]]:
    database = Database(settings.worker_database_url)
    store = ObjectStore(endpoint_url=settings.s3_endpoint_url, region=settings.s3_region)
    scanner: Scanner = (
        GuardDutyScanner(store.client) if settings.scanner == "guardduty" else EicarScanner()
    )
    documents = DocumentActivities(
        database.sessions, store, scanner, artefacts_bucket=settings.s3_bucket_artefacts
    )
    return [echo, documents.scan, documents.extract]


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
        activities=build_activities(settings),
    )
    logging.getLogger(__name__).info(
        "Worker started on task queue %s (scanner: %s)",
        settings.temporal_task_queue,
        settings.scanner,
    )
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
