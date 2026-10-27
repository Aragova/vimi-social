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


def _candidate(source_id: str, text_value: str) -> CandidateContent:
    return CandidateContent(
        id=None,
        source="x",
        source_id=source_id,
        source_url=f"https://x.com/i/web/status/{source_id}",
        author=f"author-{source_id}",
        published_at=None,
        media_type="video",
        duration_ms=300_000,
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
    "Gay porn twink young beach travel sunset documentary",
    "Gay porn twink young studio interview fashion portrait",
    "Gay porn twink young city apartment lifestyle discussion",
    "Gay porn twink young countryside road trip summer diary",
    "Gay porn twink young gym training wellness behind scenes",
    "Gay porn twink young hotel vacation pool evening story",
    "Gay porn twink young festival backstage candid footage",
    "Gay porn twink young home cooking weekend personal vlog",
)


class PageCappedOrConnector:
    source_name = "x"

    def __init__(self) -> None:
        self.requests: list[ScoutSearchRequest] = []

    async def search(self, request: ScoutSearchRequest) -> tuple[CandidateContent, ...]:
        self.requests.append(request)
        call = len(self.requests)

        if call == 1:
            assert request.query_variants == ("Гей", "порно", "твинк", "молодые")
            assert request.preferred_languages == ("ru",)
            assert request.pagination_token is None
            return SourceSearchCandidates((), next_token="ru-page-2")

        if call == 2:
            assert request.query_variants == ("Гей", "порно", "твинк", "молодые")
            assert request.preferred_languages == ("ru",)
            assert request.pagination_token == "ru-page-2"
            return SourceSearchCandidates((), next_token="ru-page-3")

        if call == 3:
            assert request.query_variants == ("Gay", "porn", "twink", "young")
            assert request.preferred_languages == ("en",)
            assert request.pagination_token is None
            return SourceSearchCandidates(
                (
                    _candidate(
                        "en-1",
                        "Gay porn twink young first archival long video interview",
                    ),
                    _candidate(
                        "en-2",
                        "Gay porn twink young second independent long video profile",
                    ),
                ),
                next_token=None,
            )

        if call == 4:
            assert request.query_variants == ("Gay", "porn", "twink", "young")
            assert request.preferred_languages == ()
            assert request.pagination_token is None
            return SourceSearchCandidates(
                tuple(
                    _candidate(f"broad-{index}", text_value)
                    for index, text_value in enumerate(_BROAD_TEXTS)
                ),
                next_token="en-page-2",
            )

        raise AssertionError("Scout must stop once ten relevant long-form candidates exist")


@pytest.mark.asyncio
async def test_or_round_page_cap_preserves_budget_for_translated_english_rounds() -> None:
    engine = create_engine(_database_dsn())
    session_factory = sessionmaker[Session](
        bind=engine,
        expire_on_commit=False,
        autoflush=False,
    )
    telegram_user = TelegramUser(
        id=930039101,
        first_name="OrCap",
        username="or_round_cap_930039101",
        language_code="ru",
    )

    try:
        resolver = TelegramIdentityResolver(session_factory)
        principal = resolver.resolve(telegram_user)
        TelegramUpdateGuard(session_factory).claim(830039101, telegram_user.id)

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
            update_id=830039101,
            message_id=939101,
            chat_id=telegram_user.id,
            intent="Гей порно твинк молодые",
        )
        assert task is not None
        assert task.preferred_languages == ("ru", "en")

        connector = PageCappedOrConnector()
        activities = ScoutActivities(
            session_factory,
            SourceConnectorRegistry([connector]),
            messenger=None,
            query_planner=MultilingualQueryPlanner(FakeTranslator()),
            curator=FilteringCandidateCurator(),
            retrieval_budget=150,
            retrieval_round_limit=30,
        )
        result = await activities.execute_scout_task(
            ScoutWorkflowInput(
                operation_key=task.operation_key.value,
                execution_token=str(task.execution_token),
            )
        )

        assert len(connector.requests) == 4
        assert [request.pagination_token for request in connector.requests] == [
            None,
            "ru-page-2",
            None,
            None,
        ]
        assert result.candidate_count == 10

        repository = SourceTaskRepository()
        with (
            session_factory() as session,
            tenant_transaction(session, principal.context.tenant_id),
        ):
            persisted = repository.list_candidates(session, task.id, limit=20)

        assert len(persisted) == 10
        assert sum(
            candidate.connector_metadata.get("retrieval_relaxation_level") == 2
            for candidate in persisted
        ) == 8
        assert all(
            candidate.duration_ms is not None and candidate.duration_ms >= 60_000
            for candidate in persisted
        )
    finally:
        engine.dispose()
