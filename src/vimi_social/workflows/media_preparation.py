from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from vimi_social.domain.analysis import MediaAnalysisResult, SceneAnalysisState
from vimi_social.domain.media import (
    MediaPreparationResult,
    MediaPreparationState,
    MediaPreparationWorkflowInput,
)
from vimi_social.domain.publication import (
    PublicationPreviewResult,
    RenderResult,
    VariantArtifactState,
)

_SCENE_ANALYSIS_PATCH = "media-scene-analysis-v1"
_RENDER_PREVIEW_PATCH = "media-render-preview-v1"


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

        if workflow.patched(_SCENE_ANALYSIS_PATCH):
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

            if workflow.patched(_RENDER_PREVIEW_PATCH):
                render_result: RenderResult | None = None
                preview_result: PublicationPreviewResult | None = None
                if (
                    analysis_result is not None
                    and analysis_result.state is SceneAnalysisState.READY
                    and analysis_result.analysis_id is not None
                ):
                    render_result = await workflow.execute_activity(
                        "render_variant",
                        args=[workflow_input, analysis_result.analysis_id],
                        result_type=RenderResult,
                        task_queue=workflow_input.media_task_queue,
                        start_to_close_timeout=timedelta(minutes=5),
                        retry_policy=RetryPolicy(
                            initial_interval=timedelta(seconds=2),
                            maximum_interval=timedelta(seconds=10),
                            maximum_attempts=2,
                        ),
                    )
                    if (
                        render_result is not None
                        and render_result.state is VariantArtifactState.READY
                    ):
                        preview_result = await workflow.execute_activity(
                            "prepare_publication_preview",
                            args=[workflow_input, render_result],
                            result_type=PublicationPreviewResult,
                            start_to_close_timeout=timedelta(seconds=30),
                            retry_policy=RetryPolicy(
                                initial_interval=timedelta(seconds=2),
                                maximum_interval=timedelta(seconds=10),
                                maximum_attempts=3,
                            ),
                        )

                await workflow.execute_activity(
                    "deliver_media_preparation_result",
                    args=[
                        workflow_input,
                        result,
                        analysis_result,
                        render_result,
                        preview_result,
                    ],
                    start_to_close_timeout=timedelta(minutes=2),
                    retry_policy=_delivery_retry_policy(),
                )
            else:
                # Preserve the exact PR #6 delivery command shape for histories that
                # recorded scene analysis before render/preview was introduced.
                await workflow.execute_activity(
                    "deliver_media_preparation_result",
                    args=[workflow_input, result, analysis_result],
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=_delivery_retry_policy(),
                )
        else:
            # Preserve the exact pre-PR #6 command shape for histories that began
            # before the scene-analysis patch marker existed.
            await workflow.execute_activity(
                "deliver_media_preparation_result",
                args=[workflow_input, result],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=_delivery_retry_policy(),
            )
        return result


def _delivery_retry_policy() -> RetryPolicy:
    return RetryPolicy(
        initial_interval=timedelta(seconds=2),
        maximum_interval=timedelta(minutes=1),
        maximum_attempts=5,
    )
