import os
from uuid import uuid4

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
from vimi_social.source.continuation import ScoutContinuationActivities
from vimi_social.source.continuation_state import find_scout_continuation_state
from vimi_social.source.scout_attempts import ScoutAttemptStore
from vimi_social.source.service import SourceTaskService
from vimi_social.telegram.identity import TelegramIdentityResolver, TelegramUpdateGuard
from vimi_social.telegram.models import TelegramUser


def _database_dsn() -> str:
    dsn = os.environ.get("VIMI_TEST_DATABASE_DSN")
    if dsn is None:
        pytest.skip("PostgreSQL integration DSN is not configured")
    return dsn


def _candidate(source_id: str, *, next_token: str) -> CandidateContent:
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
        title="bangkok night market video",
        caption="bangkok night market video",
        tags=(),
        engagement={"like_count": 10},
        adult_classification=AdultClassification.UNKNOWN,
        explicitness_score=None,
        provenance_hint="PUBLIC_X_POST_REUSE_RIGHTS_NOT_ESTABLISHED",
        availability="DISCOVERED_METADATA_ONLY",
        connector_metadata={
            "media_key": f"7_{source_id}",
            "x_search_scope": "all",
            "x_next_token": next_token,
        },
    )


class PagedConnector:
    source_name = "x"

    def __init__(self) -> None:
        self.tokens: list[str | None] = []

    async def search(self, request: ScoutSearchRequest) -> tuple[CandidateContent, ...]:
        self.tokens.append(request.pagination_token)
        if request.pagination_token is None:
            return tuple(_candidate(f"1{i:02d}", next_token="page-2") for i in range(10))
        if request.pagination_token == "page-2":
            assert request.search_scope == "all"
            return tuple(_candidate(f"2{i:02d}", next_token="page-3") for i in range(10))
        raise AssertionError(f"unexpected continuation token: {request.pagination_token}")


@pytest.mark.asyncio
async def test_scout_continuation_reuses_token_once_and_appends_results() -> None:
    engine = create_engine(_database_dsn())
    session_factory = sessionmaker[Session](
        bind=engine,
        expire_on_commit=False,
        autoflush=False,
    )
    telegram_user = TelegramUser(
        id=920000201,
        first_name="Continuation",
        username="continuation_integration",
        language_code="en",
    )
    chat_id = 920000201
    initial_update_id = 820000201

    try:
        principal = TelegramIdentityResolver(session_factory).resolve(telegram_user)
        TelegramUpdateGuard(session_factory).claim(initial_update_id, telegram_user.id)
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
            update_id=initial_update_id,
            message_id=201,
            chat_id=chat_id,
            intent="bangkok night market video",
        )
        assert task is not None

        connector = PagedConnector()
        registry = SourceConnectorRegistry([connector])
        initial = ScoutActivities(
            session_factory,
            registry,
            messenger=None,
            retrieval_budget=30,
            retrieval_round_limit=30,
        )
        first_result = await initial.execute_scout_task(
            ScoutWorkflowInput(
                operation_key=task.operation_key.value,
                execution_token=str(task.execution_token),
            )
        )
        assert first_result.candidate_count == 10
        assert connector.tokens == [None]

        first_click = service.prepare_ai_search_continuation(
            principal,
            task_id=task.id,
            update_id=820000202,
            message_id=301,
            chat_id=chat_id,
        )
        second_click = service.prepare_ai_search_continuation(
            principal,
            task_id=task.id,
            update_id=820000203,
            message_id=301,
            chat_id=chat_id,
        )
        assert first_click is not None
        assert second_click is not None
        assert first_click.request_key == second_click.request_key

        continuation = ScoutContinuationActivities(
            session_factory,
            registry,
            messenger=None,
            batch_size=30,
        )
        second_result = await continuation.continue_scout_results(first_click)

        assert connector.tokens == [None, "page-2"]
        assert second_result.candidate_count == 20
        candidates = service.get_ai_search_candidates(principal, task.id)
        assert candidates is not None
        assert len(candidates) == 20
        assert [candidate.source_id for candidate in candidates[:10]] == [
            f"1{i:02d}" for i in range(10)
        ]
        assert [candidate.source_id for candidate in candidates[10:]] == [
            f"2{i:02d}" for i in range(10)
        ]
        assert [candidate.connector_metadata["curator_rank"] for candidate in candidates] == list(
            range(1, 21)
        )
        state = find_scout_continuation_state(candidates)
        assert state is not None
        assert state.next_token == "page-3"

        third_click = service.prepare_ai_search_continuation(
            principal,
            task_id=task.id,
            update_id=820000204,
            message_id=301,
            chat_id=chat_id,
        )
        assert third_click is not None
        assert third_click.request_key != first_click.request_key

        # Simulate a worker that crossed the paid-I/O fence and then disappeared
        # before persisting page 3. A later attempt must retire the token without
        # issuing another X request.
        abandoned_attempt = uuid4()
        attempt_store = ScoutAttemptStore()
        with (
            session_factory() as session,
            tenant_transaction(session, principal.context.tenant_id),
        ):
            assert attempt_store.claim_completed_continuation(
                session,
                operation_key=task.operation_key,
                attempt_token=abandoned_attempt,
            )

        before_retry = list(connector.tokens)
        ambiguous = await continuation.continue_scout_results(third_click)
        assert ambiguous.failure_code == "CONTINUATION_ATTEMPT_AMBIGUOUS"
        assert connector.tokens == before_retry

        after_ambiguous = service.get_ai_search_candidates(principal, task.id)
        assert after_ambiguous is not None
        assert find_scout_continuation_state(after_ambiguous) is None
    finally:
        engine.dispose()