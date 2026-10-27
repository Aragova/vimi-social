from contextlib import suppress
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

from vimi_social.domain.interest import XInterestSyncResult
from vimi_social.domain.source import (
    ScoutContinuationWorkflowInput,
    ScoutRunResult,
    ScoutWorkflowInput,
)

_X_INTEREST_SYNC_PATCH = "scout-x-interest-sync-v1"


@workflow.defn
class ScoutWorkflow:
    @workflow.run
    async def run(self, workflow_input: ScoutWorkflowInput) -> ScoutRunResult:
        # Preserve deterministic replay for Scout histories created before the
        # personalization activity existed. New histories record this patch marker
        # and run the best-effort profile refresh before provider discovery.
        if workflow.patched(_X_INTEREST_SYNC_PATCH):
            # User-context reads can incur provider charges. Refresh is best-effort,
            # never retried automatically, and must not block an otherwise valid
            # Scout run. schedule_to_close_timeout also bounds queue wait when the
            # destination worker is unavailable or backlogged.
            with suppress(ActivityError):
                await workflow.execute_activity(
                    "sync_x_user_interest_profile",
                    workflow_input,
                    result_type=XInterestSyncResult,
                    task_queue=workflow_input.interest_task_queue,
                    schedule_to_close_timeout=timedelta(minutes=2),
                    start_to_close_timeout=timedelta(minutes=2),
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )

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
