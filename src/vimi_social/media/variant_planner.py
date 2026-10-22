from collections.abc import Sequence

from vimi_social.domain.analysis import (
    PolicyDecision,
    PreflightDecision,
    RankedScene,
    RenderRecipe,
    RenderSegment,
    RenderStrategy,
    VariantPlan,
)
from vimi_social.domain.media import MediaAsset


class VariantPlanner:
    version = "variant-planner-v1"

    def plan(
        self,
        asset: MediaAsset,
        scenes: Sequence[RankedScene],
        preflight: PreflightDecision,
    ) -> VariantPlan:
        if preflight.decision in {
            PolicyDecision.MANUAL_REVIEW_REQUIRED,
            PolicyDecision.BLOCKED,
        }:
            return VariantPlan(
                destination=preflight.destination,
                decision=preflight.decision,
                capability_version=preflight.capability_version,
                policy_version=preflight.policy_version,
                planner_version=self.version,
                requires_sensitive_label=preflight.requires_sensitive_label,
                reason_codes=preflight.reason_codes,
                recipe=None,
            )

        duration_ms = asset.probe.duration_ms
        if duration_ms is None or duration_ms <= 0:
            raise ValueError("variant planning requires a positive media duration")

        if preflight.decision is PolicyDecision.DIRECT_ALLOWED:
            recipe = RenderRecipe(
                strategy=RenderStrategy.PASSTHROUGH,
                expected_duration_ms=duration_ms,
                segments=(
                    RenderSegment(
                        scene_ordinal=-1,
                        start_ms=0,
                        end_ms=duration_ms,
                        rank_score=1.0,
                    ),
                ),
            )
        else:
            limit = preflight.max_video_duration_ms
            if limit is None or limit <= 0:
                raise ValueError("adaptation-required preflight must provide a duration limit")
            recipe = _build_clip_recipe(scenes, limit)

        return VariantPlan(
            destination=preflight.destination,
            decision=preflight.decision,
            capability_version=preflight.capability_version,
            policy_version=preflight.policy_version,
            planner_version=self.version,
            requires_sensitive_label=preflight.requires_sensitive_label,
            reason_codes=preflight.reason_codes,
            recipe=recipe,
        )


def _build_clip_recipe(
    ranked_scenes: Sequence[RankedScene],
    duration_limit_ms: int,
) -> RenderRecipe:
    selected: list[RankedScene] = []
    remaining = duration_limit_ms
    for scene in ranked_scenes:
        duration = scene.end_ms - scene.start_ms
        if duration <= 0 or duration > remaining:
            continue
        selected.append(scene)
        remaining -= duration
        if remaining < 750:
            break
    if not selected:
        raise ValueError("no ranked scene fits the destination duration limit")

    chronological = sorted(selected, key=lambda scene: (scene.start_ms, scene.ordinal))
    segments = tuple(
        RenderSegment(
            scene_ordinal=scene.ordinal,
            start_ms=scene.start_ms,
            end_ms=scene.end_ms,
            rank_score=scene.rank_score,
        )
        for scene in chronological
    )
    return RenderRecipe(
        strategy=RenderStrategy.CLIP_SEQUENCE,
        expected_duration_ms=sum(segment.end_ms - segment.start_ms for segment in segments),
        segments=segments,
    )
