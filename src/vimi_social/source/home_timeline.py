from contextvars import ContextVar

from temporalio import activity

from vimi_social.domain.source import CandidateContent, ScoutRunResult, ScoutWorkflowInput
from vimi_social.source.retrieval_v3 import RetrievalV3ScoutActivities

_CURRENT_HOME_TIMELINE_SEEDS: ContextVar[tuple[CandidateContent, ...]] = ContextVar(
    "vimi_current_home_timeline_seeds",
    default=(),
)


class HomeTimelineRetrievalV3ScoutActivities(RetrievalV3ScoutActivities):
    """Inject bounded OAuth timeline seeds into the normal V3 ranking pipeline."""

    @activity.defn(name="execute_scout_task")
    async def execute_scout_task(
        self,
        workflow_input: ScoutWorkflowInput,
    ) -> ScoutRunResult:
        seed_token = _CURRENT_HOME_TIMELINE_SEEDS.set(workflow_input.seed_candidates)
        try:
            # PersonalizedScoutActivities owns the personalization context around
            # this call, so timeline seeds receive the same lexical + E5 taste,
            # visual/OCR, short-video filtering, dedup and V3 spam ranking as
            # Search API candidates. No OAuth credential crosses this boundary.
            return await super().execute_scout_task(workflow_input)
        finally:
            _CURRENT_HOME_TIMELINE_SEEDS.reset(seed_token)

    async def _rank_relevant_pool(
        self,
        query_variants: tuple[str, ...],
        preferred_languages: tuple[str, ...],
        discovered: list[CandidateContent],
    ) -> tuple[CandidateContent, ...]:
        _merge_home_timeline_seeds(discovered, _CURRENT_HOME_TIMELINE_SEEDS.get())
        return await super()._rank_relevant_pool(
            query_variants,
            preferred_languages,
            discovered,
        )


def _merge_home_timeline_seeds(
    discovered: list[CandidateContent],
    seeds: tuple[CandidateContent, ...],
) -> None:
    if not seeds:
        return
    seen = {(candidate.source, candidate.source_id) for candidate in discovered}
    for seed in seeds:
        key = (seed.source, seed.source_id)
        if key in seen:
            continue
        seen.add(key)
        discovered.append(seed)
