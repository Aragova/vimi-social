from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from vimi_social.auth.context import ExecutionContext
from vimi_social.domain.identity import TenantId
from vimi_social.domain.international import AgeEligibility, IanaTimezone, UiLocale
from vimi_social.source.service import (
    SourceTaskIntentTooLong,
    SourceTaskService,
    infer_requested_sources,
)
from vimi_social.telegram.identity import TelegramPrincipal


def test_broad_intent_does_not_conflate_ui_language_with_search_source() -> None:
    assert infer_requested_sources("найди свежие видео про фитнес") == ()


def test_explicit_x_source_is_detected() -> None:
    assert infer_requested_sources("Find fresh clips on X about fitness") == ("x",)
    assert infer_requested_sources("Найди в Твиттере ролики про спорт") == ("x",)


def test_explicit_unavailable_source_is_preserved_for_fail_closed_routing() -> None:
    assert infer_requested_sources("Найди это в Telegram") == ("telegram",)
    assert infer_requested_sources("Search Reddit for this topic") == ("reddit",)


def test_oversized_intent_is_rejected_before_opening_database_session() -> None:
    def no_session() -> Session:
        raise AssertionError("oversized intent must be rejected before database access")

    principal = TelegramPrincipal(
        user_id=uuid4(),
        context=ExecutionContext(
            tenant_id=TenantId(uuid4()),
            actor_subject="telegram:1",
        ),
        locale=UiLocale.EN,
        timezone=IanaTimezone("UTC"),
        region=None,
        age_eligibility=AgeEligibility.UNKNOWN,
    )
    service = SourceTaskService(no_session)

    with pytest.raises(SourceTaskIntentTooLong):
        service.submit_ai_search_intent(
            principal,
            update_id=1,
            message_id=2,
            chat_id=3,
            intent="x" * 4001,
        )
