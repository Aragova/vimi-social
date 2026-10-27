from collections.abc import Callable, Mapping
from contextvars import ContextVar, Token
from dataclasses import replace
from uuid import UUID

from sqlalchemy.orm import Session
from temporalio import activity

from vimi_social.db.tenant import tenant_transaction
from vimi_social.domain.identity import TenantId
from vimi_social.domain.interest import UserInterestProfile
from vimi_social.domain.source import (
    CandidateContent,
    ScoutContinuationWorkflowInput,
    ScoutRunResult,
    ScoutWorkflowInput,
)
from vimi_social.source.activities import ScoutActivities
from vimi_social.source.candidate_filter import (
    FilteringCandidateCurator,
    FilteringScoutContinuationActivities,
)
from vimi_social.source.connectors import SourceConnectorRegistry
from vimi_social.source.curator import CandidateCurator
from vimi_social.source.interest_profile import (
    apply_interest_profile,
    build_interest_summary,
)
from vimi_social.source.interest_repository import UserInterestProfileRepository
from vimi_social.source.ocr import PreviewOcrExtractor
from vimi_social.source.query_planner import MultilingualQueryPlanner
from vimi_social.source.repository import SourceTaskRepository
from vimi_social.source.scout_attempts import ScoutAttemptStore
from vimi_social.source.semantic import (
    SemanticRelevanceScorer,
    SemanticRelevanceUnavailable,
)
from vimi_social.source.visual import VisualRelevanceScorer
from vimi_social.telegram.outgoing import TelegramMessenger
from vimi_social.usage.repository import UsageRepository

_CURRENT_PROFILE: ContextVar[UserInterestProfile | None] = ContextVar(
    "vimi_current_interest_profile",
    default=None,
)
_CURRENT_TASTE_SEMANTIC: ContextVar[dict[tuple[str, str], float] | None] = ContextVar(
    "vimi_current_taste_semantic",
    default=None,
)
_PERSONAL_AFFINITY_WEIGHT = 0.10
_LOCAL_AI_BATCH_LIMIT = 100


class PersonalizedFilteringCandidateCurator(FilteringCandidateCurator):
    """Apply a bounded taste boost only after the normal relevance gates pass."""

    def rank(
        self,
        candidates: tuple[CandidateContent, ...],
        *,
        query_variants: tuple[str, ...],
        preferred_languages: tuple[str, ...],
        limit: int,
        semantic_scores: tuple[float, ...] | None = None,
        visual_scores: tuple[float | None, ...] | None = None,
        preview_ocr_texts: tuple[str | None, ...] | None = None,
        preview_ocr_semantic_scores: tuple[float | None, ...] | None = None,
        visual_weight: float = 0.15,
        preview_ocr_weight: float = 0.10,
        minimum_relevance: float = 0.0,
    ) -> tuple[CandidateContent, ...]:
        if limit < 1:
            return ()

        profile = _CURRENT_PROFILE.get()
        taste_semantic = _CURRENT_TASTE_SEMANTIC.get() or {}
        enriched = tuple(
            apply_interest_profile(
                candidate,
                profile,
                semantic_affinity=taste_semantic.get(_candidate_key(candidate)),
            )
            for candidate in candidates
        )
        ranked = super().rank(
            enriched,
            query_variants=query_variants,
            preferred_languages=preferred_languages,
            limit=len(enriched),
            semantic_scores=semantic_scores,
            visual_scores=visual_scores,
            preview_ocr_texts=preview_ocr_texts,
            preview_ocr_semantic_scores=preview_ocr_semantic_scores,
            visual_weight=visual_weight,
            preview_ocr_weight=preview_ocr_weight,
            minimum_relevance=minimum_relevance,
        )
        if not ranked:
            return ()

        rescored: list[
            tuple[float, float, float, float, float, float, int, CandidateContent]
        ] = []
        for index, candidate in enumerate(ranked):
            metadata = dict(candidate.connector_metadata)
            relevance = _metadata_float(metadata, "curator_relevance_score", 0.0)
            affinity = _metadata_float(metadata, "personal_affinity_score", 0.0)
            personalized = round(
                relevance + (_PERSONAL_AFFINITY_WEIGHT * affinity),
                6,
            )
            metadata["curator_personal_affinity_score"] = affinity
            metadata["curator_personalized_score"] = personalized
            updated = replace(candidate, connector_metadata=metadata)
            rescored.append(
                (
                    personalized,
                    relevance,
                    _metadata_float(
                        metadata,
                        "curator_semantic_relevance_score",
                        -1.0,
                    ),
                    _metadata_float(metadata, "curator_lexical_relevance_score", 0.0),
                    _metadata_float(metadata, "curator_duration_preference_score", 0.0),
                    _metadata_float(metadata, "curator_quality_score", 0.0),
                    -index,
                    updated,
                )
            )

        rescored.sort(key=lambda item: item[:7], reverse=True)
        result: list[CandidateContent] = []
        for rank, item in enumerate(rescored[:limit], start=1):
            candidate = item[7]
            metadata = dict(candidate.connector_metadata)
            metadata["curator_rank"] = rank
            result.append(replace(candidate, connector_metadata=metadata))
        return tuple(result)


class PersonalizedScoutActivities(ScoutActivities):
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
        curator: CandidateCurator | None = None,
        semantic_scorer: SemanticRelevanceScorer | None = None,
        visual_scorer: VisualRelevanceScorer | None = None,
        preview_ocr_extractor: PreviewOcrExtractor | None = None,
        visual_relevance_weight: float = 0.15,
        preview_ocr_weight: float = 0.10,
        semantic_minimum_relevance: float = 0.0,
        retrieval_budget: int = 300,
        retrieval_round_limit: int = 30,
        preview_evidence_limit: int = 50,
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
            curator=curator,
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
        self._interest_repository = (
            interest_repository or UserInterestProfileRepository()
        )

    @activity.defn(name="execute_scout_task")
    async def execute_scout_task(
        self,
        workflow_input: ScoutWorkflowInput,
    ) -> ScoutRunResult:
        task = self._authorized_task(workflow_input)
        profile_token = self._set_profile(task.actor_user_id, task.tenant_id)
        taste_token = _CURRENT_TASTE_SEMANTIC.set({})
        try:
            return await super().execute_scout_task(workflow_input)
        finally:
            _CURRENT_TASTE_SEMANTIC.reset(taste_token)
            _CURRENT_PROFILE.reset(profile_token)

    async def _score_semantic_candidates(
        self,
        query_variants: tuple[str, ...],
        candidates: tuple[CandidateContent, ...],
    ) -> tuple[float, ...]:
        query_scores = await super()._score_semantic_candidates(
            query_variants,
            candidates,
        )
        await _cache_taste_semantic_scores(
            self._semantic_scorer,
            _CURRENT_PROFILE.get(),
            _CURRENT_TASTE_SEMANTIC.get(),
            candidates,
        )
        return query_scores

    def _set_profile(
        self,
        user_id: UUID,
        tenant_id: TenantId,
    ) -> Token[UserInterestProfile | None]:
        with self._session_factory() as session, tenant_transaction(session, tenant_id):
            profile = self._interest_repository.get(session, user_id=user_id)
        return _CURRENT_PROFILE.set(profile)


class PersonalizedFilteringScoutContinuationActivities(
    FilteringScoutContinuationActivities
):
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
        curator: CandidateCurator | None = None,
        semantic_scorer: SemanticRelevanceScorer | None = None,
        semantic_minimum_relevance: float = 0.0,
        batch_size: int = 30,
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
            curator=curator,
            semantic_scorer=semantic_scorer,
            semantic_minimum_relevance=semantic_minimum_relevance,
            batch_size=batch_size,
        )
        self._interest_repository = (
            interest_repository or UserInterestProfileRepository()
        )

    @activity.defn(name="continue_scout_results")
    async def continue_scout_results(
        self,
        workflow_input: ScoutContinuationWorkflowInput,
    ) -> ScoutRunResult:
        task = self._authorized_task(workflow_input)
        with self._session_factory() as session, tenant_transaction(
            session,
            task.tenant_id,
        ):
            profile = self._interest_repository.get(
                session,
                user_id=task.actor_user_id,
            )
        profile_token = _CURRENT_PROFILE.set(profile)
        taste_token = _CURRENT_TASTE_SEMANTIC.set({})
        try:
            return await super().continue_scout_results(workflow_input)
        finally:
            _CURRENT_TASTE_SEMANTIC.reset(taste_token)
            _CURRENT_PROFILE.reset(profile_token)

    async def _score_semantic_candidates(
        self,
        query_variants: tuple[str, ...],
        candidates: tuple[CandidateContent, ...],
    ) -> tuple[float, ...]:
        query_scores = await super()._score_semantic_candidates(
            query_variants,
            candidates,
        )
        await _cache_taste_semantic_scores(
            self._semantic_scorer,
            _CURRENT_PROFILE.get(),
            _CURRENT_TASTE_SEMANTIC.get(),
            candidates,
        )
        return query_scores


async def _cache_taste_semantic_scores(
    scorer: SemanticRelevanceScorer | None,
    profile: UserInterestProfile | None,
    cache: dict[tuple[str, str], float] | None,
    candidates: tuple[CandidateContent, ...],
) -> None:
    if scorer is None or profile is None or cache is None or not candidates:
        return
    summary = build_interest_summary(profile)
    if summary is None:
        return

    missing = tuple(
        candidate
        for candidate in candidates
        if _candidate_key(candidate) not in cache
    )
    if not missing:
        return

    try:
        for start in range(0, len(missing), _LOCAL_AI_BATCH_LIMIT):
            batch = missing[start : start + _LOCAL_AI_BATCH_LIMIT]
            scores = await scorer.score_candidates((summary,), batch)
            if len(scores) != len(batch):
                raise SemanticRelevanceUnavailable(
                    "taste semantic batch alignment mismatch"
                )
            for candidate, score in zip(batch, scores, strict=True):
                cache[_candidate_key(candidate)] = max(0.0, min(1.0, float(score)))
    except SemanticRelevanceUnavailable:
        # Taste semantics are optional. Query relevance and lexical taste signals
        # continue to work when local E5 is temporarily unavailable.
        return


def _candidate_key(candidate: CandidateContent) -> tuple[str, str]:
    return candidate.source, candidate.source_id


def _metadata_float(
    metadata: Mapping[str, object],
    key: str,
    default: float,
) -> float:
    value = metadata.get(key)
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return default
