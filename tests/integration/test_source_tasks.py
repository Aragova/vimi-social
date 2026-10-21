import os
from uuid import UUID

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from vimi_social.auth.context import ExecutionContext
from vimi_social.domain.identity import TenantId
from vimi_social.domain.international import AgeEligibility, IanaTimezone, UiLocale
from vimi_social.source.models import SourceTaskQueryTooLong
from vimi_social.source.repository import SourceTaskRepository
from vimi_social.telegram.identity import TelegramPrincipal


def _database_dsn() -> str:
    dsn = os.environ.get("VIMI_TEST_DATABASE_DSN")
    if dsn is None:
        pytest.skip("PostgreSQL integration DSN is not configured")
    return dsn


def _principal(session: Session, telegram_user_id: int) -> TelegramPrincipal:
    row = session.execute(
        text(
            """
            SELECT * FROM resolve_or_create_telegram_context(
                :telegram_user_id,
                NULL,
                'en'
            )
            """
        ),
        {"telegram_user_id": telegram_user_id},
    ).mappings().one()
    user_id = row["resolved_user_id"]
    tenant_id = row["resolved_tenant_id"]
    assert isinstance(user_id, UUID)
    assert isinstance(tenant_id, UUID)
    return TelegramPrincipal(
        user_id=user_id,
        context=ExecutionContext(
            tenant_id=TenantId(tenant_id),
            actor_subject=f"telegram:{telegram_user_id}",
        ),
        locale=UiLocale.EN,
        timezone=IanaTimezone("UTC"),
        region=None,
        age_eligibility=AgeEligibility.UNKNOWN,
    )


def test_ai_search_intake_persists_one_task_for_one_telegram_update() -> None:
    engine = create_engine(_database_dsn())
    factory = sessionmaker[Session](bind=engine, expire_on_commit=False, autoflush=False)
    repository = SourceTaskRepository(factory)
    try:
        with Session(engine) as session, session.begin():
            principal = _principal(session, 920000001)

        assert repository.begin_ai_search(820000000, principal) is True
        task = repository.consume_ai_search_text(820000001, principal, "find fresh videos")
        assert task is not None
        assert task.query_text == "find fresh videos"
        assert task.origin_key == "telegram:update:820000001:source-task"

        duplicate = repository.consume_ai_search_text(
            820000001,
            principal,
            "find fresh videos",
        )
        assert duplicate is not None
        assert duplicate.id == task.id
    finally:
        engine.dispose()


def test_replayed_ai_callback_cannot_reopen_consumed_intake() -> None:
    engine = create_engine(_database_dsn())
    factory = sessionmaker[Session](bind=engine, expire_on_commit=False, autoflush=False)
    repository = SourceTaskRepository(factory)
    try:
        with Session(engine) as session, session.begin():
            principal = _principal(session, 920000004)

        assert repository.begin_ai_search(820000020, principal) is True
        assert repository.begin_ai_search(820000020, principal) is True

        task = repository.consume_ai_search_text(820000021, principal, "first query")
        assert task is not None

        assert repository.begin_ai_search(820000020, principal) is False
        assert repository.consume_ai_search_text(
            820000022,
            principal,
            "unrelated later text",
        ) is None
    finally:
        engine.dispose()


def test_selecting_other_source_closes_ai_intake_and_blocks_stale_replay() -> None:
    engine = create_engine(_database_dsn())
    factory = sessionmaker[Session](bind=engine, expire_on_commit=False, autoflush=False)
    repository = SourceTaskRepository(factory)
    try:
        with Session(engine) as session, session.begin():
            principal = _principal(session, 920000005)

        assert repository.begin_ai_search(820000030, principal) is True
        assert repository.clear_pending_intake(820000031, principal) is True
        assert repository.begin_ai_search(820000030, principal) is False
        assert repository.consume_ai_search_text(
            820000032,
            principal,
            "must not become an AI task",
        ) is None

        assert repository.begin_ai_search(820000033, principal) is True
        task = repository.consume_ai_search_text(820000034, principal, "new search")
        assert task is not None
        assert task.query_text == "new search"
    finally:
        engine.dispose()


def test_oversized_active_query_is_recoverable_and_preserves_intake() -> None:
    engine = create_engine(_database_dsn())
    factory = sessionmaker[Session](bind=engine, expire_on_commit=False, autoflush=False)
    repository = SourceTaskRepository(factory)
    try:
        with Session(engine) as session, session.begin():
            principal = _principal(session, 920000002)

        assert repository.begin_ai_search(820000010, principal) is True
        with pytest.raises(SourceTaskQueryTooLong):
            repository.consume_ai_search_text(820000011, principal, "x" * 2001)

        task = repository.consume_ai_search_text(820000012, principal, "short query")
        assert task is not None
        assert task.query_text == "short query"
    finally:
        engine.dispose()


def test_oversized_text_outside_ai_search_is_ignored() -> None:
    engine = create_engine(_database_dsn())
    factory = sessionmaker[Session](bind=engine, expire_on_commit=False, autoflush=False)
    repository = SourceTaskRepository(factory)
    try:
        with Session(engine) as session, session.begin():
            principal = _principal(session, 920000003)

        assert repository.consume_ai_search_text(820000004, principal, "x" * 2001) is None
    finally:
        engine.dispose()


def test_source_task_table_fails_closed_without_tenant_context() -> None:
    engine = create_engine(_database_dsn())
    try:
        with Session(engine) as session, session.begin():
            count = session.execute(text("SELECT count(*) FROM source_task")).scalar_one()
        assert count == 0
    finally:
        engine.dispose()
