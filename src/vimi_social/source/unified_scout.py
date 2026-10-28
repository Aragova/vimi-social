import math
import re
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import replace
from uuid import uuid4

from sqlalchemy.orm import Session
from temporalio import activity

from vimi_social.db.tenant import tenant_transaction
from vimi_social.domain.interest import UserInterestProfile
from vimi_social.domain.source import (
    CandidateContent,
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
from vimi_social.source.visual import VisualRelevanceScorer, VisualRelevanceUnavailable
from vimi_social.source.ocr import PreviewOcrExtractor, PreviewOcrUnavailable
from vimi_social.telegram.outgoing import TelegramMessenger
from vimi_social.usage.repository import UsageRepository

_TOKEN = re.compile(r"[^\W_]+(?:[-'][^\W_]+)*", re.UNICODE)
_URL = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
_LINK_FARM = re.compile(
    r"\b(?:best|top)\b.{0,80}\b(?:sites?|websites?|directories|directory)\b",
    re.IGNORECASE,
)
_PROMO = re.compile(
    r"\b(?:click\s+here|visit\s+(?:our|the)|free\s+links?|link\s+in\s+bio)\b",
    re.IGNORECASE,
)

_X_MIN_PAGE_SIZE = 10
_LOCAL_AI_BATCH_LIMIT = 100
_RELEVANT_TARGET = 20
_LONG_FORM_TARGET = 3
_LONG_FORM_MIN_MS = 5 * 60 * 1000
_LONG_FORM_MAX_MS = 30 * 60 * 1000
_TIMELINE_SEMANTIC_MINIMUM = 0.84
_TIMELINE_LONG_FORM_SEMANTIC_MINIMUM = 0.81
_TIMELINE_LEXICAL_MIN_MATCHES = 2
_E5_FLOOR = 0.70
_PERSONAL_AFFINITY_WEIGHT = 0.10
_DURATION_WEIGHT = 0.15
_QUALITY_WEIGHT = 0.03
_SPAM_WEIGHT = 0.35
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
    """Single-pass Scout pipeline for Search API + personalized Home Timeline.

    The initial Scout path deliberately avoids the old wrapper stack. Timeline seeds are
    inserted into the discovered pool directly, Search API results are merged by exact
    provider post ID only, and every candidate passes one relevance/ranking pipeline
    before one final persistence step. Text-near-duplicate suppression is intentionally
    absent: distinct provider posts remain distinct even when their captions are similar.
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

        # Timeline is a first-class source, not a registry side effect. This guarantees
        # every successfully fetched seed enters the same pool even when Search API
        # fails, returns no overlap, or stops early.
        discovered = list(_prepare_timeline_seeds(workflow_input.seed_candidates))
        retrieval_spent = _timeline_read_charge(
            posts_read=workflow_input.seed_posts_read,
            failure_code=workflow_input.seed_failure_code,
            reserved=self._timeline_reserved_budget,
        )
        source_failure_code: str | None = None

        async for search_round in _search_rounds(
            self._query_planner,
            plan,
            task.user_intent,
            task.preferred_languages,
            profile,
        ):
            target_met = False
            for connector in connectors:
                pagination_token: str | None = None
                pages_read = 0
                continuation_generation = 0
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
                    # Reserve before provider I/O. An ambiguous provider failure may have
                    # consumed the read even when its response never reached ViMi.
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
                        break

                    pages_read += 1
                    prepared = tuple(
                        _prepare_search_candidate(
                            candidate,
                            search_round,
                            continuation_generation=continuation_generation,
                        )
                        for candidate in fetched
                    )
                    discovered = list(_merge_exact_candidates((*discovered, *prepared)))

                    if await self._recall_target_met(
                        plan.query_variants,
                        tuple(discovered),
                    ):
                        target_met = True
                        break
                    if retrieval_spent >= self._retrieval_budget:
                        break
                    if search_round.max_pages is not None and pages_read >= search_round.max_pages:
                        break

                    next_token = fetched.next_token if isinstance(fetched, SourceSearchCandidates) else None
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

        merged = _merge_exact_candidates(tuple(discovered))
        curated = await self._rank_pool(
            plan.query_variants,
            task.preferred_languages,
            merged,
            profile,
        )

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
        eligible = tuple(candidate for candidate in candidates if not _known_short(candidate))
        if len(eligible) < _RELEVANT_TARGET:
            return False
        semantic_scores = await self._query_semantic_scores(query_variants, eligible)
        relevant = 0
        long_form = 0
        for index, candidate in enumerate(eligible):
            semantic_raw = semantic_scores[index] if semantic_scores is not None else None
            lexical, matches = _lexical_relevance(candidate, query_variants)
            if _passes_query_gate(
                candidate,
                semantic_raw=semantic_raw,
                lexical=lexical,
                lexical_matches=matches,
                minimum_relevance=self._semantic_minimum_relevance,
            ):
                relevant += 1
                if _is_preferred_long_form(candidate):
                    long_form += 1
        return relevant >= _RELEVANT_TARGET and long_form >= _LONG_FORM_TARGET

    async def _rank_pool(
        self,
        query_variants: tuple[str, ...],
        preferred_languages: tuple[str, ...],
        candidates: tuple[CandidateContent, ...],
        profile: UserInterestProfile | None,
    ) -> tuple[CandidateContent, ...]:
        del preferred_languages
        pool = tuple(candidate for candidate in candidates if not _known_short(candidate))
        if not pool:
            return ()

        semantic_scores = await self._query_semantic_scores(query_variants, pool)
        taste_scores = await self._taste_semantic_scores(profile, pool)

        prelim: list[tuple[float, int, CandidateContent]] = []
        for index, candidate in enumerate(pool):
            semantic_raw = semantic_scores[index] if semantic_scores is not None else None
            lexical, lexical_matches = _lexical_relevance(candidate, query_variants)
            if not _passes_query_gate(
                candidate,
                semantic_raw=semantic_raw,
                lexical=lexical,
                lexical_matches=lexical_matches,
                minimum_relevance=self._semantic_minimum_relevance,
            ):
                continue

            enriched = apply_interest_profile(
                candidate,
                profile,
                semantic_affinity=(taste_scores[index] if taste_scores is not None else None),
            )
            scored = _score_candidate(
                enriched,
                semantic_raw=semantic_raw,
                lexical=lexical,
                visual_relevance=None,
                ocr_relevance=None,
            )
            prelim.append((scored[0], index, scored[1]))

        if not prelim:
            return ()
        prelim.sort(key=lambda item: (item[0], -item[1]), reverse=True)
        evidence = tuple(item[2] for item in prelim[: self._preview_evidence_limit])

        visual_by_key: dict[tuple[str, str], float] = {}
        if self._visual_scorer is not None and evidence:
            try:
                raw_visual = await self._score_visual_candidates(query_variants, evidence)
                visual_by_key = _relative_visual_scores(evidence, raw_visual)
            except VisualRelevanceUnavailable:
                visual_by_key = {}

        ocr_by_key: dict[tuple[str, str], float] = {}
        if self._preview_ocr_extractor is not None and evidence:
            try:
                texts = await self._extract_preview_ocr_texts(evidence)
                if self._semantic_scorer is not None and any(text for text in texts):
                    raw_ocr = await self._score_semantic_texts(query_variants, texts)
                    ocr_by_key = {
                        _candidate_key(candidate): _calibrate_e5(raw)
                        for candidate, raw in zip(evidence, raw_ocr, strict=True)
                        if raw is not None
                    }
            except (PreviewOcrUnavailable, SemanticRelevanceUnavailable):
                ocr_by_key = {}

        final: list[tuple[float, float, float, float, float, int, CandidateContent]] = []
        for _, original_index, candidate in prelim:
            semantic_raw = semantic_scores[original_index] if semantic_scores is not None else None
            lexical, _ = _lexical_relevance(candidate, query_variants)
            key = _candidate_key(candidate)
            score, updated = _score_candidate(
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
                    _metadata_float(metadata, "curator_relevance_score", 0.0),
                    _metadata_float(metadata, "personal_affinity_score", 0.0),
                    _duration_preference(updated),
                    _metadata_float(metadata, "curator_quality_score", 0.0),
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
                    raise SemanticRelevanceUnavailable("taste semantic batch alignment mismatch")
                scores.extend(batch_scores)
        except SemanticRelevanceUnavailable:
            return None
        return tuple(scores)


async def _search_rounds(
    planner: MultilingualQueryPlanner,
    plan: ScoutQueryPlan,
    intent: str,
    preferred_languages: tuple[str, ...],
    profile: UserInterestProfile | None,
) -> AsyncIterator[ScoutQueryRound]:
    """Base OR recall first; profile-guided recall is only a final bounded fallback."""

    level = 0
    emitted: set[tuple[str, ...]] = set()
    async for search_round in planner.search_rounds(plan, intent, preferred_languages):
        key = tuple(value.casefold() for value in search_round.query_variants)
        if key in emitted:
            continue
        emitted.add(key)
        yield replace(search_round, relaxation_level=level)
        level += 1

    profile_terms = build_personalized_retrieval_terms(profile, plan.query_variants)
    if len(profile_terms) >= 2:
        key = tuple(value.casefold() for value in profile_terms)
        if key not in emitted:
            normalized_languages = {
                language.strip().lower()
                for language in preferred_languages
                if language.strip()
            }
            yield ScoutQueryRound(
                query_variants=profile_terms,
                preferred_languages=(
                    ("en",)
                    if "en" in normalized_languages and all(term.isascii() for term in profile_terms)
                    else ()
                ),
                relaxation_level=level,
                specificity=1 / len(profile_terms),
                strategy="profile_personalized_fallback",
                max_pages=1,
            )


def _prepare_timeline_seeds(
    seeds: tuple[CandidateContent, ...],
) -> tuple[CandidateContent, ...]:
    prepared: list[CandidateContent] = []
    for seed in seeds:
        metadata = dict(seed.connector_metadata)
        metadata["x_candidate_origin"] = "home_timeline"
        metadata["x_candidate_origins"] = ["home_timeline"]
        metadata["retrieval_strategy"] = "home_timeline"
        prepared.append(replace(seed, connector_metadata=metadata))
    return tuple(prepared)


def _prepare_search_candidate(
    candidate: CandidateContent,
    search_round: ScoutQueryRound,
    *,
    continuation_generation: int,
) -> CandidateContent:
    metadata = dict(candidate.connector_metadata)
    metadata["x_candidate_origin"] = "search"
    metadata["x_candidate_origins"] = ["search"]
    metadata["retrieval_query"] = search_round.query_variants[0]
    metadata["retrieval_query_variants"] = list(search_round.query_variants)
    metadata["retrieval_relaxation_level"] = search_round.relaxation_level
    metadata["retrieval_specificity"] = search_round.specificity
    metadata["retrieval_language_mode"] = "+".join(search_round.preferred_languages)
    metadata["retrieval_strategy"] = search_round.strategy
    metadata["x_continuation_generation"] = continuation_generation
    return replace(candidate, connector_metadata=metadata)


def _merge_exact_candidates(
    candidates: tuple[CandidateContent, ...],
) -> tuple[CandidateContent, ...]:
    """Merge only identical provider post IDs; never suppress text-near-duplicates."""

    result: list[CandidateContent] = []
    positions: dict[tuple[str, str], int] = {}
    for candidate in candidates:
        key = _candidate_key(candidate)
        position = positions.get(key)
        if position is None:
            positions[key] = len(result)
            result.append(candidate)
            continue
        result[position] = _merge_exact_pair(result[position], candidate)
    return tuple(result)


def _merge_exact_pair(left: CandidateContent, right: CandidateContent) -> CandidateContent:
    left_origins = _candidate_origins(left)
    right_origins = _candidate_origins(right)
    origins = tuple(dict.fromkeys((*left_origins, *right_origins)))

    # Prefer the richer payload, but merge metadata from both. Search continuation state
    # survives while Home Timeline provenance remains explicit for relevance gating.
    if _payload_richness(right) > _payload_richness(left):
        winner, other = right, left
    else:
        winner, other = left, right
    metadata = dict(other.connector_metadata)
    metadata.update(winner.connector_metadata)

    search_copy = right if "search" in right_origins else left if "search" in left_origins else None
    if search_copy is not None:
        for key, value in search_copy.connector_metadata.items():
            if key.startswith("x_") or key.startswith("retrieval_"):
                metadata[key] = value

    metadata["x_candidate_origins"] = list(origins)
    metadata["x_candidate_origin"] = (
        "home_timeline" if "home_timeline" in origins else origins[0] if origins else "search"
    )
    return replace(winner, connector_metadata=metadata)


def _candidate_origins(candidate: CandidateContent) -> tuple[str, ...]:
    raw = candidate.connector_metadata.get("x_candidate_origins")
    if isinstance(raw, list | tuple):
        values = tuple(value for value in raw if isinstance(value, str) and value)
        if values:
            return values
    origin = candidate.connector_metadata.get("x_candidate_origin")
    if isinstance(origin, str) and origin:
        return (origin,)
    return ()


def _payload_richness(candidate: CandidateContent) -> tuple[int, int, int, int]:
    duration = candidate.duration_ms or 0
    text_length = len(candidate.caption or candidate.title or "")
    engagement = sum(max(0, int(value)) for value in candidate.engagement.values())
    dimensions = int(candidate.width is not None and candidate.height is not None)
    return (int(duration > 0), duration, text_length + dimensions, engagement)


def _timeline_read_charge(*, posts_read: int, failure_code: str | None, reserved: int) -> int:
    if posts_read > 0:
        return min(max(0, posts_read), reserved)
    if failure_code in _DEFINITIVE_NO_TIMELINE_READ_FAILURES:
        return 0
    return reserved


def _known_short(candidate: CandidateContent) -> bool:
    return (
        candidate.media_type == "video"
        and candidate.duration_ms is not None
        and 0 < candidate.duration_ms < 60_000
    )


def _is_preferred_long_form(candidate: CandidateContent) -> bool:
    duration = candidate.duration_ms
    return duration is not None and _LONG_FORM_MIN_MS <= duration <= _LONG_FORM_MAX_MS


def _passes_query_gate(
    candidate: CandidateContent,
    *,
    semantic_raw: float | None,
    lexical: float,
    lexical_matches: int,
    minimum_relevance: float,
) -> bool:
    if candidate.connector_metadata.get("x_candidate_origin") == "home_timeline":
        semantic_minimum = (
            _TIMELINE_LONG_FORM_SEMANTIC_MINIMUM
            if _is_preferred_long_form(candidate)
            else _TIMELINE_SEMANTIC_MINIMUM
        )
        semantic_ok = semantic_raw is not None and semantic_raw >= semantic_minimum
        lexical_ok = lexical_matches >= _TIMELINE_LEXICAL_MIN_MATCHES
        return semantic_ok or lexical_ok

    if semantic_raw is None:
        return lexical >= minimum_relevance
    text_gate = (0.35 * lexical) + (0.65 * _calibrate_e5(semantic_raw))
    return text_gate >= minimum_relevance


def _score_candidate(
    candidate: CandidateContent,
    *,
    semantic_raw: float | None,
    lexical: float,
    visual_relevance: float | None,
    ocr_relevance: float | None,
    visual_weight: float = 0.15,
    ocr_weight: float = 0.10,
) -> tuple[float, CandidateContent]:
    semantic = _calibrate_e5(semantic_raw) if semantic_raw is not None else None
    text_relevance = lexical if semantic is None else (0.25 * lexical) + (0.75 * semantic)
    relevance = text_relevance
    if visual_relevance is not None:
        weight = max(0.0, min(0.40, visual_weight))
        relevance = ((1.0 - weight) * relevance) + (weight * visual_relevance)
    if ocr_relevance is not None:
        weight = max(0.0, min(0.25, ocr_weight))
        relevance = ((1.0 - weight) * relevance) + (weight * ocr_relevance)

    metadata = dict(candidate.connector_metadata)
    affinity = _metadata_float(metadata, "personal_affinity_score", 0.0)
    duration = _duration_preference(candidate)
    quality = _quality_score(candidate)
    spam = _spam_penalty(candidate)
    final = round(
        relevance
        + (_PERSONAL_AFFINITY_WEIGHT * affinity)
        + (_DURATION_WEIGHT * duration)
        + (_QUALITY_WEIGHT * quality)
        - (_SPAM_WEIGHT * spam),
        6,
    )

    metadata["curator_lexical_relevance_score"] = round(lexical, 6)
    if semantic_raw is not None and semantic is not None:
        metadata["curator_semantic_raw_score"] = round(semantic_raw, 6)
        metadata["curator_semantic_relevance_score"] = round(semantic, 6)
    if visual_relevance is not None:
        metadata["curator_visual_relevance_score"] = round(visual_relevance, 6)
    if ocr_relevance is not None:
        metadata["curator_preview_ocr_relevance_score"] = round(ocr_relevance, 6)
    metadata["curator_relevance_score"] = round(relevance, 6)
    metadata["curator_personalized_score"] = round(
        relevance + (_PERSONAL_AFFINITY_WEIGHT * affinity),
        6,
    )
    metadata["curator_duration_preference_score"] = duration
    metadata["curator_quality_score"] = quality
    metadata["curator_spam_penalty_score"] = spam
    metadata["curator_v3_score"] = final
    metadata["curator_ranking_score"] = final
    return final, replace(candidate, connector_metadata=metadata)


def _lexical_relevance(
    candidate: CandidateContent,
    query_variants: tuple[str, ...],
) -> tuple[float, int]:
    searchable = " ".join(
        part
        for part in (candidate.title or "", candidate.caption or "", " ".join(candidate.tags))
        if part
    ).casefold()
    candidate_tokens = tuple(token.casefold() for token in _TOKEN.findall(searchable))
    if not candidate_tokens:
        return 0.0, 0

    best_score = 0.0
    best_matches = 0
    for variant in query_variants:
        query_tokens = tuple(
            dict.fromkeys(token.casefold() for token in _TOKEN.findall(variant) if token)
        )
        if not query_tokens:
            continue
        matches = sum(
            1
            for query_token in query_tokens
            if any(_token_matches(query_token, candidate_token) for candidate_token in candidate_tokens)
        )
        coverage = matches / len(query_tokens)
        phrase_bonus = 0.10 if len(query_tokens) > 1 and variant.casefold() in searchable else 0.0
        score = min(1.0, coverage + phrase_bonus)
        if (score, matches) > (best_score, best_matches):
            best_score, best_matches = score, matches
    return round(best_score, 6), best_matches


def _token_matches(query: str, candidate: str) -> bool:
    if query == candidate:
        return True
    if len(query) >= 4 and len(candidate) >= 4:
        return query.startswith(candidate) or candidate.startswith(query)
    return False


def _calibrate_e5(value: float) -> float:
    bounded = max(_E5_FLOOR, min(1.0, float(value)))
    return round((bounded - _E5_FLOOR) / (1.0 - _E5_FLOOR), 6)


def _relative_visual_scores(
    candidates: tuple[CandidateContent, ...],
    values: tuple[float | None, ...],
) -> dict[tuple[str, str], float]:
    distinct = sorted({value for value in values if value is not None})
    if len(distinct) < 2:
        return {}
    denominator = len(distinct) - 1
    calibration = {value: index / denominator for index, value in enumerate(distinct)}
    return {
        _candidate_key(candidate): round(calibration[value], 6)
        for candidate, value in zip(candidates, values, strict=True)
        if value is not None
    }


def _duration_preference(candidate: CandidateContent) -> float:
    duration = candidate.duration_ms
    if duration is None or duration <= 0:
        return 0.50
    if duration < 60_000:
        return 0.0
    if duration < _LONG_FORM_MIN_MS:
        return 0.70
    if duration <= _LONG_FORM_MAX_MS:
        return 1.0
    return 0.90


def _quality_score(candidate: CandidateContent) -> float:
    total = sum(max(0, int(value)) for value in candidate.engagement.values())
    if total <= 0:
        return 0.0
    return round(min(1.0, math.log1p(total) / math.log1p(100_000)), 6)


def _spam_penalty(candidate: CandidateContent) -> float:
    text = " ".join((candidate.caption or candidate.title or "").split())
    if not text:
        return 0.0
    tokens = _TOKEN.findall(text)
    url_count = len(_URL.findall(text))
    penalty = 0.0
    if _LINK_FARM.search(text):
        penalty += 0.65
    if _PROMO.search(text):
        penalty += 0.25
    if url_count >= 2:
        penalty += 0.25
    elif url_count == 1 and len(tokens) <= 12:
        penalty += 0.12
    return round(min(1.0, penalty), 6)


def _candidate_key(candidate: CandidateContent) -> tuple[str, str]:
    return candidate.source, candidate.source_id


def _metadata_float(metadata: Mapping[str, object], key: str, default: float) -> float:
    value = metadata.get(key)
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return default
