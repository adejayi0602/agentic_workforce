"""Starting durable workflows from the API (ADR-0004).

Workflows are started by name, so the API doesn't import worker code. The workflow id is
derived from the version id, and an already-running workflow is reused, so starting twice is
harmless.
"""

import logging
import uuid

from temporalio.client import Client
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.contrib.pydantic import pydantic_data_converter

from workforce_api.config import Settings

logger = logging.getLogger(__name__)

PROCESS_DOCUMENT_WORKFLOW = "ProcessDocumentWorkflow"


def process_document_workflow_id(version_id: uuid.UUID) -> str:
    return f"process-document-{version_id}"


class WorkflowStarter:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: Client | None = None

    async def _connect(self) -> Client:
        if self._client is None:
            self._client = await Client.connect(
                self._settings.temporal_address,
                namespace=self._settings.temporal_namespace,
                data_converter=pydantic_data_converter,
            )
        return self._client

    async def start_document_processing(
        self, *, organisation_id: uuid.UUID, version_id: uuid.UUID
    ) -> str:
        client = await self._connect()
        workflow_id = process_document_workflow_id(version_id)
        await client.start_workflow(
            PROCESS_DOCUMENT_WORKFLOW,
            {"organisation_id": str(organisation_id), "version_id": str(version_id)},
            id=workflow_id,
            task_queue=self._settings.temporal_task_queue,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
        )
        return workflow_id

    async def close(self) -> None:
        self._client = None
