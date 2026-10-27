import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from vimi_social.db.tenant import tenant_transaction
from vimi_social.domain.interest import XInterestSnapshot, XInterestSyncState
from vimi_social.domain.source import ScoutWorkflowInput
from vimi_social.publication.x_adapter import EnvironmentCredentialResolver
from vimi_social.source.interest_activities import XInterestProfileActivities
from vimi_social.source.interest_profile import InterestProfileDraft
from vimi_social.source.interest_repository import UserInterestProfileRepository
from vimi_social.source.x_user_context import XUserContextClient
from vimi_social.telegram.identity import TelegramIdentityResolver
from vimi_social.telegram.models import TelegramUser


def _database_dsn() -> str:
    dsn = os.environ.get("VIMI_TEST_DATABASE_DSN")
    if dsn is None:
        pytest.skip("PostgreSQL integration DSN is not configured")
    return dsn


class _StaticCredentialResolver(EnvironmentCredentialResolver):
    def resolve(self, credential_ref: str) -> str:
        assert credential_ref == "env:VIMI_DEST_X_TEST_TOKEN"
        return "user-token"


class _CountingEmptyXUserContextClient(XUserContextClient):
    def __init__(self) -> None:
        self.calls = 0

    async def fetch_snapshot(self, access_token: str) -> XInterestSnapshot:
        assert access_token == "user-token"
        self.calls += 1
        return XInterestSnapshot(user_id="x-user-empty")

    async def aclose(self) -> None:
        return None


def test_user_bound_x_account_and_aggregate_profile_round_trip() -> None:
    engine = create_engine(_database_dsn())
    session_factory = sessionmaker[Session](
        bind=engine,
        expire_on_commit=False,
        autoflush=False,
    )
    try:
        principal = TelegramIdentityResolver(session_factory).resolve(
            TelegramUser(
                id=970040001,
                first_name="Taste",
                language_code="en",
            )
        )
        tenant_id = principal.context.tenant_id
        account_id = uuid4()
        repository = UserInterestProfileRepository()

        with session_factory() as session, tenant_transaction(session, tenant_id):
            session.execute(
                text(
                    """
                    INSERT INTO destination_account (
                        id, tenant_id, platform, external_account_id, display_name,
                        credential_ref, state, connected_user_id
                    ) VALUES (
                        :id, :tenant_id, 'x', 'x-user-test', 'Personal X',
                        'env:VIMI_DEST_X_TEST_TOKEN', 'ACTIVE', :user_id
                    )
                    """
                ),
                {
                    "id": str(account_id),
                    "tenant_id": str(tenant_id.value),
                    "user_id": str(principal.user_id),
                },
            )
            bindings = repository.active_x_accounts_for_user(
                session,
                user_id=principal.user_id,
            )
            assert len(bindings) == 1
            assert bindings[0].id == account_id

            stored = repository.upsert(
                session,
                tenant_id=tenant_id,
                user_id=principal.user_id,
                destination_account_id=account_id,
                external_account_id="x-user-test",
                draft=InterestProfileDraft(
                    term_weights={"twink": 1.0},
                    hashtag_weights={"twink": 0.9},
                    author_weights={"creator-1": 0.8},
                    source_stats={"bookmarks": 4, "likes": 3},
                    sample_size=7,
                ),
            )
            assert stored.sample_size == 7

        with session_factory() as session, tenant_transaction(session, tenant_id):
            loaded = repository.get(session, user_id=principal.user_id)
            assert loaded is not None
            assert loaded.destination_account_id == account_id
            assert loaded.term_weights == {"twink": 1.0}
            assert loaded.source_stats == {"bookmarks": 4, "likes": 3}
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_successful_empty_snapshot_is_cached_without_second_x_read() -> None:
    engine = create_engine(_database_dsn())
    session_factory = sessionmaker[Session](
        bind=engine,
        expire_on_commit=False,
        autoflush=False,
    )
    client = _CountingEmptyXUserContextClient()
    try:
        principal = TelegramIdentityResolver(session_factory).resolve(
            TelegramUser(
                id=970040002,
                first_name="Empty Taste",
                language_code="en",
            )
        )
        tenant_id = principal.context.tenant_id
        account_id = uuid4()
        operation_key = f"taste-empty:{uuid4()}"

        with session_factory() as session, tenant_transaction(session, tenant_id):
            session.execute(
                text(
                    """
                    INSERT INTO destination_account (
                        id, tenant_id, platform, external_account_id, display_name,
                        credential_ref, state, connected_user_id
                    ) VALUES (
                        :id, :tenant_id, 'x', 'x-user-empty', 'Empty Personal X',
                        'env:VIMI_DEST_X_TEST_TOKEN', 'ACTIVE', :user_id
                    )
                    """
                ),
                {
                    "id": str(account_id),
                    "tenant_id": str(tenant_id.value),
                    "user_id": str(principal.user_id),
                },
            )
            execution_token = session.execute(
                text(
                    """
                    INSERT INTO source_task (
                        tenant_id, actor_user_id, operation_key, source_mode,
                        user_intent, requested_sources, preferred_languages,
                        state, locale
                    ) VALUES (
                        :tenant_id, :user_id, :operation_key, 'AI_SEARCH',
                        'twink video', :requested_sources, :preferred_languages,
                        'QUEUED', 'en'
                    )
                    RETURNING execution_token
                    """
                ),
                {
                    "tenant_id": str(tenant_id.value),
                    "user_id": str(principal.user_id),
                    "operation_key": operation_key,
                    "requested_sources": ["x"],
                    "preferred_languages": ["en"],
                },
            ).scalar_one()

        activities = XInterestProfileActivities(
            session_factory,
            credential_resolver=_StaticCredentialResolver(),
            client=client,
        )
        workflow_input = ScoutWorkflowInput(
            operation_key=operation_key,
            execution_token=str(execution_token),
        )

        first = await activities.sync_x_user_interest_profile(workflow_input)
        assert first.state is XInterestSyncState.SYNCED
        assert first.sample_size == 0
        assert client.calls == 1

        with session_factory() as session, tenant_transaction(session, tenant_id):
            stored = UserInterestProfileRepository().get(
                session,
                user_id=principal.user_id,
            )
            assert stored is not None
            assert stored.sample_size == 0
            assert stored.term_weights == {}
            assert stored.hashtag_weights == {}
            assert stored.author_weights == {}

        second = await activities.sync_x_user_interest_profile(workflow_input)
        assert second.state is XInterestSyncState.CACHED
        assert second.sample_size == 0
        assert client.calls == 1
    finally:
        engine.dispose()
