from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy.orm import Session
from temporalio import activity
from temporalio.exceptions import ApplicationError

from vimi_social.db.tenant import tenant_transaction
from vimi_social.domain.identity import OperationKey
from vimi_social.domain.international import UiLocale
from vimi_social.domain.source import (
    CandidateContent,
    ScoutRefillContinuationState,
    ScoutRunResult,
    ScoutSearchRequest,
    ScoutWorkflowInput,
    SourceTask,
    SourceTaskState,
)
from vimi_social.source.connectors import (
    SourceConnectorRateLimited,
    SourceConnectorRegistry,
    SourceConnectorRejected,
    SourceConnectorUnavailable,
    SourceSearchCandidates,
)
from vimi_social.source.curator import CandidateCurator, restore_curator_order
from vimi_social.source.ocr import PreviewOcrExtractor, PreviewOcrUnavailable
from vimi_social.source.query_planner import MultilingualQueryPlanner, ScoutQueryRound
from vimi_social.source.repository import SourceTaskRepository
from vimi_social.source.scout_attempts import ScoutAttemptStore
from vimi_social.source.semantic import (
    SemanticRelevanceScorer,
    SemanticRelevanceUnavailable,
)
from vimi_social.source.visual import (
    VisualRelevanceScorer,
    VisualRelevanceUnavailable,
)
from vimi_social.telegram.outgoing import (
    TelegramMessageRetryAfter,
    TelegramMessenger,
    TelegramOutgoingState,
)
from vimi_social.telegram.scout_results import build_scout_results
from vimi_social.usage.repository import UsageRepository

_LOCAL_AI_BATCH_LIMIT = 100
_SCOUT_RELEVANT_TARGET = 10
_X_MIN_PAGE_SIZE = 10
_CONTINUATION_CARRIER_KEYS = (
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


class ScoutActivities:
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
    ) -> None:
        self._session_factory = session_factory
        self._registry = registry
        self._messenger = messenger
        self._source_repository = source_repository or SourceTaskRepository()
        self._usage_repository = usage_repository or UsageRepository()
        self._attempt_store = attempt_store or ScoutAttemptStore()
        self._query_planner = query_planner or MultilingualQueryPlanner()
        self._curator = curator or CandidateCurator()
        self._semantic_scorer = semantic_scorer
        self._visual_scorer = visual_scorer
        self._preview_ocr_extractor = preview_ocr_extractor
        self._visual_relevance_weight = max(0.0, min(0.40, visual_relevance_weight))
        self._preview_ocr_weight = max(0.0, min(0.25, preview_ocr_weight))
        self._semantic_minimum_relevance = max(0.0, min(1.0, semantic_minimum_relevance))
        self._retrieval_budget = max(_X_MIN_PAGE_SIZE, min(1000, retrieval_budget))
        self._retrieval_round_limit = max(
            _X_MIN_PAGE_SIZE,
            min(retrieval_round_limit, self._retrieval_budget),
        )
        self._preview_evidence_limit = max(
            0,
            min(preview_evidence_limit, self._retrieval_budget),
        )

    @activity.defn(name="execute_scout_task")
    async def execute_scout_task(self, workflow_input: ScoutWorkflowInput) -> ScoutRunResult:
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
                current = self._source_repository.get_by_operation_key(
                    session,
                    task.operation_key,
                )
                if current is None:
                    raise RuntimeError("source task disappeared from tenant context")
                return self._result_for_task(session, current)

            self._usage_repository.commit(session, task.operation_key)

        query_plan = await self._query_planner.plan(
            task.user_intent,
            task.preferred_languages,
        )
        discovered: list[CandidateContent] = []
        retrieval_spent = 0
        continuation_states: list[ScoutRefillContinuationState] = []

        async for search_round in self._query_planner.search_rounds(
            query_plan,
            task.user_intent,
            task.preferred_languages,
        ):
            source_failure_code: str | None = None
            target_met = False
            for connector in connectors:
                pagination_token: str | None = None
                continuation_generation = 0
                pages_read = 0
                round_continuation_state: ScoutRefillContinuationState | None = None

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
                    # Reserve the external-read budget before every provider call. Even a
                    # partial/failed paginated call may already have consumed provider reads.
                    retrieval_spent += request_limit
                    try:
                        round_candidates = await connector.search(request)
                        pages_read += 1
                        discovered.extend(
                            _with_retrieval_provenance(
                                candidate,
                                search_round,
                                continuation_generation=continuation_generation,
                            )
                            for candidate in round_candidates
                        )
                    except SourceConnectorRateLimited:
                        source_failure_code = "SOURCE_RATE_LIMITED"
                        break
                    except SourceConnectorRejected:
                        source_failure_code = "SOURCE_ACCESS_REJECTED"
                        break
                    except SourceConnectorUnavailable:
                        source_failure_code = "SOURCE_UNAVAILABLE"
                        if pagination_token is not None and round_continuation_state is not None:
                            round_continuation_state = _retire_ambiguous_refill_state(
                                round_continuation_state,
                                page_start_token=pagination_token,
                                continuation_generation=continuation_generation,
                            )
                        break

                    if isinstance(round_candidates, SourceSearchCandidates):
                        round_continuation_state = _capture_continuation_state(
                            round_candidates,
                            search_round,
                            requested_token=pagination_token,
                            continuation_generation=continuation_generation,
                            previous=round_continuation_state,
                        )

                    round_relevant = await self._rank_relevant_pool(
                        query_plan.query_variants,
                        task.preferred_languages,
                        discovered,
                    )
                    if len(round_relevant) >= _SCOUT_RELEVANT_TARGET:
                        target_met = True
                        break
                    if retrieval_spent >= self._retrieval_budget:
                        break
                    if search_round.max_pages is not None and pages_read >= search_round.max_pages:
                        break

                    next_token = (
                        round_candidates.next_token
                        if isinstance(round_candidates, SourceSearchCandidates)
                        else None
                    )
                    if next_token is None or next_token == pagination_token:
                        break
                    pagination_token = next_token
                    continuation_generation += 1

                if round_continuation_state is not None:
                    continuation_states.append(round_continuation_state)
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
            if source_failure_code is not None:
                break
            if target_met:
                break
            if retrieval_spent >= self._retrieval_budget:
                break

        normalized = _deduplicate(discovered)
        semantic_scores: tuple[float, ...] | None = None
        if self._semantic_scorer is not None and normalized:
            try:
                semantic_scores = await self._score_semantic_candidates(
                    query_plan.query_variants,
                    normalized,
                )
            except SemanticRelevanceUnavailable:
                semantic_scores = None

        provisional = self._curator.rank(
            normalized,
            query_variants=query_plan.query_variants,
            preferred_languages=task.preferred_languages,
            limit=max(1, len(normalized)),
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
                    normalized,
                    evidence_candidates,
                    evidence_visual_scores,
                )
            except VisualRelevanceUnavailable:
                visual_scores = None

        preview_ocr_texts: tuple[str | None, ...] | None = None
        preview_ocr_semantic_scores: tuple[float | None, ...] | None = None
        if self._preview_ocr_extractor is not None and evidence_candidates:
            try:
                evidence_ocr_texts = await self._extract_preview_ocr_texts(evidence_candidates)
                preview_ocr_texts = _align_optional_texts(
                    normalized,
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
            normalized,
            query_variants=query_plan.query_variants,
            preferred_languages=task.preferred_languages,
            limit=max(1, len(normalized)),
            semantic_scores=semantic_scores,
            visual_scores=visual_scores,
            preview_ocr_texts=preview_ocr_texts,
            preview_ocr_semantic_scores=preview_ocr_semantic_scores,
            visual_weight=self._visual_relevance_weight,
            preview_ocr_weight=self._preview_ocr_weight,
            minimum_relevance=self._semantic_minimum_relevance,
        )
        for continuation_state in continuation_states:
            curated = _apply_continuation_state(curated, continuation_state)
        with self._session_factory() as session, tenant_transaction(session, task.tenant_id):
            if not self._attempt_store.lock_owned_attempt(
                session,
                operation_key=task.operation_key,
                attempt_token=attempt_token,
            ):
                current = self._source_repository.get_by_operation_key(
                    session,
                    task.operation_key,
                )
                if current is None:
                    raise RuntimeError("source task disappeared from tenant context")
                return self._result_for_task(session, current)

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
            discovered_count=len(discovered),
            candidate_count=len(persisted),
        )

    async def _rank_relevant_pool(
        self,
        query_variants: tuple[str, ...],
        preferred_languages: tuple[str, ...],
        discovered: list[CandidateContent],
    ) -> tuple[CandidateContent, ...]:
        normalized = _deduplicate(discovered)
        semantic_scores: tuple[float, ...] | None = None
        if self._semantic_scorer is not None and normalized:
            try:
                semantic_scores = await self._score_semantic_candidates(
                    query_variants,
                    normalized,
                )
            except SemanticRelevanceUnavailable:
                semantic_scores = None

        return self._curator.rank(
            normalized,
            query_variants=query_variants,
            preferred_languages=preferred_languages,
            limit=max(1, len(normalized)),
            semantic_scores=semantic_scores,
            minimum_relevance=self._semantic_minimum_relevance,
        )

    async def _score_semantic_candidates(
        self,
        query_variants: tuple[str, ...],
        candidates: tuple[CandidateContent, ...],
    ) -> tuple[float, ...]:
        scorer = self._semantic_scorer
        if scorer is None:
            return ()

        scores: list[float] = []
        for start in range(0, len(candidates), _LOCAL_AI_BATCH_LIMIT):
            batch = candidates[start : start + _LOCAL_AI_BATCH_LIMIT]
            batch_scores = await scorer.score_candidates(query_variants, batch)
            if len(batch_scores) != len(batch):
                raise SemanticRelevanceUnavailable("semantic batch alignment mismatch")
            scores.extend(batch_scores)
        return tuple(scores)

    async def _score_visual_candidates(
        self,
        query_variants: tuple[str, ...],
        candidates: tuple[CandidateContent, ...],
    ) -> tuple[float | None, ...]:
        scorer = self._visual_scorer
        if scorer is None:
            return ()

        scores: list[float | None] = []
        for start in range(0, len(candidates), _LOCAL_AI_BATCH_LIMIT):
            batch = candidates[start : start + _LOCAL_AI_BATCH_LIMIT]
            batch_scores = await scorer.score_preview_candidates(query_variants, batch)
            if len(batch_scores) != len(batch):
                raise VisualRelevanceUnavailable("visual batch alignment mismatch")
            scores.extend(batch_scores)
        return tuple(scores)

    async def _extract_preview_ocr_texts(
        self,
        candidates: tuple[CandidateContent, ...],
    ) -> tuple[str | None, ...]:
        extractor = self._preview_ocr_extractor
        if extractor is None:
            return ()

        texts: list[str | None] = []
        for start in range(0, len(candidates), _LOCAL_AI_BATCH_LIMIT):
            batch = candidates[start : start + _LOCAL_AI_BATCH_LIMIT]
            batch_texts = await extractor.extract_preview_texts(batch)
            if len(batch_texts) != len(batch):
                raise PreviewOcrUnavailable("OCR batch alignment mismatch")
            texts.extend(batch_texts)
        return tuple(texts)

    async def _score_semantic_texts(
        self,
        query_variants: tuple[str, ...],
        texts: tuple[str | None, ...],
    ) -> tuple[float | None, ...]:
        scorer = self._semantic_scorer
        if scorer is None:
            return ()

        scores: list[float | None] = []
        for start in range(0, len(texts), _LOCAL_AI_BATCH_LIMIT):
            batch = texts[start : start + _LOCAL_AI_BATCH_LIMIT]
            if not any(text for text in batch):
                scores.extend(None for _ in batch)
                continue
            batch_scores = await scorer.score_texts(query_variants, batch)
            if len(batch_scores) != len(batch):
                raise SemanticRelevanceUnavailable("semantic text batch alignment mismatch")
            scores.extend(batch_scores)
        return tuple(scores)

    @activity.defn(name="deliver_scout_results")
    async def deliver_scout_results(
        self,
        workflow_input: ScoutWorkflowInput,
        result: ScoutRunResult,
    ) -> str:
        if self._messenger is None:
            raise ApplicationError(
                "Telegram delivery is not configured in the worker",
                non_retryable=True,
                type="TelegramDeliveryNotConfigured",
            )

        task = self._authorized_task(workflow_input)
        if task.telegram_update_id is None or task.telegram_chat_id is None:
            raise ApplicationError(
                "source task has no Telegram delivery metadata",
                non_retryable=True,
                type="TelegramDeliveryMetadataMissing",
            )

        candidates: tuple[CandidateContent, ...] = ()
        if result.state is SourceTaskState.COMPLETED:
            with self._session_factory() as session, tenant_transaction(session, task.tenant_id):
                candidates = restore_curator_order(
                    self._source_repository.list_candidates(
                        session,
                        task.id,
                        limit=self._retrieval_budget,
                    )
                )

        message = build_scout_results(
            UiLocale(task.locale),
            result,
            candidates,
            task_id=task.id,
        )
        try:
            state = await self._messenger.send_message(
                task.telegram_update_id,
                f"source-task-results:{task.id}",
                task.telegram_chat_id,
                message,
            )
        except TelegramMessageRetryAfter as error:
            raise ApplicationError(
                "Telegram result delivery is rate limited",
                next_retry_delay=timedelta(seconds=error.retry_after_seconds),
                type="TelegramResultRateLimited",
            ) from None

        if state is TelegramOutgoingState.UNKNOWN:
            return TelegramOutgoingState.UNKNOWN.value
        if state is TelegramOutgoingState.FAILED_SAFE:
            return TelegramOutgoingState.FAILED_SAFE.value
        return TelegramOutgoingState.CONFIRMED.value

    def _authorized_task(self, workflow_input: ScoutWorkflowInput) -> SourceTask:
        operation_key = OperationKey(workflow_input.operation_key)
        try:
            execution_token = UUID(workflow_input.execution_token)
        except ValueError:
            raise RuntimeError("invalid source task execution token") from None

        with self._session_factory() as session, session.begin():
            tenant_id = self._source_repository.resolve_tenant(
                session,
                operation_key=operation_key,
                execution_token=execution_token,
            )

        with self._session_factory() as session, tenant_transaction(session, tenant_id):
            task = self._source_repository.get_by_operation_key(session, operation_key)
            if task is None or task.execution_token != execution_token:
                raise RuntimeError("source task authority binding mismatch")
            return task

    def _fail_safe(
        self,
        task: SourceTask,
        failure_code: str,
        *,
        release_usage: bool = False,
        attempt_token: UUID | None = None,
    ) -> ScoutRunResult:
        with self._session_factory() as session, tenant_transaction(session, task.tenant_id):
            if attempt_token is None:
                transitioned = self._attempt_store.fail_queued(
                    session,
                    operation_key=task.operation_key,
                    failure_code=failure_code,
                )
                if transitioned and release_usage:
                    self._usage_repository.release(session, task.operation_key)
            else:
                transitioned = self._attempt_store.finish_owned_attempt(
                    session,
                    operation_key=task.operation_key,
                    attempt_token=attempt_token,
                    state=SourceTaskState.FAILED_SAFE,
                    failure_code=failure_code,
                )

            if transitioned:
                return ScoutRunResult(
                    operation_key=task.operation_key.value,
                    state=SourceTaskState.FAILED_SAFE,
                    discovered_count=0,
                    candidate_count=0,
                    failure_code=failure_code,
                )

            current = self._source_repository.get_by_operation_key(session, task.operation_key)
            if current is None:
                raise RuntimeError("source task disappeared from tenant context")
            return self._result_for_task(session, current)

    def _result_for_task(self, session: Session, task: SourceTask) -> ScoutRunResult:
        if task.state is SourceTaskState.COMPLETED:
            candidates = self._source_repository.list_candidates(
                session,
                task.id,
                limit=self._retrieval_budget,
            )
            return ScoutRunResult(
                operation_key=task.operation_key.value,
                state=SourceTaskState.COMPLETED,
                discovered_count=len(candidates),
                candidate_count=len(candidates),
            )
        if task.state is SourceTaskState.FAILED_SAFE:
            return ScoutRunResult(
                operation_key=task.operation_key.value,
                state=SourceTaskState.FAILED_SAFE,
                discovered_count=0,
                candidate_count=0,
                failure_code=task.failure_code,
            )
        if task.state is SourceTaskState.UNKNOWN:
            return ScoutRunResult(
                operation_key=task.operation_key.value,
                state=SourceTaskState.UNKNOWN,
                discovered_count=0,
                candidate_count=0,
                failure_code=task.failure_code or "SCOUT_ATTEMPT_AMBIGUOUS",
            )
        raise RuntimeError(f"source task is not terminal: {task.state.value}")


def _with_retrieval_provenance(
    candidate: CandidateContent,
    search_round: ScoutQueryRound,
    *,
    continuation_generation: int = 0,
) -> CandidateContent:
    metadata = dict(candidate.connector_metadata)
    metadata["retrieval_query"] = search_round.query_variants[0]
    metadata["retrieval_query_variants"] = list(search_round.query_variants)
    metadata["retrieval_relaxation_level"] = search_round.relaxation_level
    metadata["retrieval_specificity"] = search_round.specificity
    metadata["retrieval_language_mode"] = "+".join(search_round.preferred_languages)
    metadata["x_continuation_generation"] = continuation_generation
    return replace(candidate, connector_metadata=metadata)


def _metadata_text(metadata: dict[str, object], key: str) -> str | None:
    value = metadata.get(key)
    return value if isinstance(value, str) and value else None


def _capture_continuation_state(
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
        provider_metadata = dict(candidates[0].connector_metadata)
        search_scope = _metadata_text(provider_metadata, "x_search_scope") or search_scope
        search_query = _metadata_text(provider_metadata, "x_search_query") or search_query

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


def _retire_ambiguous_refill_state(
    state: ScoutRefillContinuationState,
    *,
    page_start_token: str,
    continuation_generation: int,
) -> ScoutRefillContinuationState:
    return replace(
        state,
        page_start_token=page_start_token,
        next_token=None,
        continuation_generation=continuation_generation,
    )


def _continuation_state_metadata(state: ScoutRefillContinuationState) -> dict[str, object]:
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


def _apply_continuation_state(
    candidates: tuple[CandidateContent, ...],
    state: ScoutRefillContinuationState,
) -> tuple[CandidateContent, ...]:
    if not candidates:
        return candidates

    carrier_index: int | None = None
    for index, candidate in enumerate(candidates):
        metadata = candidate.connector_metadata
        if (
            metadata.get("retrieval_relaxation_level") == state.retrieval_relaxation_level
            and metadata.get("retrieval_language_mode") == state.retrieval_language_mode
        ):
            carrier_index = index
            break
    if carrier_index is None:
        return candidates

    carrier = candidates[carrier_index]
    metadata = dict(carrier.connector_metadata)
    for key in _CONTINUATION_CARRIER_KEYS:
        metadata.pop(key, None)
    metadata.update(_continuation_state_metadata(state))
    updated = replace(carrier, connector_metadata=metadata)
    return (*candidates[:carrier_index], updated, *candidates[carrier_index + 1 :])


def _deduplicate(candidates: list[CandidateContent]) -> tuple[CandidateContent, ...]:
    result: list[CandidateContent] = []
    seen: set[tuple[str, str]] = set()
    for candidate in candidates:
        key = (candidate.source, candidate.source_id)
        if key in seen:
            continue
        seen.add(key)
        result.append(candidate)
    return tuple(result)


def _align_optional_floats(
    candidates: tuple[CandidateContent, ...],
    evidence_candidates: tuple[CandidateContent, ...],
    values: tuple[float | None, ...],
) -> tuple[float | None, ...]:
    if len(evidence_candidates) != len(values):
        raise ValueError("evidence score count must match evidence candidate count")
    by_key = {
        (candidate.source, candidate.source_id): value
        for candidate, value in zip(evidence_candidates, values, strict=True)
    }
    return tuple(by_key.get((candidate.source, candidate.source_id)) for candidate in candidates)


def _align_optional_texts(
    candidates: tuple[CandidateContent, ...],
    evidence_candidates: tuple[CandidateContent, ...],
    values: tuple[str | None, ...],
) -> tuple[str | None, ...]:
    if len(evidence_candidates) != len(values):
        raise ValueError("evidence text count must match evidence candidate count")
    by_key = {
        (candidate.source, candidate.source_id): value
        for candidate, value in zip(evidence_candidates, values, strict=True)
    }
    return tuple(by_key.get((candidate.source, candidate.source_id)) for candidate in candidates)
