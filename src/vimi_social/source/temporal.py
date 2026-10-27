import asyncio

from temporalio.client import Client
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from vimi_social.domain.source import (
    ScoutContinuationWorkflowInput,
    ScoutWorkflowInput,
)
from vimi_social.workflows.scout import ScoutContinuationWorkflow, ScoutWorkflow


class TemporalScoutWorkflowStarter:
    def __init__(
        self,
        target: str,
        namespace: str,
        task_queue: str,
        interest_task_queue: str = "vimi-social-destination",
    ) -> None:
        self._target = target
        self._namespace = namespace
        self._task_queue = task_queue
        self._interest_task_queue = interest_task_queue
        self._client: Client | None = None
        self._connect_lock = asyncio.Lock()

    async def start(self, operation_key: str, execution_token: str) -> None:
        client = await self._get_client()
        workflow_input = ScoutWorkflowInput(
            operation_key=operation_key,
            execution_token=execution_token,
            interest_task_queue=self._interest_task_queue,
        )
        try:
            await client.start_workflow(
                ScoutWorkflow.run,
                workflow_input,
                id=operation_key,
                task_queue=self._task_queue,
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
            )
        except WorkflowAlreadyStartedError:
            return

    async def start_continuation(
        self,
        workflow_input: ScoutContinuationWorkflowInput,
    ) -> None:
        client = await self._get_client()
        try:
            await client.start_workflow(
                ScoutContinuationWorkflow.run,
                workflow_input,
                id=workflow_input.request_key,
                task_queue=self._task_queue,
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
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
