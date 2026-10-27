from dataclasses import replace

from temporalio import activity

from vimi_social.db.tenant import tenant_transaction
from vimi_social.domain.source import (
    CandidateContent,
    ScoutRunResult,
    ScoutWorkflowInput,
    SourceTaskState,
)
from vimi_social.source.ocr import PreviewOcrUnavailable
from vimi_social.source.personalization import (
    _CURRENT_PROFILE,
    _CURRENT_TASTE_SEMANTIC,
)
from vimi_social.source.retrieval_v3 import RetrievalV3ScoutActivities
from vimi_social.source.semantic import SemanticRelevanceUnavailable
from vimi_social.source.visual import VisualRelevanceUnavailable


class HomeTimelineRetrievalV3ScoutActivities(RetrievalV3ScoutActivities):
    """Merge OAuth home-timeline seeds with Search API results before final ranking."""

    @activity.defn(name="execute_scout_task")
    async def execute_scout_task(
        self,
        workflow_input: ScoutWorkflowInput,
    ) -> ScoutRunResult:
        result = await super().execute_scout_task(workflow_input)
        if (
            result.state is not SourceTaskState.COMPLETED
            or not workflow_input.seed_candidates
        ):
            return result

        task = self._authorized_task(workflow_input)
        with self._session_factory() as session, tenant_transaction(
            session,
            task.tenant_id,
        ):
            search_candidates = self._source_repository.list_candidates(
                session,
                task.id,
                limit=1000,
            )

        combined = _merge_candidate_pools(
            search_candidates,
            workflow_input.seed_candidates,
        )
        if not combined:
            return result

        profile_token = self._set_profile(task.actor_user_id, task.tenant_id)
        taste_token = _CURRENT_TASTE_SEMANTIC.set({})
        try:
            query_plan = await self._query_planner.plan(
                task.user_intent,
                task.preferred_languages,
            )
            semantic_scores: tuple[float, ...] | None = None
            if self._semantic_scorer is not None:
                try:
                    semantic_scores = await self._score_semantic_candidates(
                        query_plan.query_variants,
                        combined,
                    )
                except SemanticRelevanceUnavailable:
                    semantic_scores = None

            provisional = self._curator.rank(
                combined,
                query_variants=query_plan.query_variants,
                preferred_languages=task.preferred_languages,
                limit=max(1, len(combined)),
                semantic_scores=semantic_scores,
                minimum_relevance=self._semantic_minimum_relevance,
            )
            evidence_candidates = provisional[: self._preview_evidence_limit]

            visual_scores: tuple[float | None, ...] | None = None
            if self._visual_scorer is not None and evidence_candidates:
                try:
                    evidence_visual_scores = await self._score_visual_candidates(
                        query_plan.query_variants,
                        evidence_candidates,
                    )
                    visual_scores = _align_optional_floats(
                        combined,
                        evidence_candidates,
                        evidence_visual_scores,
                    )
                except VisualRelevanceUnavailable:
                    visual_scores = None

            preview_ocr_texts: tuple[str | None, ...] | None = None
            preview_ocr_semantic_scores: tuple[float | None, ...] | None = None
            if self._preview_ocr_extractor is not None and evidence_candidates:
                try:
                    evidence_ocr_texts = await self._extract_preview_ocr_texts(
                        evidence_candidates
                    )
                    preview_ocr_texts = _align_optional_texts(
                        combined,
                        evidence_candidates,
                        evidence_ocr_texts,
                    )
                except PreviewOcrUnavailable:
                    preview_ocr_texts = None

            if (
                preview_ocr_texts is not None
                and self._semantic_scorer is not None
                and any(text for text in preview_ocr_texts)
            ):
                try:
                    preview_ocr_semantic_scores = await self._score_semantic_texts(
                        query_plan.query_variants,
                        preview_ocr_texts,
                    )
                except SemanticRelevanceUnavailable:
                    preview_ocr_semantic_scores = None

            curated = self._curator.rank(
                combined,
                query_variants=query_plan.query_variants,
                preferred_languages=task.preferred_languages,
                limit=max(1, len(combined)),
                semantic_scores=semantic_scores,
                visual_scores=visual_scores,
                preview_ocr_texts=preview_ocr_texts,
                preview_ocr_semantic_scores=preview_ocr_semantic_scores,
                visual_weight=self._visual_relevance_weight,
                preview_ocr_weight=self._preview_ocr_weight,
                minimum_relevance=self._semantic_minimum_relevance,
            )
        finally:
            _CURRENT_TASTE_SEMANTIC.reset(taste_token)
            _CURRENT_PROFILE.reset(profile_token)

        with self._session_factory() as session, tenant_transaction(
            session,
            task.tenant_id,
        ):
            persisted = self._source_repository.replace_candidates(
                session,
                task_id=task.id,
                tenant_id=task.tenant_id,
                candidates=curated,
            )

        return ScoutRunResult(
            operation_key=result.operation_key,
            state=result.state,
            discovered_count=result.discovered_count + len(workflow_input.seed_candidates),
            candidate_count=len(persisted),
            failure_code=result.failure_code,
        )


def _merge_candidate_pools(
    search_candidates: tuple[CandidateContent, ...],
    seed_candidates: tuple[CandidateContent, ...],
) -> tuple[CandidateContent, ...]:
    result: list[CandidateContent] = list(search_candidates)
    positions = {
        (candidate.source, candidate.source_id): index
        for index, candidate in enumerate(result)
    }
    for seed in seed_candidates:
        key = (seed.source, seed.source_id)
        existing_index = positions.get(key)
        if existing_index is None:
            positions[key] = len(result)
            result.append(seed)
            continue
        existing = result[existing_index]
        metadata = dict(existing.connector_metadata)
        metadata["x_home_timeline_seen"] = True
        result[existing_index] = replace(existing, connector_metadata=metadata)
    return tuple(result)


def _candidate_key(candidate: CandidateContent) -> tuple[str, str]:
    return candidate.source, candidate.source_id


def _align_optional_floats(
    candidates: tuple[CandidateContent, ...],
    scored_candidates: tuple[CandidateContent, ...],
    scores: tuple[float | None, ...],
) -> tuple[float | None, ...]:
    score_by_key = {
        _candidate_key(candidate): score
        for candidate, score in zip(scored_candidates, scores, strict=True)
    }
    return tuple(score_by_key.get(_candidate_key(candidate)) for candidate in candidates)


def _align_optional_texts(
    candidates: tuple[CandidateContent, ...],
    scored_candidates: tuple[CandidateContent, ...],
    texts: tuple[str | None, ...],
) -> tuple[str | None, ...]:
    text_by_key = {
        _candidate_key(candidate): text
        for candidate, text in zip(scored_candidates, texts, strict=True)
    }
    return tuple(text_by_key.get(_candidate_key(candidate)) for candidate in candidates)
