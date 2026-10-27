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
from vimi_social.source.candidate_filter import FilteringCandidateCurator
from vimi_social.source.connectors import SourceConnectorRegistry, SourceSearchCandidates
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


class FakeTranslator:
    async def translate_to_english(self, intent: str) -> str | None:
        assert intent == "Гей порно твинк молодые"
        return "Gay porn twink young"


def _candidate(
    source_id: str,
    *,
    duration_ms: int,
    text_value: str,
) -> CandidateContent:
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
        connector_metadata={
            "language": "en",
            "media_key": f"7_{source_id}",
            "x_search_scope": "all",
            "x_search_query": "test",
        },
    )


_BROAD_TEXTS = (
    "Gay porn twink young beach travel sunset conversation documentary",
    "Gay porn twink young studio interview fashion music portrait",
    "Gay porn twink young city apartment morning lifestyle discussion",
    "Gay porn twink young countryside road trip summer diary",
    "Gay porn twink young gym training wellness behind scenes",
    "Gay porn twink young hotel vacation pool evening story",
    "Gay porn twink young festival backstage performance candid footage",
    "Gay porn twink young home cooking weekend personal vlog",
)


class SparseOrRecallConnector:
    source_name = "x"

    def __init__(self) -> None:
        self.requests: list[ScoutSearchRequest] = []

    async def search(self, request: ScoutSearchRequest) -> tuple[CandidateContent, ...]:
        self.requests.append(request)
        call = len(self.requests)

        if call == 1:
            assert request.query_variants == ("Гей", "порно", "твинк", "молодые")
            assert request.preferred_languages == ("ru",)
            return SourceSearchCandidates((), next_token=None)

        if call == 2:
            assert request.query_variants == ("Gay", "porn", "twink", "young")
            assert request.preferred_languages == ("en",)
            return SourceSearchCandidates(
                (
                    _candidate(
                        "exact-1",
                        duration_ms=86_000,
                        text_value=(
                            "Gay porn twink young first archival video profile interview"
                        ),
                    ),
                    _candidate(
                        "exact-2",
                        duration_ms=64_000,
                        text_value=(
                            "Gay porn twink young second independent travel recording"
                        ),
                    ),
                ),
                next_token=None,
            )

        if call == 3:
            assert request.query_variants == ("Gay", "porn", "twink", "young")
            assert request.preferred_languages == ()
            return SourceSearchCandidates(
                tuple(
                    _candidate(
                        f"broad-{index}",
                        duration_ms=300_000 + index * 1_000,
                        text_value=text_value,
                    )
                    for index, text_value in enumerate(_BROAD_TEXTS)
                ),
                next_token="unused-page-2",
            )

        raise AssertionError("Scout must stop after reaching ten curated candidates")


@pytest.mark.asyncio
async def test_sparse_search_uses_word_level_or_recall_until_target() -> None:
    engine = create_engine(_database_dsn())
    session_factory = sessionmaker[Session](
        bind=engine,
        expire_on_commit=False,
        autoflush=False,
    )
    telegram_user = TelegramUser(
        id=930039001,
        first_name="Recall",
        username="controlled_recall_930039001",
        language_code="ru",
    )

    try:
        resolver = TelegramIdentityResolver(session_factory)
        principal = resolver.resolve(telegram_user)
        TelegramUpdateGuard(session_factory).claim(830039001, telegram_user.id)

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
        service.begin_ai_search(principal, chat_id=telegram_user.id)
        task = service.submit_ai_search_intent(
            principal,
            update_id=830039001,
            message_id=939001,
            chat_id=telegram_user.id,
            intent="Гей порно твинк молодые",
        )
        assert task is not None
        assert task.preferred_languages == ("ru", "en")

        connector = SparseOrRecallConnector()
        activities = ScoutActivities(
            session_factory,
            SourceConnectorRegistry([connector]),
            messenger=None,
            query_planner=MultilingualQueryPlanner(FakeTranslator()),
            curator=FilteringCandidateCurator(),
            retrieval_budget=120,
            retrieval_round_limit=30,
        )
        result = await activities.execute_scout_task(
            ScoutWorkflowInput(
                operation_key=task.operation_key.value,
                execution_token=str(task.execution_token),
            )
        )

        assert len(connector.requests) == 3
        assert result.candidate_count == 10

        repository = SourceTaskRepository()
        with (
            session_factory() as session,
            tenant_transaction(session, principal.context.tenant_id),
        ):
            persisted = repository.list_candidates(session, task.id, limit=20)

        assert len(persisted) == 10
        assert all(
            candidate.duration_ms is not None and candidate.duration_ms >= 60_000
            for candidate in persisted
        )
        assert sum(
            candidate.connector_metadata.get("retrieval_relaxation_level") == 2
            for candidate in persisted
        ) == 8
        assert all(
            candidate.connector_metadata.get("retrieval_query_variants")
            == ["Gay", "porn", "twink", "young"]
            for candidate in persisted
            if candidate.source_id.startswith("broad-")
        )
    finally:
        engine.dispose()
