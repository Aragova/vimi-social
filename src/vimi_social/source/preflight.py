from collections.abc import Callable
from uuid import UUID

from sqlalchemy.orm import Session
from temporalio import activity

from vimi_social.db.tenant import tenant_transaction
from vimi_social.domain.identity import OperationKey
from vimi_social.domain.source import ScoutWorkflowInput, SourceTask
from vimi_social.source.connectors import SourceConnectorRegistry, SourceConnectorUnavailable
from vimi_social.source.repository import SourceTaskRepository


class ScoutSourcePreflightActivities:
    """Validate source routing before any paid user-context provider read."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        registry: SourceConnectorRegistry,
        *,
        source_repository: SourceTaskRepository | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._registry = registry
        self._source_repository = source_repository or SourceTaskRepository()

    @activity.defn(name="validate_scout_sources")
    async def validate_scout_sources(self, workflow_input: ScoutWorkflowInput) -> bool:
        task = self._authorized_task(workflow_input)
        try:
            self._registry.route(task.requested_sources)
        except SourceConnectorUnavailable:
            return False
        return True

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
