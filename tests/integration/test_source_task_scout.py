import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from vimi_social.db.tenant import tenant_transaction
from vimi_social.domain.source import (
    AdultClassification,
    CandidateContent,
    ScoutSearchRequest,
    ScoutWorkflowInput,
)
from vimi_social.source.activities import ScoutActivities
from vimi_social.source.connectors import SourceConnectorRegistry
from vimi_social.source.query_planner import MultilingualQueryPlanner
from vimi_social.source.repository import SourceTaskRepository
from vimi_social.source.service import SourceTaskService
from vimi_social.telegram.identity import TelegramIdentityResolver, TelegramUpdateGuard
from vimi_social.telegram.models import TelegramUser


def _database_dsn() -> str:
    dsn = os.environ.get("VIMI_TEST_DATABASE_DSN")
    if dsn is None:
        pytest.skip("PostgreSQL integration DSN is not configured")
    return dsn


class FakeXConnector:
    source_name = "x"

    def __init__(self) -> None:
        self.calls = 0
        self.query_variants: list[tuple[str, ...]] = []

    async def search(self, request: ScoutSearchRequest) -> tuple[CandidateContent, ...]:
        self.calls += 1
        self.query_variants.append(request.query_variants)
        return (
            CandidateContent(
                id=None,
                source="x",
                source_id="987654321",
                source_url="https://x.com/i/web/status/987654321",
                author="42",
                published_at=None,
                media_type="video",
                duration_ms=12000,
                width=1080,
                height=1920,
                title=request.intent,
                caption=request.intent,
                tags=(),
                engagement={"like_count": 12},
                adult_classification=AdultClassification.UNKNOWN,
                explicitness_score=None,
                provenance_hint="PUBLIC_X_POST_REUSE_RIGHTS_NOT_ESTABLISHED",
                availability="DISCOVERED_METADATA_ONLY",
                connector_metadata={"media_key": "7_1"},
            ),
        )


class CountingTranslator:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def translate_to_english(self, intent: str) -> str | None:
        self.calls.append(intent)
        if intent == "Найди видео про ночной Бангкок":
            return "Bangkok night"
        if intent == "Найди видео про ночной":
            return "night"
        raise AssertionError(f"unexpected translation input: {intent}")


@pytest.mark.asyncio
async def test_ai_search_task_is_durable_metered_and_activity_retry_is_idempotent() -> None:
    engine = create_engine(_database_dsn())
    session_factory = sessionmaker[Session](
        bind=engine,
        expire_on_commit=False,
        autoflush=False,
    )
    telegram_user = TelegramUser(
        id=920000001,
        first_name="Scout",
        username="scout_integration",
        language_code="en",
    )
    update_id = 820000001
    chat_id = 920000001
    message_id = 77

    try:
        resolver = TelegramIdentityResolver(session_factory)
        principal = resolver.resolve(telegram_user)
        guard = TelegramUpdateGuard(session_factory)
        assert guard.claim(update_id, telegram_user.id).value == "CLAIMED"

        with (
            session_factory() as session,
            tenant_transaction(session, principal.context.tenant_id),
        ):
            session.execute(
                text(
                    """
                    INSERT INTO usage_capacity (tenant_id, metric, quota)
                    VALUES (:tenant_id, 'scout_run', 5)
                    ON CONFLICT (tenant_id, metric) DO UPDATE
                    SET quota = GREATEST(usage_capacity.quota, 5)
                    """
                ),
                {"tenant_id": str(principal.context.tenant_id.value)},
            )

        service = SourceTaskService(session_factory)
        service.begin_ai_search(principal, chat_id=chat_id)
        task = service.submit_ai_search_intent(
            principal,
            update_id=update_id,
            message_id=message_id,
            chat_id=chat_id,
            intent="Найди видео про ночной Бангкок",
        )
        assert task is not None

        duplicate = service.submit_ai_search_intent(
            principal,
            update_id=update_id,
            message_id=message_id,
            chat_id=chat_id,
            intent="Найди видео про ночной Бангкок",
        )
        assert duplicate is not None
        assert duplicate.id == task.id

        connector = FakeXConnector()
        translator = CountingTranslator()
        activities = ScoutActivities(
            session_factory,
            SourceConnectorRegistry([connector]),
            messenger=None,
            query_planner=MultilingualQueryPlanner(translator),
        )
        workflow_input = ScoutWorkflowInput(
            operation_key=task.operation_key.value,
            execution_token=str(task.execution_token),
        )
        first_result = await activities.execute_scout_task(workflow_input)
        second_result = await activities.execute_scout_task(workflow_input)

        assert first_result.candidate_count == 1
        assert second_result.candidate_count == 1
        assert connector.calls == 4
        assert connector.query_variants == [
            ("ночной Бангкок",),
            ("ночной Бангкок", "Bangkok night"),
            ("ночной",),
            ("ночной", "night"),
        ]
        assert translator.calls == [
            "Найди видео про ночной Бангкок",
            "Найди видео про ночной",
        ]

        repository = SourceTaskRepository()
        with (
            session_factory() as session,
            tenant_transaction(session, principal.context.tenant_id),
        ):
            stored = repository.get_by_operation_key(session, task.operation_key)
            assert stored is not None
            assert stored.state.value == "COMPLETED"
            candidates = repository.list_candidates(session, task.id)
            assert len(candidates) == 1

            counters = session.execute(
                text(
                    """
                    SELECT reserved, committed
                    FROM usage_capacity
                    WHERE tenant_id = :tenant_id AND metric = 'scout_run'
                    """
                ),
                {"tenant_id": str(principal.context.tenant_id.value)},
            ).one()
            assert counters.reserved == 0
            assert counters.committed == 1

            reservation_state = session.execute(
                text(
                    """
                    SELECT state
                    FROM usage_reservation
                    WHERE operation_key = :operation_key
                    """
                ),
                {"operation_key": task.operation_key.value},
            ).scalar_one()
            assert reservation_state == "COMMITTED"

            charges = session.execute(
                text(
                    """
                    SELECT count(*)
                    FROM usage_ledger
                    WHERE operation_key = :operation_key
                      AND entry_kind = 'CHARGE'
                    """
                ),
                {"operation_key": task.operation_key.value},
            ).scalar_one()
            assert charges == 1
    finally:
        engine.dispose()


def test_source_task_is_not_visible_from_another_tenant_context() -> None:
    engine = create_engine(_database_dsn())
    session_factory = sessionmaker[Session](
        bind=engine,
        expire_on_commit=False,
        autoflush=False,
    )
    try:
        resolver = TelegramIdentityResolver(session_factory)
        first = resolver.resolve(
            TelegramUser(
                id=920000011,
                first_name="One",
                language_code="en",
            )
        )
        second = resolver.resolve(
            TelegramUser(
                id=920000012,
                first_name="Two",
                language_code="en",
            )
        )
        update_id = 820000011
        TelegramUpdateGuard(session_factory).claim(update_id, 920000011)

        with session_factory() as session, tenant_transaction(session, first.context.tenant_id):
            session.execute(
                text(
                    """
                    INSERT INTO usage_capacity (tenant_id, metric, quota)
                    VALUES (:tenant_id, 'scout_run', 2)
                    ON CONFLICT (tenant_id, metric) DO NOTHING
                    """
                ),
                {"tenant_id": str(first.context.tenant_id.value)},
            )

        service = SourceTaskService(session_factory)
        service.begin_ai_search(first, chat_id=920000011)
        task = service.submit_ai_search_intent(
            first,
            update_id=update_id,
            message_id=88,
            chat_id=920000011,
            intent="tenant isolation",
        )
        assert task is not None

        repository = SourceTaskRepository()
        with session_factory() as session, tenant_transaction(session, second.context.tenant_id):
            assert repository.get_by_operation_key(session, task.operation_key) is None
    finally:
        engine.dispose()
