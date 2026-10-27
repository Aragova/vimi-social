from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import replace

from temporalio import activity

from vimi_social.domain.source import (
    CandidateContent,
    ScoutRunResult,
    ScoutSearchRequest,
    ScoutWorkflowInput,
)
from vimi_social.source.connectors import (
    SourceConnector,
    SourceConnectorRateLimited,
    SourceConnectorRegistry,
    SourceConnectorRejected,
    SourceConnectorUnavailable,
    SourceSearchCandidates,
)
from vimi_social.source.retrieval_v3 import RetrievalV3ScoutActivities

_CURRENT_HOME_TIMELINE_SEEDS: ContextVar[tuple[CandidateContent, ...]] = ContextVar(
    "vimi_current_home_timeline_seeds",
    default=(),
)


class HomeTimelineSeedRegistry(SourceConnectorRegistry):
    """Merge bounded OAuth timeline seeds into the first provider result."""

    def __init__(
        self,
        delegate: SourceConnectorRegistry,
        *,
        seed_getter: Callable[[], tuple[CandidateContent, ...]] | None = None,
    ) -> None:
        self._delegate = delegate
        self._seed_getter = seed_getter or _CURRENT_HOME_TIMELINE_SEEDS.get

    def route(self, requested_sources: tuple[str, ...]) -> tuple[SourceConnector, ...]:
        return tuple(
            _HomeTimelineSeedConnector(connector, self._seed_getter)
            for connector in self._delegate.route(requested_sources)
        )


class _HomeTimelineSeedConnector:
    def __init__(
        self,
        delegate: SourceConnector,
        seed_getter: Callable[[], tuple[CandidateContent, ...]],
    ) -> None:
        self._delegate = delegate
        self._seed_getter = seed_getter
        self._seed_merge_pending = True
        self._deferred_failure: (
            SourceConnectorRateLimited
            | SourceConnectorRejected
            | SourceConnectorUnavailable
            | None
        ) = None

    @property
    def source_name(self) -> str:
        return self._delegate.source_name

    async def search(self, request: ScoutSearchRequest) -> tuple[CandidateContent, ...]:
        if self._deferred_failure is not None:
            failure = self._deferred_failure
            self._deferred_failure = None
            raise failure

        if not self._seed_merge_pending:
            return await self._delegate.search(request)

        self._seed_merge_pending = False
        seeds = _prepare_home_timeline_seeds(self._seed_getter())
        if not seeds:
            return await self._delegate.search(request)

        try:
            provider_result = await self._delegate.search(request)
        except (
            SourceConnectorRateLimited,
            SourceConnectorRejected,
            SourceConnectorUnavailable,
        ) as exc:
            # Keep the independent timeline source usable when Search API fails.
            # Re-raise the same provider failure on the next round without making
            # another paid provider request so the base activity stops retrieval
            # while still curating and persisting the already-fetched seeds.
            self._deferred_failure = exc
            return seeds

        return _merge_provider_result(provider_result, seeds)


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


def _prepare_home_timeline_seeds(
    seeds: tuple[CandidateContent, ...],
) -> tuple[CandidateContent, ...]:
    prepared: list[CandidateContent] = []
    for seed in seeds:
        metadata = dict(seed.connector_metadata)
        # Home Timeline is personalized but not constrained by the active search
        # intent. Mark it as maximally broad so CandidateCurator keeps the normal
        # absolute relevance gate active even when semantic scoring is unavailable.
        metadata["retrieval_specificity"] = 0.0
        metadata["retrieval_strategy"] = "home_timeline_personalized_seed"
        prepared.append(replace(seed, connector_metadata=metadata))
    return tuple(prepared)


def _merge_provider_result(
    provider_result: tuple[CandidateContent, ...],
    seeds: tuple[CandidateContent, ...],
) -> tuple[CandidateContent, ...]:
    combined = (*seeds, *provider_result)
    if isinstance(provider_result, SourceSearchCandidates):
        return SourceSearchCandidates(combined, next_token=provider_result.next_token)
    return combined
