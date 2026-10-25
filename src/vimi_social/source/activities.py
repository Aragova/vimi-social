from collections.abc import Callable
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
)
from vimi_social.source.curator import CandidateCurator, restore_curator_order
from vimi_social.source.query_planner import MultilingualQueryPlanner
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
        visual_relevance_weight: float = 0.15,
        semantic_minimum_relevance: float = 0.0,
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
        self._visual_relevance_weight = max(0.0, min(0.40, visual_relevance_weight))
        self._semantic_minimum_relevance = max(0.0, min(1.0, semantic_minimum_relevance))

    @activity.defn(name="execute_scout_task")
    async def execute_scout_task(self, workflow_input: ScoutWorkflowInput) -> ScoutRunResult:
        task = self._authorized_task(workflow_input)

        # Route before any paid query expansion. Unsupported source requests fail
        # without spending translation-provider credits.
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

        # Query expansion is fenced behind the durable Scout claim. A terminal
        # retry returns above and an ambiguous in-flight retry becomes UNKNOWN
        # rather than repeating translation or source-search side effects.
        query_plan = await self._query_planner.plan(
            task.user_intent,
            task.preferred_languages,
        )
        request = ScoutSearchRequest(
            intent=task.user_intent,
            requested_sources=task.requested_sources,
            preferred_languages=task.preferred_languages,
            query_variants=query_plan.query_variants,
            max_results=10,
        )

        try:
            discovered: list[CandidateContent] = []
            for connector in connectors:
                discovered.extend(await connector.search(request))
        except SourceConnectorRateLimited:
            return self._fail_safe(
                task,
                "SOURCE_RATE_LIMITED",
                attempt_token=attempt_token,
            )
        except SourceConnectorRejected:
            return self._fail_safe(
                task,
                "SOURCE_ACCESS_REJECTED",
                attempt_token=attempt_token,
            )
        except SourceConnectorUnavailable:
            return self._fail_safe(
                task,
                "SOURCE_UNAVAILABLE",
                attempt_token=attempt_token,
            )

        normalized = _deduplicate(discovered)
        semantic_scores: tuple[float, ...] | None = None
        if self._semantic_scorer is not None and normalized:
            try:
                semantic_scores = await self._semantic_scorer.score_candidates(
                    query_plan.query_variants,
                    normalized,
                )
            except SemanticRelevanceUnavailable:
                semantic_scores = None

        visual_scores: tuple[float | None, ...] | None = None
        if self._visual_scorer is not None and normalized:
            try:
                visual_scores = await self._visual_scorer.score_preview_candidates(
                    query_plan.query_variants,
                    normalized,
                )
            except VisualRelevanceUnavailable:
                visual_scores = None

        curated = self._curator.rank(
            normalized,
            query_variants=query_plan.query_variants,
            preferred_languages=task.preferred_languages,
            limit=request.max_results,
            semantic_scores=semantic_scores,
            visual_scores=visual_scores,
            visual_weight=self._visual_relevance_weight,
            minimum_relevance=self._semantic_minimum_relevance,
        )
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
                        limit=10,
                    )
                )

        message = build_scout_results(UiLocale(task.locale), result, candidates)
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
            candidates = self._source_repository.list_candidates(session, task.id, limit=100)
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
