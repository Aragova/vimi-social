from collections.abc import Callable
from contextvars import ContextVar, Token
from typing import cast

from sqlalchemy.orm import Session

from vimi_social.db.tenant import tenant_transaction
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
from vimi_social.source.interest_profile import apply_interest_profile
from vimi_social.source.interest_repository import UserInterestProfileRepository
from vimi_social.source.ocr import PreviewOcrExtractor
from vimi_social.source.query_planner import MultilingualQueryPlanner
from vimi_social.source.repository import SourceTaskRepository
from vimi_social.source.scout_attempts import ScoutAttemptStore
from vimi_social.source.semantic import SemanticRelevanceScorer
from vimi_social.source.visual import VisualRelevanceScorer
from vimi_social.telegram.outgoing import TelegramMessenger
from vimi_social.usage.repository import UsageRepository

_CURRENT_PROFILE: ContextVar[UserInterestProfile | None] = ContextVar(
    "vimi_current_interest_profile",
    default=None,
)
_PERSONAL_AFFINITY_WEIGHT = 0.10


class PersonalizedFilteringCandidateCurator(FilteringCandidateCurator):
    """Boost relevant candidates using the current user's explainable taste profile."""

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
        profile = _CURRENT_PROFILE.get()
        enriched = tuple(apply_interest_profile(candidate, profile) for candidate in candidates)
        ranked = super().rank(
            enriched,
            query_variants=query_variants,
            preferred_languages=preferred_languages,
            limit=max(1, len(enriched)) if enriched else limit,
            semantic_scores=semantic_scores,
            visual_scores=visual_scores,
            preview_ocr_texts=preview_ocr_texts,
            preview_ocr_semantic_scores=preview_ocr_semantic_scores,
            visual_weight=visual_weight,
            preview_ocr_weight=preview_ocr_weight,
            minimum_relevance=minimum_relevance,
        )
        if limit < 1 or not ranked:
            return ()

        rescored: list[tuple[float, float, float, float, int, CandidateContent]] = []
        for index, candidate in enumerate(ranked):
            metadata = dict(candidate.connector_metadata)
            relevance = _metadata_float(metadata, "curator_relevance_score", 0.0)
            affinity = _metadata_float(metadata, "personal_affinity_score", 0.0)
            personalized = round(
                min(1.0, relevance + (_PERSONAL_AFFINITY_WEIGHT * affinity)),
                6,
            )
            metadata["curator_personal_affinity_score"] = affinity
            metadata["curator_personalized_score"] = personalized
            updated = candidate.__class__(
                id=candidate.id,
                source=candidate.source,
                source_id=candidate.source_id,
                source_url=candidate.source_url,
                author=candidate.author,
                published_at=candidate.published_at,
                media_type=candidate.media_type,
                duration_ms=candidate.duration_ms,
                width=candidate.width,
                height=candidate.height,
                title=candidate.title,
                caption=candidate.caption,
                tags=candidate.tags,
                engagement=candidate.engagement,
                adult_classification=candidate.adult_classification,
                explicitness_score=candidate.explicitness_score,
                provenance_hint=candidate.provenance_hint,
                availability=candidate.availability,
                connector_metadata=metadata,
            )
            rescored.append(
                (
                    personalized,
                    relevance,
                    _metadata_float(metadata, "curator_semantic_relevance_score", -1.0),
                    _metadata_float(metadata, "curator_duration_preference_score", 0.0),
                    -index,
                    updated,
                )
            )

        rescored.sort(key=lambda item: item[:5], reverse=True)
        result: list[CandidateContent] = []
        for rank, item in enumerate(rescored[:limit], start=1):
            candidate = item[5]
            metadata = dict(candidate.connector_metadata)
            metadata["curator_rank"] = rank
            result.append(
                candidate.__class__(
                    id=candidate.id,
                    source=candidate.source,
                    source_id=candidate.source_id,
                    source_url=candidate.source_url,
                    author=candidate.author,
                    published_at=candidate.published_at,
                    media_type=candidate.media_type,
                    duration_ms=candidate.duration_ms,
                    width=candidate.width,
                    height=candidate.height,
                    title=candidate.title,
                    caption=candidate.caption,
                    tags=candidate.tags,
                    engagement=candidate.engagement,
                    adult_classification=candidate.adult_classification,
                    explicitness_score=candidate.explicitness_score,
                    provenance_hint=candidate.provenance_hint,
                    availability=candidate.availability,
                    connector_metadata=metadata,
                )
            )
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
        self._interest_repository = interest_repository or UserInterestProfileRepository()

    async def execute_scout_task(self, workflow_input: ScoutWorkflowInput) -> ScoutRunResult:
        task = self._authorized_task(workflow_input)
        token = self._set_profile(task.actor_user_id, task.tenant_id.value)
        try:
            return await super().execute_scout_task(workflow_input)
        finally:
            _CURRENT_PROFILE.reset(token)

    def _set_profile(self, user_id: object, tenant_id: object) -> Token[UserInterestProfile | None]:
        from vimi_social.domain.identity import TenantId
        from uuid import UUID

        resolved_user_id = cast(UUID, user_id)
        resolved_tenant_id = TenantId.parse(str(tenant_id))
        with self._session_factory() as session, tenant_transaction(session, resolved_tenant_id):
            profile = self._interest_repository.get(session, user_id=resolved_user_id)
        return _CURRENT_PROFILE.set(profile)


class PersonalizedFilteringScoutContinuationActivities(FilteringScoutContinuationActivities):
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
        self._interest_repository = interest_repository or UserInterestProfileRepository()

    async def continue_scout_results(
        self,
        workflow_input: ScoutContinuationWorkflowInput,
    ) -> ScoutRunResult:
        task = self._authorized_task(workflow_input)
        with self._session_factory() as session, tenant_transaction(session, task.tenant_id):
            profile = self._interest_repository.get(session, user_id=task.actor_user_id)
        token = _CURRENT_PROFILE.set(profile)
        try:
            return await super().continue_scout_results(workflow_input)
        finally:
            _CURRENT_PROFILE.reset(token)


def _metadata_float(metadata: dict[str, object], key: str, default: float) -> float:
    value = metadata.get(key)
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return default
