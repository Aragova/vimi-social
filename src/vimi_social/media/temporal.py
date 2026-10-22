import asyncio
from dataclasses import replace

from temporalio.client import Client
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from vimi_social.domain.media import MediaPreparationWorkflowInput
from vimi_social.workflows.media_preparation import MediaPreparationWorkflow


class TemporalMediaPreparationStarter:
    def __init__(
        self,
        target: str,
        namespace: str,
        workflow_task_queue: str,
        media_task_queue: str,
    ) -> None:
        self._target = target
        self._namespace = namespace
        self._workflow_task_queue = workflow_task_queue
        self._media_task_queue = media_task_queue
        self._client: Client | None = None
        self._connect_lock = asyncio.Lock()

    async def start(self, workflow_input: MediaPreparationWorkflowInput) -> None:
        client = await self._get_client()
        prepared_input = replace(workflow_input, media_task_queue=self._media_task_queue)
        try:
            await client.start_workflow(
                MediaPreparationWorkflow.run,
                prepared_input,
                id=prepared_input.operation_key,
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
