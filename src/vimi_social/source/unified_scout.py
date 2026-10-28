from collections.abc import AsyncIterator, Callable
from dataclasses import replace
from uuid import uuid4

from sqlalchemy.orm import Session
from temporalio import activity

from vimi_social.db.tenant import tenant_transaction
from vimi_social.domain.interest import UserInterestProfile
from vimi_social.domain.source import (
    CandidateContent,
    ScoutRefillContinuationState,
    ScoutRunResult,
    ScoutSearchRequest,
    ScoutWorkflowInput,
    SourceTask,
    SourceTaskState,
)
from vimi_social.source.activities import ScoutActivities
from vimi_social.source.connectors import (
    SourceConnectorRateLimited,
    SourceConnectorRegistry,
    SourceConnectorRejected,
    SourceConnectorUnavailable,
    SourceSearchCandidates,
)
from vimi_social.source.interest_profile import (
    apply_interest_profile,
    build_interest_summary,
    build_personalized_retrieval_terms,
)
from vimi_social.source.interest_repository import UserInterestProfileRepository
from vimi_social.source.ocr import PreviewOcrExtractor, PreviewOcrUnavailable
from vimi_social.source.query_planner import (
    MultilingualQueryPlanner,
    ScoutQueryPlan,
    ScoutQueryRound,
)
from vimi_social.source.repository import SourceTaskRepository
from vimi_social.source.scout_attempts import ScoutAttemptStore
from vimi_social.source.semantic import (
    SemanticRelevanceScorer,
    SemanticRelevanceUnavailable,
)
from vimi_social.source.unified_ranking import (
    calibrate_e5,
    candidate_key,
    candidate_origins,
    distinct_query_token_count,
    duration_preference,
    is_preferred_long_form,
    known_short,
    lexical_relevance,
    merge_exact_candidates,
    metadata_float,
    passes_query_gate,
    prepare_search_candidate,
    prepare_timeline_seeds,
    relative_visual_scores,
    score_candidate,
)
from vimi_social.source.visual import VisualRelevanceScorer, VisualRelevanceUnavailable
from vimi_social.telegram.outgoing import TelegramMessenger
from vimi_social.usage.repository import UsageRepository

_X_MIN_PAGE_SIZE = 10
_LOCAL_AI_BATCH_LIMIT = 100
_RELEVANT_TARGET = 20
_LONG_FORM_TARGET = 3
_CONTINUATION_STATE_KEYS = (
    "retrieval_query",
    "retrieval_query_variants",
    "retrieval_relaxation_level",
    "retrieval_specificity",
    "retrieval_language_mode",
    "x_search_scope",
    "x_search_query",
    "x_next_token",
    "x_page_start_token",
    "x_continuation_generation",
)
_DEFINITIVE_NO_TIMELINE_READ_FAILURES = frozenset(
    {
        "DISABLED_BY_BUDGET",
        "NO_ACCOUNT",
        "MULTIPLE_ACCOUNTS",
        "NO_PROFILE",
        "CREDENTIAL_UNAVAILABLE",
    }
)


class UnifiedScoutActivities(ScoutActivities):
    """One initial Scout pipeline for Home Timeline + X Search.

    Home Timeline enters the pool directly before provider search. Only exact provider
    IDs are merged; similar text remains distinct. Every candidate passes one relevance
    and ranking path before one final persistence step.
    """

    def __init__(
        self,
        session_factory: Callable[[], Session],
        registry: SourceConnectorRegistry,
        messenger: TelegramMessenger | None,
        *,
        source_repository: SourceTaskRepository | None = None,
        usage_repository: UsageRepository | None = None,
        attempt_store: ScoutAttemptStore | None = None,
        query_planner: MultilingualQueryPlanner | None = None,
        semantic_scorer: SemanticRelevanceScorer | None = None,
        visual_scorer: VisualRelevanceScorer | None = None,
        preview_ocr_extractor: PreviewOcrExtractor | None = None,
        visual_relevance_weight: float = 0.15,
        preview_ocr_weight: float = 0.10,
        semantic_minimum_relevance: float = 0.18,
        retrieval_budget: int = 300,
        retrieval_round_limit: int = 30,
        preview_evidence_limit: int = 50,
        timeline_reserved_budget: int = 50,
        interest_repository: UserInterestProfileRepository | None = None,
    ) -> None:
        super().__init__(
            session_factory,
            registry,
            messenger,
            source_repository=source_repository,
            usage_repository=usage_repository,
            attempt_store=attempt_store,
            query_planner=query_planner,
            semantic_scorer=semantic_scorer,
            visual_scorer=visual_scorer,
            preview_ocr_extractor=preview_ocr_extractor,
            visual_relevance_weight=visual_relevance_weight,
            preview_ocr_weight=preview_ocr_weight,
            semantic_minimum_relevance=semantic_minimum_relevance,
            retrieval_budget=retrieval_budget,
            retrieval_round_limit=retrieval_round_limit,
            preview_evidence_limit=preview_evidence_limit,
        )
        self._timeline_reserved_budget = max(
            0,
            min(timeline_reserved_budget, self._retrieval_budget - _X_MIN_PAGE_SIZE),
        )
        self._interest_repository = interest_repository or UserInterestProfileRepository()

    @activity.defn(name="execute_scout_task")
    async def execute_scout_task(
        self,
        workflow_input: ScoutWorkflowInput,
    ) -> ScoutRunResult:
        task = self._authorized_task(workflow_input)
        try:
            connectors = self._registry.route(task.requested_sources)
        except SourceConnectorUnavailable:
            return self._fail_safe(task, "SOURCE_UNAVAILABLE", release_usage=True)

        attempt_token = uuid4()
        with self._session_factory() as session, tenant_transaction(session, task.tenant_id):
            current = self._source_repository.get_by_operation_key(session, task.operation_key)
            if current is None:
                raise RuntimeError("source task disappeared from tenant context")
            if current.state in {
                SourceTaskState.COMPLETED,
                SourceTaskState.FAILED_SAFE,
                SourceTaskState.UNKNOWN,
            }:
                return self._result_for_task(session, current)

            claim = self._attempt_store.claim(
                session,
                operation_key=task.operation_key,
                attempt_token=attempt_token,
            )
            if not claim.claimed:
                if claim.state is SourceTaskState.SCOUTING:
                    self._attempt_store.mark_ambiguous_retry(
                        session,
                        operation_key=task.operation_key,
                        retry_token=attempt_token,
                    )
                refreshed = self._source_repository.get_by_operation_key(
                    session,
                    task.operation_key,
                )
                if refreshed is None:
                    raise RuntimeError("source task disappeared from tenant context")
                return self._result_for_task(session, refreshed)
            self._usage_repository.commit(session, task.operation_key)

        plan = await self._query_planner.plan(
            task.user_intent,
            task.preferred_languages,
        )
        profile = self._load_profile(task)
        discovered = list(prepare_timeline_seeds(workflow_input.seed_candidates))
        retrieval_spent = _timeline_read_charge(
            posts_read=workflow_input.seed_posts_read,
            failure_code=workflow_input.seed_failure_code,
            reserved=self._timeline_reserved_budget,
        )
        source_failure_code: str | None = None
        latest_continuation: ScoutRefillContinuationState | None = None

        async for search_round in search_rounds(
            self._query_planner,
            plan,
            task.user_intent,
            task.preferred_languages,
            profile,
        ):
            target_met = False
            for connector in connectors:
                pagination_token: str | None = None
                continuation_generation = 0
                pages_read = 0
                round_continuation: ScoutRefillContinuationState | None = None

                while True:
                    remaining_budget = self._retrieval_budget - retrieval_spent
                    if remaining_budget < _X_MIN_PAGE_SIZE:
                        break

                    request_limit = min(remaining_budget, self._retrieval_round_limit)
                    request = ScoutSearchRequest(
                        intent=task.user_intent,
                        requested_sources=task.requested_sources,
                        preferred_languages=search_round.preferred_languages,
                        query_variants=search_round.query_variants,
                        max_results=request_limit,
                        pagination_token=pagination_token,
                    )
                    retrieval_spent += request_limit
                    try:
                        fetched = await connector.search(request)
                    except SourceConnectorRateLimited:
                        source_failure_code = "SOURCE_RATE_LIMITED"
                        break
                    except SourceConnectorRejected:
                        source_failure_code = "SOURCE_ACCESS_REJECTED"
                        break
                    except SourceConnectorUnavailable:
                        source_failure_code = "SOURCE_UNAVAILABLE"
                        if pagination_token is not None and round_continuation is not None:
                            round_continuation = retire_ambiguous_continuation(
                                round_continuation,
                                attempted_token=pagination_token,
                                continuation_generation=continuation_generation,
                            )
                            latest_continuation = round_continuation
                        break

                    pages_read += 1
                    if isinstance(fetched, SourceSearchCandidates):
                        round_continuation = capture_continuation_state(
                            fetched,
                            search_round,
                            requested_token=pagination_token,
                            continuation_generation=continuation_generation,
                            previous=round_continuation,
                        )
                        latest_continuation = round_continuation

                    prepared = tuple(
                        prepare_search_candidate(
                            candidate,
                            query_variants=search_round.query_variants,
                            preferred_languages=search_round.preferred_languages,
                            relaxation_level=search_round.relaxation_level,
                            specificity=search_round.specificity,
                            strategy=search_round.strategy,
                            continuation_generation=continuation_generation,
                        )
                        for candidate in fetched
                    )
                    discovered = list(merge_exact_candidates((*discovered, *prepared)))

                    if await self._recall_target_met(
                        plan.query_variants,
                        tuple(discovered),
                    ):
                        target_met = True
                        break
                    if retrieval_spent >= self._retrieval_budget:
                        break
                    if (
                        search_round.max_pages is not None
                        and pages_read >= search_round.max_pages
                    ):
                        break

                    next_token = (
                        fetched.next_token
                        if isinstance(fetched, SourceSearchCandidates)
                        else None
                    )
                    if next_token is None or next_token == pagination_token:
                        break
                    pagination_token = next_token
                    continuation_generation += 1

                if source_failure_code is not None or target_met:
                    break
                if retrieval_spent >= self._retrieval_budget:
                    break

            if source_failure_code is not None or target_met:
                break
            if retrieval_spent >= self._retrieval_budget:
                break

        if source_failure_code is not None and not discovered:
            return self._fail_safe(
                task,
                source_failure_code,
                attempt_token=attempt_token,
            )

        merged = merge_exact_candidates(tuple(discovered))
        curated = await self._rank_pool(plan.query_variants, merged, profile)
        curated = apply_latest_continuation_state(curated, latest_continuation)

        with self._session_factory() as session, tenant_transaction(session, task.tenant_id):
            if not self._attempt_store.lock_owned_attempt(
                session,
                operation_key=task.operation_key,
                attempt_token=attempt_token,
            ):
                refreshed = self._source_repository.get_by_operation_key(
                    session,
                    task.operation_key,
                )
                if refreshed is None:
                    raise RuntimeError("source task disappeared from tenant context")
                return self._result_for_task(session, refreshed)

            persisted = self._source_repository.replace_candidates(
                session,
                task_id=task.id,
                tenant_id=task.tenant_id,
                candidates=curated,
            )
            if not self._attempt_store.finish_owned_attempt(
                session,
                operation_key=task.operation_key,
                attempt_token=attempt_token,
                state=SourceTaskState.COMPLETED,
            ):
                raise RuntimeError("Scout attempt lost its fence while holding the task lock")

        return ScoutRunResult(
            operation_key=task.operation_key.value,
            state=SourceTaskState.COMPLETED,
            discovered_count=len(merged),
            candidate_count=len(persisted),
        )

    def _load_profile(self, task: SourceTask) -> UserInterestProfile | None:
        with self._session_factory() as session, tenant_transaction(session, task.tenant_id):
            return self._interest_repository.get(session, user_id=task.actor_user_id)

    async def _recall_target_met(
        self,
        query_variants: tuple[str, ...],
        candidates: tuple[CandidateContent, ...],
    ) -> bool:
        eligible = tuple(candidate for candidate in candidates if not known_short(candidate))
        if len(eligible) < _RELEVANT_TARGET:
            return False
        semantic_scores = await self._query_semantic_scores(query_variants, eligible)
        query_token_count = distinct_query_token_count(query_variants)
        relevant = 0
        long_form = 0
        for index, candidate in enumerate(eligible):
            semantic_raw = semantic_scores[index] if semantic_scores is not None else None
            lexical, matches = lexical_relevance(candidate, query_variants)
            if passes_query_gate(
                candidate,
                semantic_raw=semantic_raw,
                lexical=lexical,
                lexical_matches=matches,
                query_token_count=query_token_count,
                minimum_relevance=self._semantic_minimum_relevance,
            ):
                relevant += 1
                if is_preferred_long_form(candidate):
                    long_form += 1
        return relevant >= _RELEVANT_TARGET and long_form >= _LONG_FORM_TARGET

    async def _rank_pool(
        self,
        query_variants: tuple[str, ...],
        candidates: tuple[CandidateContent, ...],
        profile: UserInterestProfile | None,
    ) -> tuple[CandidateContent, ...]:
        pool = tuple(candidate for candidate in candidates if not known_short(candidate))
        if not pool:
            return ()

        semantic_scores = await self._query_semantic_scores(query_variants, pool)
        taste_scores = await self._taste_semantic_scores(profile, pool)
        query_token_count = distinct_query_token_count(query_variants)
        prelim: list[tuple[float, int, CandidateContent]] = []

        for index, candidate in enumerate(pool):
            semantic_raw = semantic_scores[index] if semantic_scores is not None else None
            lexical, lexical_matches = lexical_relevance(candidate, query_variants)
            if not passes_query_gate(
                candidate,
                semantic_raw=semantic_raw,
                lexical=lexical,
                lexical_matches=lexical_matches,
                query_token_count=query_token_count,
                minimum_relevance=self._semantic_minimum_relevance,
            ):
                continue

            enriched = apply_interest_profile(
                candidate,
                profile,
                semantic_affinity=(taste_scores[index] if taste_scores is not None else None),
            )
            score, updated = score_candidate(
                enriched,
                semantic_raw=semantic_raw,
                lexical=lexical,
                visual_relevance=None,
                ocr_relevance=None,
            )
            prelim.append((score, index, updated))

        if not prelim:
            return ()
        prelim.sort(key=lambda item: (item[0], -item[1]), reverse=True)
        evidence = tuple(item[2] for item in prelim[: self._preview_evidence_limit])

        visual_by_key: dict[tuple[str, str], float] = {}
        if self._visual_scorer is not None and evidence:
            try:
                raw_visual = await self._score_visual_candidates(query_variants, evidence)
                visual_by_key = relative_visual_scores(evidence, raw_visual)
            except VisualRelevanceUnavailable:
                visual_by_key = {}

        ocr_by_key: dict[tuple[str, str], float] = {}
        if self._preview_ocr_extractor is not None and evidence:
            try:
                texts = await self._extract_preview_ocr_texts(evidence)
                if self._semantic_scorer is not None and any(text for text in texts):
                    raw_ocr = await self._score_semantic_texts(query_variants, texts)
                    ocr_by_key = {
                        candidate_key(candidate): calibrate_e5(raw)
                        for candidate, raw in zip(evidence, raw_ocr, strict=True)
                        if raw is not None
                    }
            except (PreviewOcrUnavailable, SemanticRelevanceUnavailable):
                ocr_by_key = {}

        final: list[tuple[float, float, float, float, float, int, CandidateContent]] = []
        for _, original_index, candidate in prelim:
            semantic_raw = (
                semantic_scores[original_index]
                if semantic_scores is not None
                else None
            )
            lexical, _ = lexical_relevance(candidate, query_variants)
            key = candidate_key(candidate)
            score, updated = score_candidate(
                candidate,
                semantic_raw=semantic_raw,
                lexical=lexical,
                visual_relevance=visual_by_key.get(key),
                ocr_relevance=ocr_by_key.get(key),
                visual_weight=self._visual_relevance_weight,
                ocr_weight=self._preview_ocr_weight,
            )
            metadata = updated.connector_metadata
            final.append(
                (
                    score,
                    metadata_float(metadata, "curator_relevance_score", 0.0),
                    metadata_float(metadata, "personal_affinity_score", 0.0),
                    duration_preference(updated),
                    metadata_float(metadata, "curator_quality_score", 0.0),
                    -original_index,
                    updated,
                )
            )

        final.sort(key=lambda item: item[:6], reverse=True)
        ranked: list[CandidateContent] = []
        for rank, item in enumerate(final, start=1):
            candidate = item[6]
            metadata = dict(candidate.connector_metadata)
            metadata["curator_rank"] = rank
            metadata["scout_engine"] = "unified_v4"
            ranked.append(replace(candidate, connector_metadata=metadata))
        return tuple(ranked)

    async def _query_semantic_scores(
        self,
        query_variants: tuple[str, ...],
        candidates: tuple[CandidateContent, ...],
    ) -> tuple[float, ...] | None:
        if self._semantic_scorer is None or not candidates:
            return None
        try:
            return await self._score_semantic_candidates(query_variants, candidates)
        except SemanticRelevanceUnavailable:
            return None

    async def _taste_semantic_scores(
        self,
        profile: UserInterestProfile | None,
        candidates: tuple[CandidateContent, ...],
    ) -> tuple[float, ...] | None:
        scorer = self._semantic_scorer
        if scorer is None or profile is None or not candidates:
            return None
        summary = build_interest_summary(profile)
        if summary is None:
            return None
        scores: list[float] = []
        try:
            for start in range(0, len(candidates), _LOCAL_AI_BATCH_LIMIT):
                batch = candidates[start : start + _LOCAL_AI_BATCH_LIMIT]
                batch_scores = await scorer.score_candidates((summary,), batch)
                if len(batch_scores) != len(batch):
                    raise SemanticRelevanceUnavailable(
                        "taste semantic batch alignment mismatch"
                    )
                scores.extend(batch_scores)
        except SemanticRelevanceUnavailable:
            return None
        return tuple(scores)


async def search_rounds(
    planner: MultilingualQueryPlanner,
    plan: ScoutQueryPlan,
    intent: str,
    preferred_languages: tuple[str, ...],
    profile: UserInterestProfile | None,
) -> AsyncIterator[ScoutQueryRound]:
    """Preserve language-broadening rounds even when query terms are identical."""

    level = 0
    emitted: set[tuple[tuple[str, ...], tuple[str, ...]]] = set()
    async for search_round in planner.search_rounds(plan, intent, preferred_languages):
        key = round_identity(
            search_round.query_variants,
            search_round.preferred_languages,
        )
        if key in emitted:
            continue
        emitted.add(key)
        yield replace(search_round, relaxation_level=level)
        level += 1

    profile_terms = build_personalized_retrieval_terms(profile, plan.query_variants)
    if len(profile_terms) < 2:
        return
    normalized_languages = {
        language.strip().lower()
        for language in preferred_languages
        if language.strip()
    }
    english_profile = "en" in normalized_languages and all(
        term.isascii() for term in profile_terms
    )
    round_languages = ("en",) if english_profile else ()
    key = round_identity(profile_terms, round_languages)
    if key in emitted:
        return
    yield ScoutQueryRound(
        query_variants=profile_terms,
        preferred_languages=round_languages,
        relaxation_level=level,
        specificity=1 / len(profile_terms),
        strategy="profile_personalized_fallback",
        max_pages=1,
    )


def round_identity(
    query_variants: tuple[str, ...],
    preferred_languages: tuple[str, ...],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    return (
        tuple(value.casefold() for value in query_variants),
        tuple(value.strip().lower() for value in preferred_languages if value.strip()),
    )


def capture_continuation_state(
    candidates: SourceSearchCandidates,
    search_round: ScoutQueryRound,
    *,
    requested_token: str | None,
    continuation_generation: int,
    previous: ScoutRefillContinuationState | None,
) -> ScoutRefillContinuationState:
    search_scope = previous.search_scope if previous is not None else None
    search_query = previous.search_query if previous is not None else None
    if candidates:
        metadata = candidates[0].connector_metadata
        raw_scope = metadata.get("x_search_scope")
        raw_query = metadata.get("x_search_query")
        if isinstance(raw_scope, str) and raw_scope:
            search_scope = raw_scope
        if isinstance(raw_query, str) and raw_query:
            search_query = raw_query

    return ScoutRefillContinuationState(
        retrieval_query=search_round.query_variants[0],
        retrieval_query_variants=search_round.query_variants,
        retrieval_relaxation_level=search_round.relaxation_level,
        retrieval_specificity=search_round.specificity,
        retrieval_language_mode="+".join(search_round.preferred_languages),
        continuation_generation=continuation_generation,
        page_start_token=requested_token,
        next_token=candidates.next_token,
        search_scope=search_scope,
        search_query=search_query,
    )


def retire_ambiguous_continuation(
    state: ScoutRefillContinuationState,
    *,
    attempted_token: str,
    continuation_generation: int,
) -> ScoutRefillContinuationState:
    return replace(
        state,
        page_start_token=attempted_token,
        next_token=None,
        continuation_generation=continuation_generation,
    )


def apply_latest_continuation_state(
    candidates: tuple[CandidateContent, ...],
    state: ScoutRefillContinuationState | None,
) -> tuple[CandidateContent, ...]:
    if state is None or not candidates:
        return candidates

    sanitized: list[CandidateContent] = []
    matching_indices: list[int] = []
    search_indices: list[int] = []
    for index, candidate in enumerate(candidates):
        metadata = dict(candidate.connector_metadata)
        # A single latest page state owns continuation for the entire persisted pool.
        # Remove every older cursor first so no stale paid cursor can be rediscovered.
        metadata.pop("x_next_token", None)
        metadata.pop("x_page_start_token", None)
        if (
            metadata.get("retrieval_relaxation_level")
            == state.retrieval_relaxation_level
            and metadata.get("retrieval_language_mode")
            == state.retrieval_language_mode
        ):
            matching_indices.append(index)
        if "search" in candidate_origins(candidate):
            search_indices.append(index)
        sanitized.append(replace(candidate, connector_metadata=metadata))

    carrier_index = (
        matching_indices[0]
        if matching_indices
        else search_indices[0]
        if search_indices
        else 0
    )
    carrier = sanitized[carrier_index]
    metadata = dict(carrier.connector_metadata)
    for key in _CONTINUATION_STATE_KEYS:
        metadata.pop(key, None)
    metadata.update(_continuation_metadata(state))
    sanitized[carrier_index] = replace(carrier, connector_metadata=metadata)
    return tuple(sanitized)


def _continuation_metadata(state: ScoutRefillContinuationState) -> dict[str, object]:
    metadata: dict[str, object] = {
        "retrieval_query": state.retrieval_query,
        "retrieval_query_variants": list(state.retrieval_query_variants),
        "retrieval_relaxation_level": state.retrieval_relaxation_level,
        "retrieval_specificity": state.retrieval_specificity,
        "retrieval_language_mode": state.retrieval_language_mode,
        "x_continuation_generation": state.continuation_generation,
    }
    if state.search_scope is not None:
        metadata["x_search_scope"] = state.search_scope
    if state.search_query is not None:
        metadata["x_search_query"] = state.search_query
    if state.page_start_token is not None:
        metadata["x_page_start_token"] = state.page_start_token
    if state.next_token is not None:
        metadata["x_next_token"] = state.next_token
    return metadata


def _timeline_read_charge(*, posts_read: int, failure_code: str | None, reserved: int) -> int:
    if posts_read > 0:
        return min(max(0, posts_read), reserved)
    if failure_code in _DEFINITIVE_NO_TIMELINE_READ_FAILURES:
        return 0
    return reserved
