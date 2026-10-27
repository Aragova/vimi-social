from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from vimi_social.domain.source import (
    ScoutContinuationWorkflowInput,
    ScoutRunResult,
    ScoutWorkflowInput,
)


@workflow.defn
class ScoutWorkflow:
    @workflow.run
    async def run(self, workflow_input: ScoutWorkflowInput) -> ScoutRunResult:
        result = await workflow.execute_activity(
            "execute_scout_task",
            workflow_input,
            result_type=ScoutRunResult,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=2),
                maximum_interval=timedelta(seconds=10),
                maximum_attempts=2,
            ),
        )
        await workflow.execute_activity(
            "deliver_scout_results",
            args=[workflow_input, result],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=2),
                maximum_interval=timedelta(minutes=1),
                maximum_attempts=5,
            ),
        )
        return result


@workflow.defn
class ScoutContinuationWorkflow:
    @workflow.run
    async def run(
        self,
        workflow_input: ScoutContinuationWorkflowInput,
    ) -> ScoutRunResult:
        # The first activity can incur X post-read charges. Never retry it
        # automatically after an ambiguous worker/provider failure.
        result = await workflow.execute_activity(
            "continue_scout_results",
            workflow_input,
            result_type=ScoutRunResult,
            start_to_close_timeout=timedelta(minutes=3),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
        await workflow.execute_activity(
            "deliver_scout_continuation",
            args=[workflow_input, result],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=2),
                maximum_interval=timedelta(minutes=1),
                maximum_attempts=5,
            ),
        )
        return result
