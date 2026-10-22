import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from vimi_social.db.tenant import tenant_transaction
from vimi_social.domain.source import CandidateContent, ScoutSearchRequest, ScoutWorkflowInput
from vimi_social.source.activities import ScoutActivities
from vimi_social.source.connectors import SourceConnectorRegistry
from vimi_social.source.repository import SourceTaskRepository
from vimi_social.source.scout_attempts import ScoutAttemptStore
from vimi_social.source.service import SourceTaskService
from vimi_social.telegram.identity import TelegramIdentityResolver, TelegramUpdateGuard
from vimi_social.telegram.models import TelegramUser
from vimi_social.usage.repository import UsageRepository


def _database_dsn() -> str:
    dsn = os.environ.get("VIMI_TEST_DATABASE_DSN")
    if dsn is None:
        pytest.skip("PostgreSQL integration DSN is not configured")
    return dsn


class CountingConnector:
    source_name = "x"

    def __init__(self) -> None:
        self.calls = 0

    async def search(self, _: ScoutSearchRequest) -> tuple[CandidateContent, ...]:
        self.calls += 1
        return ()


def _session_factory() -> tuple[object, sessionmaker[Session]]:
    engine = create_engine(_database_dsn())
    return engine, sessionmaker[Session](
        bind=engine,
        expire_on_commit=False,
        autoflush=False,
    )


def test_pending_ai_search_conversation_is_consumed_once() -> None:
    engine, session_factory = _session_factory()
    try:
        resolver = TelegramIdentityResolver(session_factory)
        principal = resolver.resolve(
            TelegramUser(
                id=920000101,
                first_name="Conversation",
                language_code="en",
            )
        )
        guard = TelegramUpdateGuard(session_factory)
        assert guard.claim(820000101, 920000101).value == "CLAIMED"

        service = SourceTaskService(session_factory)
        service.begin_ai_search(principal, chat_id=920000101)
        first = service.submit_ai_search_intent(
            principal,
            update_id=820000101,
            message_id=101,
            chat_id=920000101,
            intent="first intent",
        )
        assert first is not None

        second = service.submit_ai_search_intent(
            principal,
            update_id=820000102,
            message_id=102,
            chat_id=920000101,
            intent="follow-up message must not become a second search",
        )
        assert second is None

        with session_factory() as session, tenant_transaction(session, principal.context.tenant_id):
            task_count = session.execute(
                text("SELECT count(*) FROM source_task WHERE actor_user_id = :actor_user_id"),
                {"actor_user_id": str(principal.user_id)},
            ).scalar_one()
            reservation_count = session.execute(
                text(
                    """
                    SELECT count(*)
                    FROM usage_reservation
                    WHERE tenant_id = :tenant_id
                      AND metric = 'scout_run'
                    """
                ),
                {"tenant_id": str(principal.context.tenant_id.value)},
            ).scalar_one()

        assert task_count == 1
        assert reservation_count == 1
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_retry_fences_ambiguous_inflight_scout_without_second_connector_call() -> None:
    engine, session_factory = _session_factory()
    try:
        resolver = TelegramIdentityResolver(session_factory)
        principal = resolver.resolve(
            TelegramUser(
                id=920000111,
                first_name="Fence",
                language_code="en",
            )
        )
        update_id = 820000111
        TelegramUpdateGuard(session_factory).claim(update_id, 920000111)

        service = SourceTaskService(session_factory)
        service.begin_ai_search(principal, chat_id=920000111)
        task = service.submit_ai_search_intent(
            principal,
            update_id=update_id,
            message_id=111,
            chat_id=920000111,
            intent="fitness video",
        )
        assert task is not None

        first_attempt_token = uuid4()
        attempt_store = ScoutAttemptStore()
        usage = UsageRepository()
        with session_factory() as session, tenant_transaction(session, principal.context.tenant_id):
            claim = attempt_store.claim(
                session,
                operation_key=task.operation_key,
                attempt_token=first_attempt_token,
            )
            assert claim.claimed
            usage.commit(session, task.operation_key)

        connector = CountingConnector()
        activities = ScoutActivities(
            session_factory,
            SourceConnectorRegistry([connector]),
            messenger=None,
        )
        result = await activities.execute_scout_task(
            ScoutWorkflowInput(
                operation_key=task.operation_key.value,
                execution_token=str(task.execution_token),
            )
        )

        assert result.state.value == "UNKNOWN"
        assert result.failure_code == "SCOUT_ATTEMPT_AMBIGUOUS"
        assert connector.calls == 0

        repository = SourceTaskRepository()
        with session_factory() as session, tenant_transaction(session, principal.context.tenant_id):
            stored = repository.get_by_operation_key(session, task.operation_key)
            assert stored is not None
            assert stored.state.value == "UNKNOWN"
            assert not attempt_store.lock_owned_attempt(
                session,
                operation_key=task.operation_key,
                attempt_token=first_attempt_token,
            )
    finally:
        engine.dispose()
