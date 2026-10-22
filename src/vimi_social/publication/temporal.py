import asyncio
from dataclasses import replace

from temporalio.client import Client
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from vimi_social.domain.publication import PublicationWorkflowInput
from vimi_social.workflows.destination_publication import DestinationPublicationWorkflow


class TemporalPublicationWorkflowStarter:
    def __init__(
        self,
        target: str,
        namespace: str,
        workflow_task_queue: str,
        destination_task_queue: str,
    ) -> None:
        self._target = target
        self._namespace = namespace
        self._workflow_task_queue = workflow_task_queue
        self._destination_task_queue = destination_task_queue
        self._client: Client | None = None
        self._connect_lock = asyncio.Lock()

    async def start(self, workflow_input: PublicationWorkflowInput) -> None:
        client = await self._get_client()
        prepared = replace(
            workflow_input,
            destination_task_queue=self._destination_task_queue,
        )
        try:
            await client.start_workflow(
                DestinationPublicationWorkflow.run,
                prepared,
                id=prepared.operation_key,
                task_queue=self._workflow_task_queue,
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
            )
        except WorkflowAlreadyStartedError:
            return

    async def _get_client(self) -> Client:
        if self._client is not None:
            return self._client
        async with self._connect_lock:
            if self._client is None:
                self._client = await Client.connect(
                    self._target,
                    namespace=self._namespace,
                )
        return self._client
