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
from vimi_social.source.repository import SourceTaskRepository
from vimi_social.source.service import SourceTaskService
from vimi_social.telegram.identity import TelegramIdentityResolver, TelegramUpdateGuard
from vimi_social.telegram.models import TelegramUser


def _database_dsn() -> str:
    dsn = os.environ.get("VIMI_TEST_DATABASE_DSN")
    if dsn is None:
        pytest.skip("PostgreSQL integration DSN is not configured")
    return dsn


def _candidate(source_id: str, intent: str) -> CandidateContent:
    return CandidateContent(
        id=None,
        source="x",
        source_id=source_id,
        source_url=f"https://x.com/i/web/status/{source_id}",
        author=f"author-{source_id}",
        published_at=None,
        media_type="video",
        duration_ms=12000,
        width=1080,
        height=1920,
        title=intent,
        caption=intent,
        tags=(),
        engagement={"like_count": 10},
        adult_classification=AdultClassification.UNKNOWN,
        explicitness_score=None,
        provenance_hint="PUBLIC_X_POST_REUSE_RIGHTS_NOT_ESTABLISHED",
        availability="DISCOVERED_METADATA_ONLY",
        connector_metadata={"media_key": f"7_{source_id}"},
    )


class TwoRoundConnector:
    source_name = "x"

    def __init__(self) -> None:
        self.calls = 0

    async def search(self, request: ScoutSearchRequest) -> tuple[CandidateContent, ...]:
        self.calls += 1
        if self.calls == 1:
            return tuple(_candidate(f"1{i:02d}", request.intent) for i in range(6))
        if self.calls == 2:
            return tuple(_candidate(f"2{i:02d}", request.intent) for i in range(20))
        raise AssertionError("Scout must stop after the second paid round reaches the target")


@pytest.mark.asyncio
async def test_scout_keeps_all_results_from_target_round_and_stops_broadening() -> None:
    engine = create_engine(_database_dsn())
    session_factory = sessionmaker[Session](
        bind=engine,
        expire_on_commit=False,
        autoflush=False,
    )
    telegram_user = TelegramUser(
        id=930028101,
        first_name="Recall",
        username="recall_target_integration",
        language_code="en",
    )
    update_id = 830028101
    chat_id = 930028101

    try:
        resolver = TelegramIdentityResolver(session_factory)
        principal = resolver.resolve(telegram_user)
        TelegramUpdateGuard(session_factory).claim(update_id, telegram_user.id)

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
            message_id=928001,
            chat_id=chat_id,
            intent="bangkok night market video",
        )
        assert task is not None

        connector = TwoRoundConnector()
        activities = ScoutActivities(
            session_factory,
            SourceConnectorRegistry([connector]),
            messenger=None,
            retrieval_budget=300,
            retrieval_round_limit=30,
        )
        result = await activities.execute_scout_task(
            ScoutWorkflowInput(
                operation_key=task.operation_key.value,
                execution_token=str(task.execution_token),
            )
        )

        assert connector.calls == 2
        assert result.discovered_count == 26
        assert result.candidate_count == 26

        repository = SourceTaskRepository()
        with (
            session_factory() as session,
            tenant_transaction(session, principal.context.tenant_id),
        ):
            persisted = repository.list_candidates(session, task.id, limit=300)
            assert len(persisted) == 26
    finally:
        engine.dispose()
