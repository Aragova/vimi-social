from contextlib import suppress
from dataclasses import replace
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

from vimi_social.domain.interest import XInterestSyncResult
from vimi_social.domain.source import (
    ScoutContinuationWorkflowInput,
    ScoutRunResult,
    ScoutWorkflowInput,
    XTimelineSeedResult,
)

_SOURCE_PREFLIGHT_PATCH = "scout-source-preflight-v1"
_X_INTEREST_SYNC_PATCH = "scout-x-interest-sync-v1"
_X_HOME_TIMELINE_SEED_PATCH = "scout-x-home-timeline-seed-v1"


@workflow.defn
class ScoutWorkflow:
    @workflow.run
    async def run(self, workflow_input: ScoutWorkflowInput) -> ScoutRunResult:
        sources_available = True
        if workflow.patched(_SOURCE_PREFLIGHT_PATCH):
            # Fail closed for paid context reads. If the preflight activity itself
            # is unavailable, the main Scout activity still performs its own route
            # validation, but no user-context provider read is attempted first.
            sources_available = False
            with suppress(ActivityError):
                sources_available = await workflow.execute_activity(
                    "validate_scout_sources",
                    workflow_input,
                    result_type=bool,
                    schedule_to_close_timeout=timedelta(seconds=30),
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )

        # Preserve deterministic replay for Scout histories created before the
        # personalization activity existed. New histories record this patch marker
        # and run the best-effort profile refresh before provider discovery.
        if sources_available and workflow.patched(_X_INTEREST_SYNC_PATCH):
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

        seed_result = XTimelineSeedResult()
        if sources_available and workflow.patched(_X_HOME_TIMELINE_SEED_PATCH):
            # This is a separate candidate source from Search API. It executes on
            # the credential-owning destination worker so the OAuth token never
            # enters Scout worker environment or workflow history. Provider reads
            # are bounded to one page and never retried automatically.
            with suppress(ActivityError):
                seed_result = await workflow.execute_activity(
                    "fetch_x_home_timeline_seed",
                    workflow_input,
                    result_type=XTimelineSeedResult,
                    task_queue=workflow_input.interest_task_queue,
                    schedule_to_close_timeout=timedelta(minutes=2),
                    start_to_close_timeout=timedelta(minutes=2),
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )

        scout_input = replace(
            workflow_input,
            seed_candidates=seed_result.candidates,
            seed_posts_read=seed_result.posts_read,
            seed_failure_code=seed_result.failure_code,
        )
        result = await workflow.execute_activity(
            "execute_scout_task",
            scout_input,
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