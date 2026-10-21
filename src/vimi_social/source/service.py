from collections.abc import Callable
import re
from uuid import UUID

from sqlalchemy.orm import Session

from vimi_social.db.tenant import tenant_transaction
from vimi_social.domain.identity import OperationKey
from vimi_social.domain.source import SourceTask
from vimi_social.source.repository import SourceTaskRepository
from vimi_social.telegram.identity import TelegramPrincipal
from vimi_social.usage.models import ReservationRequest
from vimi_social.usage.repository import UsageRepository


_EXPLICIT_SOURCE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("x", re.compile(r"(?:^|\W)(?:x|twitter|твиттер)(?:\W|$)", re.IGNORECASE)),
    ("telegram", re.compile(r"(?:telegram|телеграм)", re.IGNORECASE)),
    ("reddit", re.compile(r"(?:reddit|реддит)", re.IGNORECASE)),
)


class SourceTaskService:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        *,
        repository: SourceTaskRepository | None = None,
        usage_repository: UsageRepository | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._repository = repository or SourceTaskRepository()
        self._usage_repository = usage_repository or UsageRepository()

    def begin_ai_search(
        self,
        principal: TelegramPrincipal,
        *,
        chat_id: int,
    ) -> None:
        with (
            self._session_factory() as session,
            tenant_transaction(session, principal.context.tenant_id),
        ):
            self._repository.begin_ai_search_conversation(
                session,
                tenant_id=principal.context.tenant_id,
                user_id=principal.user_id,
                chat_id=chat_id,
            )

    def submit_ai_search_intent(
        self,
        principal: TelegramPrincipal,
        *,
        update_id: int,
        message_id: int,
        chat_id: int,
        intent: str,
    ) -> SourceTask | None:
        normalized_intent = " ".join(intent.split())
        if not normalized_intent:
            return None

        operation_key = OperationKey(f"source-task:telegram:{chat_id}:{message_id}")
        requested_sources = infer_requested_sources(normalized_intent)

        with (
            self._session_factory() as session,
            tenant_transaction(session, principal.context.tenant_id),
        ):
            task = self._repository.get_by_operation_key(session, operation_key)
            if task is not None:
                self._repository.bind_existing_task(
                    task,
                    tenant_id=principal.context.tenant_id,
                    actor_user_id=principal.user_id,
                    user_intent=normalized_intent,
                    telegram_update_id=update_id,
                    telegram_message_id=message_id,
                    telegram_chat_id=chat_id,
                )
            else:
                if not self._repository.is_waiting_for_ai_search(
                    session,
                    tenant_id=principal.context.tenant_id,
                    user_id=principal.user_id,
                    chat_id=chat_id,
                ):
                    return None
                task = self._repository.create_ai_search_task(
                    session,
                    tenant_id=principal.context.tenant_id,
                    actor_user_id=principal.user_id,
                    operation_key=operation_key,
                    user_intent=normalized_intent,
                    requested_sources=requested_sources,
                    preferred_languages=(),
                    telegram_update_id=update_id,
                    telegram_message_id=message_id,
                    telegram_chat_id=chat_id,
                    locale=principal.locale.value,
                )
                self._repository.clear_ai_search_conversation(
                    session,
                    tenant_id=principal.context.tenant_id,
                    user_id=principal.user_id,
                    chat_id=chat_id,
                )

            self._usage_repository.reserve(
                session,
                ReservationRequest(
                    tenant_id=principal.context.tenant_id,
                    operation_key=task.operation_key,
                    metric="scout_run",
                    quantity=1,
                ),
            )
            return task

    def select_candidate(
        self,
        principal: TelegramPrincipal,
        candidate_id: UUID,
    ) -> bool:
        with (
            self._session_factory() as session,
            tenant_transaction(session, principal.context.tenant_id),
        ):
            return self._repository.select_candidate(
                session,
                candidate_id=candidate_id,
                actor_user_id=principal.user_id,
            )


def infer_requested_sources(intent: str) -> tuple[str, ...]:
    """Extract only explicitly named supported/known source families.

    An empty tuple means a broad Scout request and lets the registry query all
    currently configured connectors. Explicit unsupported connectors fail closed
    in the registry instead of silently searching a different platform.
    """
    found: list[str] = []
    for source, pattern in _EXPLICIT_SOURCE_PATTERNS:
        if pattern.search(intent):
            found.append(source)
    return tuple(found)
