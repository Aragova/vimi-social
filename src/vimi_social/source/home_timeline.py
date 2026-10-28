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
_CURRENT_HOME_TIMELINE_POSTS_READ: ContextVar[int] = ContextVar(
    "vimi_current_home_timeline_posts_read",
    default=0,
)
_CURRENT_HOME_TIMELINE_FAILURE_CODE: ContextVar[str | None] = ContextVar(
    "vimi_current_home_timeline_failure_code",
    default=None,
)
_X_MIN_PAGE_SIZE = 10
_DEFINITIVE_NO_TIMELINE_READ_FAILURES = frozenset(
    {
        "DISABLED_BY_BUDGET",
        "NO_ACCOUNT",
        "MULTIPLE_ACCOUNTS",
        "NO_PROFILE",
        "CREDENTIAL_UNAVAILABLE",
    }
)


class HomeTimelineSeedRegistry(SourceConnectorRegistry):
    """Merge bounded OAuth timeline seeds into the first provider result."""

    def __init__(
        self,
        delegate: SourceConnectorRegistry,
        *,
        seed_getter: Callable[[], tuple[CandidateContent, ...]] | None = None,
        provider_read_budget: int | None = None,
        timeline_reserved_budget: int = 0,
        seed_posts_read_getter: Callable[[], int] | None = None,
        seed_failure_code_getter: Callable[[], str | None] | None = None,
    ) -> None:
        self._delegate = delegate
        self._seed_getter = seed_getter or _CURRENT_HOME_TIMELINE_SEEDS.get
        self._provider_read_budget = (
            None if provider_read_budget is None else max(0, provider_read_budget)
        )
        self._timeline_reserved_budget = max(0, timeline_reserved_budget)
        self._seed_posts_read_getter = (
            seed_posts_read_getter or _CURRENT_HOME_TIMELINE_POSTS_READ.get
        )
        self._seed_failure_code_getter = (
            seed_failure_code_getter or _CURRENT_HOME_TIMELINE_FAILURE_CODE.get
        )

    def route(self, requested_sources: tuple[str, ...]) -> tuple[SourceConnector, ...]:
        provider_limit = self._provider_read_budget
        if provider_limit is not None and self._timeline_reserved_budget:
            provider_limit += _reclaimed_timeline_budget(
                reserved=self._timeline_reserved_budget,
                posts_read=self._seed_posts_read_getter(),
                failure_code=self._seed_failure_code_getter(),
            )
        shared_budget = (
            None if provider_limit is None else _ProviderReadBudget(provider_limit)
        )
        return tuple(
            _HomeTimelineSeedConnector(
                connector,
                self._seed_getter,
                provider_read_budget=shared_budget,
            )
            for connector in self._delegate.route(requested_sources)
        )


class _ProviderReadBudget:
    def __init__(self, limit: int) -> None:
        self._remaining = max(0, limit)

    def constrain(self, request: ScoutSearchRequest) -> ScoutSearchRequest | None:
        if self._remaining < _X_MIN_PAGE_SIZE:
            return None
        allowed = min(request.max_results, self._remaining)
        if allowed < _X_MIN_PAGE_SIZE:
            return None
        self._remaining -= allowed
        if allowed == request.max_results:
            return request
        return replace(request, max_results=allowed)


class _HomeTimelineSeedConnector:
    def __init__(
        self,
        delegate: SourceConnector,
        seed_getter: Callable[[], tuple[CandidateContent, ...]],
        *,
        provider_read_budget: _ProviderReadBudget | None = None,
    ) -> None:
        self._delegate = delegate
        self._seed_getter = seed_getter
        self._provider_read_budget = provider_read_budget
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

        seeds: tuple[CandidateContent, ...] = ()
        if self._seed_merge_pending:
            self._seed_merge_pending = False
            seeds = _prepare_home_timeline_seeds(self._seed_getter())

        provider_request = request
        if self._provider_read_budget is not None:
            constrained = self._provider_read_budget.constrain(request)
            if constrained is None:
                return seeds
            provider_request = constrained

        try:
            provider_result = await self._delegate.search(provider_request)
        except (
            SourceConnectorRateLimited,
            SourceConnectorRejected,
            SourceConnectorUnavailable,
        ) as exc:
            if not seeds:
                raise
            # Keep the independent timeline source usable when Search API fails.
            # Re-raise the same provider failure on the next round without making
            # another paid provider request so the base activity stops retrieval
            # while still curating and persisting the already-fetched seeds.
            self._deferred_failure = exc
            return seeds

        if not seeds:
            return provider_result
        return _merge_provider_result(provider_result, seeds)


class HomeTimelineRetrievalV3ScoutActivities(RetrievalV3ScoutActivities):
    """Inject bounded OAuth timeline seeds into the normal V3 ranking pipeline."""

    @activity.defn(name="execute_scout_task")
    async def execute_scout_task(
        self,
        workflow_input: ScoutWorkflowInput,
    ) -> ScoutRunResult:
        seed_token = _CURRENT_HOME_TIMELINE_SEEDS.set(workflow_input.seed_candidates)
        posts_read_token = _CURRENT_HOME_TIMELINE_POSTS_READ.set(
            workflow_input.seed_posts_read
        )
        failure_code_token = _CURRENT_HOME_TIMELINE_FAILURE_CODE.set(
            workflow_input.seed_failure_code
        )
        try:
            # PersonalizedScoutActivities owns the personalization context around
            # this call, so timeline seeds receive the same lexical + E5 taste,
            # visual/OCR, short-video filtering, dedup and V3 spam ranking as
            # Search API candidates. No OAuth credential crosses this boundary.
            return await super().execute_scout_task(workflow_input)
        finally:
            _CURRENT_HOME_TIMELINE_FAILURE_CODE.reset(failure_code_token)
            _CURRENT_HOME_TIMELINE_POSTS_READ.reset(posts_read_token)
            _CURRENT_HOME_TIMELINE_SEEDS.reset(seed_token)


def _reclaimed_timeline_budget(
    *,
    reserved: int,
    posts_read: int,
    failure_code: str | None,
) -> int:
    reserved = max(0, reserved)
    if reserved == 0:
        return 0
    if posts_read > 0:
        charged = min(reserved, posts_read)
    elif failure_code in _DEFINITIVE_NO_TIMELINE_READ_FAILURES:
        charged = 0
    else:
        # A successful empty page or provider/auth failure is ambiguous from a
        # billing perspective. Keep the full reserve instead of risking a total
        # read count above the configured budget.
        charged = reserved
    return reserved - charged


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
    # Keep provider ordering so continuation metadata remains discoverable from the
    # first result, but let an exact Home Timeline duplicate replace the provider
    # copy in-place. ScoutActivities deduplicates by (source, source_id) with the first
    # copy winning; without this replacement the personalized timeline provenance is
    # discarded before the timeline-specific relevance gate can run.
    seeds_by_key = {(seed.source, seed.source_id): seed for seed in seeds}
    provider_keys: set[tuple[str, str]] = set()
    merged_provider: list[CandidateContent] = []
    for candidate in provider_result:
        key = (candidate.source, candidate.source_id)
        provider_keys.add(key)
        seed = seeds_by_key.get(key)
        if seed is None:
            merged_provider.append(candidate)
            continue

        metadata = dict(candidate.connector_metadata)
        metadata.update(seed.connector_metadata)
        merged_provider.append(replace(seed, connector_metadata=metadata))

    combined = (
        *merged_provider,
        *(seed for seed in seeds if (seed.source, seed.source_id) not in provider_keys),
    )
    if isinstance(provider_result, SourceSearchCandidates):
        return SourceSearchCandidates(combined, next_token=provider_result.next_token)
    return combined
