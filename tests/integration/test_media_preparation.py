import os
from uuid import UUID

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from vimi_social.db.tenant import tenant_transaction
from vimi_social.domain.media import MediaPreparationState, RightsBasis
from vimi_social.media.service import MediaPreparationService
from vimi_social.source.service import SourceTaskService
from vimi_social.telegram.identity import TelegramIdentityResolver, TelegramUpdateGuard
from vimi_social.telegram.models import TelegramUser


def _database_dsn() -> str:
    dsn = os.environ.get("VIMI_TEST_DATABASE_DSN")
    if dsn is None:
        pytest.skip("PostgreSQL integration DSN is not configured")
    return dsn


def test_media_selection_requires_rights_and_reserves_processing_once() -> None:
    engine = create_engine(_database_dsn())
    session_factory = sessionmaker[Session](
        bind=engine,
        expire_on_commit=False,
        autoflush=False,
    )
    first_user = TelegramUser(
        id=930000001,
        first_name="MediaOne",
        username="media_one",
        language_code="en",
    )
    second_user = TelegramUser(
        id=930000002,
        first_name="MediaTwo",
        username="media_two",
        language_code="en",
    )
    update_id = 830000001

    try:
        resolver = TelegramIdentityResolver(session_factory)
        first = resolver.resolve(first_user)
        second = resolver.resolve(second_user)
        guard = TelegramUpdateGuard(session_factory)
        assert guard.claim(update_id, first_user.id).value == "CLAIMED"

        source_service = SourceTaskService(session_factory)
        source_service.begin_ai_search(first, chat_id=first_user.id)
        source_task = source_service.submit_ai_search_intent(
            first,
            update_id=update_id,
            message_id=91,
            chat_id=first_user.id,
            intent="media preparation integration",
        )
        assert source_task is not None

        candidate_id = UUID("11111111-2222-3333-4444-555555555555")
        with session_factory() as session, tenant_transaction(session, first.context.tenant_id):
            session.execute(
                text(
                    """
                    INSERT INTO source_task_candidate (
                        id, tenant_id, source_task_id, source, source_id, source_url,
                        author, media_type, duration_ms, width, height, title, caption,
                        tags, engagement, adult_classification, explicitness_score,
                        provenance_hint, availability, connector_metadata
                    ) VALUES (
                        :id, :tenant_id, :source_task_id, 'x', 'media-123',
                        'https://x.com/i/web/status/media-123', '42', 'video',
                        12500, 1080, 1920, 'Integration video', 'training clip',
                        '{}', '{}'::jsonb, 'UNKNOWN', NULL,
                        'PUBLIC_X_POST_REUSE_RIGHTS_NOT_ESTABLISHED',
                        'DISCOVERED_MEDIA_REFERENCE_AVAILABLE',
                        '{"acquisition_url":"https://video.example/file.mp4"}'::jsonb
                    )
                    """
                ),
                {
                    "id": str(candidate_id),
                    "tenant_id": str(first.context.tenant_id.value),
                    "source_task_id": str(source_task.id),
                },
            )

        media_service = MediaPreparationService(session_factory)
        preparation = media_service.select_candidate(first, candidate_id)
        assert preparation is not None
        assert preparation.state is MediaPreparationState.AWAITING_RIGHTS
        assert preparation.rights_basis is RightsBasis.UNKNOWN

        with session_factory() as session, tenant_transaction(session, first.context.tenant_id):
            reservations_before = session.execute(
                text(
                    """
                    SELECT count(*) FROM usage_reservation
                    WHERE operation_key = :operation_key
                    """
                ),
                {"operation_key": preparation.operation_key},
            ).scalar_one()
            capacity = session.execute(
                text(
                    """
                    SELECT quota, reserved, committed
                    FROM usage_capacity
                    WHERE tenant_id = :tenant_id
                      AND metric = 'video_second_processed'
                    """
                ),
                {"tenant_id": str(first.context.tenant_id.value)},
            ).one()
            assert reservations_before == 0
            assert capacity.quota == 600
            assert capacity.reserved == 0
            assert capacity.committed == 0

        assert media_service.select_candidate(second, candidate_id) is None

        workflow_input = media_service.confirm_rights(first, preparation.id)
        duplicate_input = media_service.confirm_rights(first, preparation.id)
        assert workflow_input is not None
        assert duplicate_input == workflow_input
        assert workflow_input.operation_key == preparation.operation_key
        assert media_service.confirm_rights(second, preparation.id) is None

        with session_factory() as session, tenant_transaction(session, first.context.tenant_id):
            row = session.execute(
                text(
                    """
                    SELECT rights_basis, state
                    FROM media_preparation
                    WHERE id = :preparation_id
                    """
                ),
                {"preparation_id": str(preparation.id)},
            ).one()
            assert row.rights_basis == "USER_CONFIRMED"
            assert row.state == "QUEUED"

            reservations = session.execute(
                text(
                    """
                    SELECT count(*) AS count, min(quantity) AS quantity, min(state) AS state
                    FROM usage_reservation
                    WHERE operation_key = :operation_key
                    """
                ),
                {"operation_key": preparation.operation_key},
            ).one()
            assert reservations.count == 1
            assert reservations.quantity == 13
            assert reservations.state == "RESERVED"

            capacity = session.execute(
                text(
                    """
                    SELECT reserved, committed
                    FROM usage_capacity
                    WHERE tenant_id = :tenant_id
                      AND metric = 'video_second_processed'
                    """
                ),
                {"tenant_id": str(first.context.tenant_id.value)},
            ).one()
            assert capacity.reserved == 13
            assert capacity.committed == 0

        with session_factory() as session, tenant_transaction(session, second.context.tenant_id):
            invisible = session.execute(
                text("SELECT id FROM media_preparation WHERE id = :preparation_id"),
                {"preparation_id": str(preparation.id)},
            ).scalar_one_or_none()
            assert invisible is None
    finally:
        engine.dispose()
