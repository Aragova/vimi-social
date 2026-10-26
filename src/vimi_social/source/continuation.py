from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta
from uuid import UUID

from sqlalchemy.orm import Session
from temporalio import activity
from temporalio.exceptions import ApplicationError

from vimi_social.db.tenant import tenant_transaction
from vimi_social.domain.identity import OperationKey
from vimi_social.domain.international import UiLocale
from vimi_social.domain.source import (
    CandidateContent,
    ScoutContinuationWorkflowInput,
    ScoutRunResult,
    ScoutSearchRequest,
    SourceTask,
    SourceTaskState,
)
from vimi_social.source.connectors import (
    SourceConnectorRateLimited,
    SourceConnectorRegistry,
    SourceConnectorRejected,
    SourceConnectorUnavailable,
)
from vimi_social.source.continuation_state import (
    ScoutContinuationState,
    find_scout_continuation_state,
)
from vimi_social.source.curator import CandidateCurator, restore_curator_order
from vimi_social.source.query_planner import MultilingualQueryPlanner
from vimi_social.source.repository import SourceTaskRepository
from vimi_social.source.semantic import (
    SemanticRelevanceScorer,
    SemanticRelevanceUnavailable,
)
from vimi_social.telegram.outgoing import TelegramMessageRetryAfter, TelegramMessenger
from vimi_social.telegram.scout_results import build_scout_result_page
from vimi_social.usage.repository import UsageRepository

_LOCAL_AI_BATCH_LIMIT = 100
_MAX_CONTINUATION_CANDIDATES = 100_000


class ScoutContinuationActivities:
    """Continue one already-successful X search round without broadening the query."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        registry: SourceConnectorRegistry,
        messenger: TelegramMessenger | None,
        *,
        source_repository: SourceTaskRepository | None = None,
        usage_repository: UsageRepository | None = None,
        query_planner: MultilingualQueryPlanner | None = None,
        curator: CandidateCurator | None = None,
        semantic_scorer: SemanticRelevanceScorer | None = None,
        semantic_minimum_relevance: float = 0.0,
        batch_size: int = 30,
    ) -> None:
        self._session_factory = session_factory
        self._registry = registry
        self._messenger = messenger
        self._source_repository = source_repository or SourceTaskRepository()
        self._usage_repository = usage_repository or UsageRepository()
        self._query_planner = query_planner or MultilingualQueryPlanner()
        self._curator = curator or CandidateCurator()
        self._semantic_scorer = semantic_scorer
        self._semantic_minimum_relevance = max(
            0.0,
            min(1.0, semantic_minimum_relevance),
        )
        self._batch_size = max(10, min(500, batch_size))

    @activity.defn(name="continue_scout_results")
    async def continue_scout_results(
        self,
        workflow_input: ScoutContinuationWorkflowInput,
    ) -> ScoutRunResult:
        task = self._authorized_task(workflow_input)
        request_key = OperationKey(workflow_input.request_key)

        existing = self._load_candidates(task)
        continuation = find_scout_continuation_state(existing)
        if continuation is None:
            self._release_usage(task, request_key)
            return self._result(task, existing, failure_code="NO_MORE_RESULTS")

        try:
            connector = self._registry.route(("x",))[0]
        except SourceConnectorUnavailable:
            self._release_usage(task, request_key)
            raise ApplicationError(
                "X source connector is unavailable",
                non_retryable=True,
                type="ScoutContinuationUnavailable",
            ) from None

        self._commit_usage(task, request_key)
        request = ScoutSearchRequest(
            intent=task.user_intent,
            requested_sources=("x",),
            preferred_languages=continuation.preferred_languages,
            query_variants=continuation.query_variants,
            max_results=self._batch_size,
            pagination_token=continuation.next_token,
            search_scope=continuation.search_scope,
        )
        try:
            fetched = await connector.search(request)
        except SourceConnectorRateLimited as error:
            self._release_committed_if_safe(task, request_key)
            raise ApplicationError(
                "X continuation is rate limited",
                non_retryable=True,
                next_retry_delay=(
                    timedelta(seconds=error.retry_after_seconds)
                    if error.retry_after_seconds is not None
                    else None
                ),
                type="ScoutContinuationRateLimited",
            ) from None
        except SourceConnectorRejected:
            self._release_committed_if_safe(task, request_key)
            raise ApplicationError(
                "X continuation was rejected",
                non_retryable=True,
                type="ScoutContinuationRejected",
            ) from None
        except SourceConnectorUnavailable:
            # Transport failures are ambiguous: the provider might have processed
            # the request even if the response was lost. Do not permit an automatic
            # or manual repeat of the same token; retire it from the result card.
            self._retire_continuation(task, continuation)
            return self._result(task, existing, failure_code="SOURCE_UNAVAILABLE")

        known_ids = {(candidate.source, candidate.source_id) for candidate in existing}
        unique_new = tuple(
            _with_continuation_provenance(candidate, continuation)
            for candidate in fetched
            if (candidate.source, candidate.source_id) not in known_ids
        )

        accepted: tuple[CandidateContent, ...] = ()
        if unique_new:
            query_plan = await self._query_planner.plan(
                task.user_intent,
                task.preferred_languages,
            )
            semantic_scores: tuple[float, ...] | None = None
            if self._semantic_scorer is not None:
                try:
                    semantic_scores = await self._score_semantic_candidates(
                        query_plan.query_variants,
                        unique_new,
                    )
                except SemanticRelevanceUnavailable:
                    semantic_scores = None
            accepted = self._curator.rank(
                unique_new,
                query_variants=query_plan.query_variants,
                preferred_languages=task.preferred_languages,
                limit=len(unique_new),
                semantic_scores=semantic_scores,
                minimum_relevance=self._semantic_minimum_relevance,
            )
            accepted = _offset_curator_ranks(accepted, len(existing))

        next_token = _next_token_from_candidates(fetched)
        carrier = _advance_carrier(continuation.carrier, next_token)
        with self._session_factory() as session, tenant_transaction(session, task.tenant_id):
            self._source_repository.replace_candidates(
                session,
                task_id=task.id,
                tenant_id=task.tenant_id,
                candidates=(carrier, *accepted),
            )

        refreshed = self._load_candidates(task)
        return ScoutRunResult(
            operation_key=task.operation_key.value,
            state=SourceTaskState.COMPLETED,
            discovered_count=len(fetched),
            candidate_count=len(refreshed),
        )

    @activity.defn(name="deliver_scout_continuation")
    async def deliver_scout_continuation(
        self,
        workflow_input: ScoutContinuationWorkflowInput,
        result: ScoutRunResult,
    ) -> str:
        del result
        if self._messenger is None:
            raise ApplicationError(
                "Telegram delivery is not configured in the worker",
                non_retryable=True,
                type="TelegramDeliveryNotConfigured",
            )

        task = self._authorized_task(workflow_input)
        candidates = self._load_candidates(task)
        page = max(0, (len(candidates) - 1) // 10)
        message = build_scout_result_page(
            UiLocale(task.locale),
            candidates,
            task_id=task.id,
            page=page,
        )
        try:
            await self._messenger.edit_message(
                workflow_input.telegram_update_id,
                f"source-task-more-results:{workflow_input.request_key}",
                workflow_input.telegram_chat_id,
                workflow_input.telegram_message_id,
                message,
            )
        except TelegramMessageRetryAfter as error:
            raise ApplicationError(
                "Telegram continuation delivery is rate limited",
                next_retry_delay=timedelta(seconds=error.retry_after_seconds),
                type="TelegramResultRateLimited",
            ) from None
        return "CONFIRMED"

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

    def _authorized_task(
        self,
        workflow_input: ScoutContinuationWorkflowInput,
    ) -> SourceTask:
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
            if task.state is not SourceTaskState.COMPLETED:
                raise RuntimeError("source task is not completed")
            return task

    def _load_candidates(self, task: SourceTask) -> tuple[CandidateContent, ...]:
        with self._session_factory() as session, tenant_transaction(session, task.tenant_id):
            return restore_curator_order(
                self._source_repository.list_candidates(
                    session,
                    task.id,
                    limit=_MAX_CONTINUATION_CANDIDATES,
                )
            )

    def _commit_usage(self, task: SourceTask, request_key: OperationKey) -> None:
        with self._session_factory() as session, tenant_transaction(session, task.tenant_id):
            self._usage_repository.commit(session, request_key)

    def _release_usage(self, task: SourceTask, request_key: OperationKey) -> None:
        with self._session_factory() as session, tenant_transaction(session, task.tenant_id):
            self._usage_repository.release(session, request_key)

    def _release_committed_if_safe(self, task: SourceTask, request_key: OperationKey) -> None:
        # The provider returned a definitive 429/401/403 without post data. Internal
        # scout quota should not be consumed for a continuation that read no posts.
        # UsageRepository cannot transition COMMITTED back to RELEASED, so this is
        # intentionally a no-op after commit; the deterministic request key still
        # prevents double charging if Telegram retries the same callback.
        del task, request_key

    def _retire_continuation(
        self,
        task: SourceTask,
        continuation: ScoutContinuationState,
    ) -> None:
        carrier = _advance_carrier(continuation.carrier, None)
        with self._session_factory() as session, tenant_transaction(session, task.tenant_id):
            self._source_repository.replace_candidates(
                session,
                task_id=task.id,
                tenant_id=task.tenant_id,
                candidates=(carrier,),
            )

    @staticmethod
    def _result(
        task: SourceTask,
        candidates: tuple[CandidateContent, ...],
        *,
        failure_code: str | None = None,
    ) -> ScoutRunResult:
        return ScoutRunResult(
            operation_key=task.operation_key.value,
            state=SourceTaskState.COMPLETED,
            discovered_count=0,
            candidate_count=len(candidates),
            failure_code=failure_code,
        )


def _with_continuation_provenance(
    candidate: CandidateContent,
    continuation: ScoutContinuationState,
) -> CandidateContent:
    metadata = dict(candidate.connector_metadata)
    metadata["retrieval_query"] = continuation.query_variants[0]
    metadata["retrieval_query_variants"] = list(continuation.query_variants)
    metadata["retrieval_relaxation_level"] = continuation.relaxation_level
    metadata["retrieval_specificity"] = continuation.specificity
    metadata["retrieval_language_mode"] = "+".join(continuation.preferred_languages)
    return replace(candidate, connector_metadata=metadata)


def _next_token_from_candidates(candidates: tuple[CandidateContent, ...]) -> str | None:
    for candidate in candidates:
        token = candidate.connector_metadata.get("x_next_token")
        if isinstance(token, str) and token:
            return token
    return None


def _advance_carrier(candidate: CandidateContent, next_token: str | None) -> CandidateContent:
    metadata = dict(candidate.connector_metadata)
    metadata.pop("x_next_token", None)
    if next_token is not None:
        metadata["x_next_token"] = next_token
    return replace(candidate, connector_metadata=metadata)


def _offset_curator_ranks(
    candidates: tuple[CandidateContent, ...],
    offset: int,
) -> tuple[CandidateContent, ...]:
    result: list[CandidateContent] = []
    for index, candidate in enumerate(candidates, start=1):
        metadata = dict(candidate.connector_metadata)
        metadata["curator_rank"] = offset + index
        result.append(replace(candidate, connector_metadata=metadata))
    return tuple(result)
