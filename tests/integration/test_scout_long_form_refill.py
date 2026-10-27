import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from vimi_social.db.tenant import tenant_transaction
from vimi_social.domain.source import (
    AdultClassification,
    CandidateContent,
    ScoutRunResult,
    ScoutSearchRequest,
    ScoutWorkflowInput,
)
from vimi_social.source.activities import ScoutActivities
from vimi_social.source.candidate_filter import FilteringCandidateCurator
from vimi_social.source.connectors import SourceConnectorRegistry, SourceSearchCandidates
from vimi_social.source.repository import SourceTaskRepository
from vimi_social.source.service import SourceTaskService
from vimi_social.telegram.identity import TelegramIdentityResolver, TelegramUpdateGuard
from vimi_social.telegram.models import TelegramUser


def _database_dsn() -> str:
    dsn = os.environ.get("VIMI_TEST_DATABASE_DSN")
    if dsn is None:
        pytest.skip("PostgreSQL integration DSN is not configured")
    return dsn


def _candidate(source_id: str, *, duration_ms: int, text_value: str) -> CandidateContent:
    return CandidateContent(
        id=None,
        source="x",
        source_id=source_id,
        source_url=f"https://x.com/i/web/status/{source_id}",
        author=f"author-{source_id}",
        published_at=None,
        media_type="video",
        duration_ms=duration_ms,
        width=1920,
        height=1080,
        title=text_value,
        caption=text_value,
        tags=(),
        engagement={"like_count": 10},
        adult_classification=AdultClassification.UNKNOWN,
        explicitness_score=None,
        provenance_hint="PUBLIC_X_POST_REUSE_RIGHTS_NOT_ESTABLISHED",
        availability="DISCOVERED_METADATA_ONLY",
        connector_metadata={"media_key": f"7_{source_id}"},
    )


class LongFormRefillConnector:
    source_name = "x"

    def __init__(self) -> None:
        self.requests: list[ScoutSearchRequest] = []

    async def search(self, request: ScoutSearchRequest) -> tuple[CandidateContent, ...]:
        self.requests.append(request)
        if request.pagination_token is None:
            shorts = tuple(
                _candidate(
                    f"short-{index}",
                    duration_ms=15_000,
                    text_value=f"short promo clip {index}",
                )
                for index in range(12)
            )
            return SourceSearchCandidates(shorts, next_token="page-2")
        if request.pagination_token == "page-2":
            long_form = tuple(
                _candidate(
                    f"long-{index}",
                    duration_ms=600_000 + index * 1_000,
                    text_value=f"bangkok night market longform scene {index}",
                )
                for index in range(10)
            )
            return SourceSearchCandidates(long_form, next_token="page-3")
        raise AssertionError("Scout must stop refilling once ten accepted candidates exist")


class BudgetCappedRefillConnector:
    source_name = "x"

    def __init__(self) -> None:
        self.requests: list[ScoutSearchRequest] = []

    async def search(self, request: ScoutSearchRequest) -> tuple[CandidateContent, ...]:
        self.requests.append(request)
        call = len(self.requests)
        if call > 2:
            raise AssertionError("Scout must not exceed the reserved retrieval budget")
        token = None if call == 1 else "page-2"
        assert request.pagination_token == token
        candidates = (
            _candidate(
                f"long-budget-{call}",
                duration_ms=600_000,
                text_value=f"long budget candidate unique {call}",
            ),
            *(
                _candidate(
                    f"short-budget-{call}-{index}",
                    duration_ms=10_000,
                    text_value=f"short budget spam {call} {index}",
                )
                for index in range(10)
            ),
        )
        return SourceSearchCandidates(candidates, next_token=f"page-{call + 1}")


async def _run_scout(
    connector: LongFormRefillConnector | BudgetCappedRefillConnector,
    *,
    retrieval_budget: int,
    telegram_user_id: int,
    update_id: int,
    message_id: int,
) -> tuple[ScoutRunResult, tuple[CandidateContent, ...]]:
    engine = create_engine(_database_dsn())
    session_factory = sessionmaker[Session](
        bind=engine,
        expire_on_commit=False,
        autoflush=False,
    )
    telegram_user = TelegramUser(
        id=telegram_user_id,
        first_name="LongForm",
        username=f"long_form_refill_{telegram_user_id}",
        language_code="en",
    )

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
        service.begin_ai_search(principal, chat_id=telegram_user_id)
        task = service.submit_ai_search_intent(
            principal,
            update_id=update_id,
            message_id=message_id,
            chat_id=telegram_user_id,
            intent="bangkok night market long video",
        )
        assert task is not None

        activities = ScoutActivities(
            session_factory,
            SourceConnectorRegistry([connector]),
            messenger=None,
            curator=FilteringCandidateCurator(),
            retrieval_budget=retrieval_budget,
            retrieval_round_limit=30,
        )
        result = await activities.execute_scout_task(
            ScoutWorkflowInput(
                operation_key=task.operation_key.value,
                execution_token=str(task.execution_token),
            )
        )

        repository = SourceTaskRepository()
        with (
            session_factory() as session,
            tenant_transaction(session, principal.context.tenant_id),
        ):
            persisted = repository.list_candidates(session, task.id, limit=300)
        return result, persisted
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_scout_refills_same_x_round_until_long_form_target_is_met() -> None:
    connector = LongFormRefillConnector()
    result, persisted = await _run_scout(
        connector,
        retrieval_budget=90,
        telegram_user_id=930038201,
        update_id=830038201,
        message_id=938201,
    )

    assert len(connector.requests) == 2
    assert connector.requests[0].pagination_token is None
    assert connector.requests[1].pagination_token == "page-2"
    assert result.discovered_count == 22
    assert result.candidate_count == 10
    assert len(persisted) == 10
    assert all(
        candidate.duration_ms is not None and candidate.duration_ms >= 60_000
        for candidate in persisted
    )
    assert all(
        candidate.connector_metadata.get("x_continuation_generation") == 1
        for candidate in persisted
    )


@pytest.mark.asyncio
async def test_scout_refill_stops_at_existing_paid_read_budget() -> None:
    connector = BudgetCappedRefillConnector()
    result, persisted = await _run_scout(
        connector,
        retrieval_budget=60,
        telegram_user_id=930038202,
        update_id=830038202,
        message_id=938202,
    )

    assert len(connector.requests) == 2
    assert [request.max_results for request in connector.requests] == [30, 30]
    assert result.candidate_count == 2
    assert len(persisted) == 2
    assert all(candidate.duration_ms == 600_000 for candidate in persisted)
