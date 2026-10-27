import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from vimi_social.db.tenant import tenant_transaction
from vimi_social.source.interest_profile import InterestProfileDraft
from vimi_social.source.interest_repository import UserInterestProfileRepository
from vimi_social.telegram.identity import TelegramIdentityResolver
from vimi_social.telegram.models import TelegramUser


def _database_dsn() -> str:
    dsn = os.environ.get("VIMI_TEST_DATABASE_DSN")
    if dsn is None:
        pytest.skip("PostgreSQL integration DSN is not configured")
    return dsn


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
