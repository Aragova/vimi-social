import hashlib
import re
from collections.abc import Callable
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from vimi_social.db.tenant import tenant_transaction
from vimi_social.domain.identity import OperationKey
from vimi_social.domain.source import (
    CandidateContent,
    ScoutContinuationWorkflowInput,
    SourceTask,
)
from vimi_social.source.continuation_state import find_scout_continuation_state
from vimi_social.source.conversation_state import consume_ai_search_conversation
from vimi_social.source.curator import restore_curator_order
from vimi_social.source.repository import SourceTaskRepository
from vimi_social.telegram.identity import TelegramPrincipal
from vimi_social.usage.models import ReservationRequest
from vimi_social.usage.repository import UsageRepository

_MAX_SOURCE_TASK_INTENT_LENGTH = 4000
_MAX_PAGED_SCOUT_CANDIDATES = 100_000

_EXPLICIT_SOURCE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("x", re.compile(r"(?:^|\W)(?:x|twitter|твиттер\w*)(?:\W|$)", re.IGNORECASE)),
    ("telegram", re.compile(r"(?:telegram|телеграм\w*)", re.IGNORECASE)),
    ("reddit", re.compile(r"(?:reddit|реддит\w*)", re.IGNORECASE)),
)
_CYRILLIC = re.compile(r"[\u0400-\u04FF]")
_LATIN = re.compile(r"[A-Za-z]")


class SourceTaskIntentTooLong(ValueError):
    pass


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
        if len(normalized_intent) > _MAX_SOURCE_TASK_INTENT_LENGTH:
            raise SourceTaskIntentTooLong(
                f"AI Search intent exceeds {_MAX_SOURCE_TASK_INTENT_LENGTH} characters"
            )

        operation_key = OperationKey(f"source-task:telegram:{chat_id}:{message_id}")
        requested_sources = infer_requested_sources(normalized_intent)
        preferred_languages = infer_preferred_languages(normalized_intent)

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
                if not consume_ai_search_conversation(
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
                    preferred_languages=preferred_languages,
                    telegram_update_id=update_id,
                    telegram_message_id=message_id,
                    telegram_chat_id=chat_id,
                    locale=principal.locale.value,
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

    def prepare_ai_search_continuation(
        self,
        principal: TelegramPrincipal,
        *,
        task_id: UUID,
        update_id: int,
        message_id: int,
        chat_id: int,
    ) -> ScoutContinuationWorkflowInput | None:
        with (
            self._session_factory() as session,
            tenant_transaction(session, principal.context.tenant_id),
        ):
            row = session.execute(
                text(
                    """
                    SELECT operation_key, execution_token::text
                    FROM source_task
                    WHERE id = :task_id
                      AND actor_user_id = :actor_user_id
                      AND telegram_chat_id = :chat_id
                      AND state = 'COMPLETED'
                    """
                ),
                {
                    "task_id": str(task_id),
                    "actor_user_id": str(principal.user_id),
                    "chat_id": chat_id,
                },
            ).mappings().one_or_none()
            if row is None:
                return None

            candidates = restore_curator_order(
                self._repository.list_candidates(
                    session,
                    task_id,
                    limit=_MAX_PAGED_SCOUT_CANDIDATES,
                )
            )
            continuation = find_scout_continuation_state(candidates)
            if continuation is None:
                return None

            token_fingerprint = hashlib.sha256(
                continuation.next_token.encode("utf-8")
            ).hexdigest()[:16]
            request_key = OperationKey(
                f"source-task-more:{task_id}:{token_fingerprint}"
            )
            self._usage_repository.reserve(
                session,
                ReservationRequest(
                    tenant_id=principal.context.tenant_id,
                    operation_key=request_key,
                    metric="scout_run",
                    quantity=1,
                ),
            )
            return ScoutContinuationWorkflowInput(
                operation_key=str(row["operation_key"]),
                execution_token=str(row["execution_token"]),
                request_key=request_key.value,
                telegram_update_id=update_id,
                telegram_message_id=message_id,
                telegram_chat_id=chat_id,
            )

    def get_ai_search_candidates(
        self,
        principal: TelegramPrincipal,
        task_id: UUID,
    ) -> tuple[CandidateContent, ...] | None:
        with (
            self._session_factory() as session,
            tenant_transaction(session, principal.context.tenant_id),
        ):
            owned = session.execute(
                text(
                    """
                    SELECT 1
                    FROM source_task
                    WHERE id = :task_id
                      AND actor_user_id = :actor_user_id
                      AND state = 'COMPLETED'
                    """
                ),
                {
                    "task_id": str(task_id),
                    "actor_user_id": str(principal.user_id),
                },
            ).first()
            if owned is None:
                return None
            return restore_curator_order(
                self._repository.list_candidates(
                    session,
                    task_id,
                    limit=_MAX_PAGED_SCOUT_CANDIDATES,
                )
            )

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


def infer_preferred_languages(intent: str) -> tuple[str, ...]:
    """Infer search languages from the intent rather than the Telegram UI locale.

    Russian/Cyrillic intents deliberately request both Russian and English discovery.
    Latin-script intents default to English. Unknown scripts remain unrestricted.
    """
    if _CYRILLIC.search(intent):
        return ("ru", "en")
    if _LATIN.search(intent):
        return ("en",)
    return ()