from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from vimi_social.domain.publication import (
    PublicationResult,
    PublicationState,
    PublicationWorkflowInput,
)


@workflow.defn
class DestinationPublicationWorkflow:
    @workflow.run
    async def run(self, workflow_input: PublicationWorkflowInput) -> PublicationResult:
        result = await workflow.execute_activity(
            "publish_destination",
            workflow_input,
            result_type=PublicationResult,
            task_queue=workflow_input.destination_task_queue,
            start_to_close_timeout=timedelta(minutes=20),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=2),
                maximum_interval=timedelta(seconds=10),
                maximum_attempts=2,
            ),
        )
        if result.state is PublicationState.UNKNOWN:
            # Reconciliation is read-only and may retry. The second mutation-activity
            # attempt above cannot issue X I/O after the first attempt durably claimed
            # DISPATCHING: fencing converts that ambiguous worker loss to UNKNOWN.
            result = await workflow.execute_activity(
                "reconcile_destination_publication",
                workflow_input,
                result_type=PublicationResult,
                task_queue=workflow_input.destination_task_queue,
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(seconds=5),
                    maximum_interval=timedelta(seconds=30),
                    maximum_attempts=3,
                ),
            )

        await workflow.execute_activity(
            "deliver_publication_result",
            args=[workflow_input, result],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=2),
                maximum_interval=timedelta(minutes=1),
                maximum_attempts=5,
            ),
        )
        return result
