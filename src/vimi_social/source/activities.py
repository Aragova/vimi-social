from collections.abc import Callable
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
from vimi_social.source.repository import SourceTaskRepository
from vimi_social.telegram.menus import build_scout_results
from vimi_social.telegram.outgoing import (
    TelegramMessageRetryAfter,
    TelegramMessenger,
    TelegramOutgoingState,
)
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
    ) -> None:
        self._session_factory = session_factory
        self._registry = registry
        self._messenger = messenger
        self._source_repository = source_repository or SourceTaskRepository()
        self._usage_repository = usage_repository or UsageRepository()

    @activity.defn(name="execute_scout_task")
    async def execute_scout_task(self, workflow_input: ScoutWorkflowInput) -> ScoutRunResult:
        task = self._authorized_task(workflow_input)

        with self._session_factory() as session:
            with tenant_transaction(session, task.tenant_id):
                current = self._source_repository.get_by_operation_key(
                    session, task.operation_key
                )
                if current is None:
                    raise RuntimeError("source task disappeared from tenant context")
                if current.state is SourceTaskState.COMPLETED:
                    existing = self._source_repository.list_candidates(
                        session, current.id, limit=100
                    )
                    return ScoutRunResult(
                        operation_key=task.operation_key.value,
                        state=SourceTaskState.COMPLETED,
                        discovered_count=len(existing),
                        candidate_count=len(existing),
                    )
                if current.state is SourceTaskState.FAILED_SAFE:
                    return ScoutRunResult(
                        operation_key=task.operation_key.value,
                        state=SourceTaskState.FAILED_SAFE,
                        discovered_count=0,
                        candidate_count=0,
                        failure_code=current.failure_code,
                    )
                self._source_repository.set_state(
                    session,
                    task.operation_key,
                    SourceTaskState.SCOUTING,
                )
                self._usage_repository.commit(session, task.operation_key)

        request = ScoutSearchRequest(
            intent=task.user_intent,
            requested_sources=task.requested_sources,
            preferred_languages=task.preferred_languages,
            max_results=10,
        )

        try:
            connectors = self._registry.route(request.requested_sources)
            discovered: list[CandidateContent] = []
            for connector in connectors:
                discovered.extend(await connector.search(request))
        except SourceConnectorRateLimited:
            return self._fail_safe(task, "SOURCE_RATE_LIMITED")
        except SourceConnectorRejected:
            return self._fail_safe(task, "SOURCE_ACCESS_REJECTED")
        except SourceConnectorUnavailable:
            return self._fail_safe(task, "SOURCE_UNAVAILABLE")

        normalized = _deduplicate(discovered)
        with self._session_factory() as session:
            with tenant_transaction(session, task.tenant_id):
                persisted = self._source_repository.replace_candidates(
                    session,
                    task_id=task.id,
                    tenant_id=task.tenant_id,
                    candidates=normalized,
                )
                self._source_repository.set_state(
                    session,
                    task.operation_key,
                    SourceTaskState.COMPLETED,
                )

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
            with self._session_factory() as session:
                with tenant_transaction(session, task.tenant_id):
                    candidates = self._source_repository.list_candidates(
                        session,
                        task.id,
                        limit=5,
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

        with self._session_factory() as session:
            with tenant_transaction(session, tenant_id):
                task = self._source_repository.get_by_operation_key(session, operation_key)
                if task is None or task.execution_token != execution_token:
                    raise RuntimeError("source task authority binding mismatch")
                return task

    def _fail_safe(self, task: SourceTask, failure_code: str) -> ScoutRunResult:
        with self._session_factory() as session:
            with tenant_transaction(session, task.tenant_id):
                self._source_repository.set_state(
                    session,
                    task.operation_key,
                    SourceTaskState.FAILED_SAFE,
                    failure_code=failure_code,
                )
        return ScoutRunResult(
            operation_key=task.operation_key.value,
            state=SourceTaskState.FAILED_SAFE,
            discovered_count=0,
            candidate_count=0,
            failure_code=failure_code,
        )


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
