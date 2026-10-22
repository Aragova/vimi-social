from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from vimi_social.domain.analysis import MediaAnalysisResult
from vimi_social.domain.media import (
    MediaPreparationResult,
    MediaPreparationState,
    MediaPreparationWorkflowInput,
)


@workflow.defn
class MediaPreparationWorkflow:
    @workflow.run
    async def run(self, workflow_input: MediaPreparationWorkflowInput) -> MediaPreparationResult:
        result = await workflow.execute_activity(
            "prepare_candidate_media",
            workflow_input,
            result_type=MediaPreparationResult,
            task_queue=workflow_input.media_task_queue,
            start_to_close_timeout=timedelta(minutes=3),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=2),
                maximum_interval=timedelta(seconds=10),
                maximum_attempts=2,
            ),
        )

        analysis_result: MediaAnalysisResult | None = None
        if result.state is MediaPreparationState.READY and result.asset_id is not None:
            analysis_result = await workflow.execute_activity(
                "analyze_prepared_media",
                args=[workflow_input, result.asset_id],
                result_type=MediaAnalysisResult,
                task_queue=workflow_input.media_task_queue,
                start_to_close_timeout=timedelta(minutes=3),
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(seconds=2),
                    maximum_interval=timedelta(seconds=10),
                    maximum_attempts=2,
                ),
            )

        await workflow.execute_activity(
            "deliver_media_preparation_result",
            args=[workflow_input, result, analysis_result],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=2),
                maximum_interval=timedelta(minutes=1),
                maximum_attempts=5,
            ),
        )
        return result
