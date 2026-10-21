from collections.abc import Callable, Mapping
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from vimi_social.db.tenant import tenant_transaction
from vimi_social.domain.identity import TenantId
from vimi_social.domain.source import SourceMode
from vimi_social.source.models import (
    CandidateContent,
    SourcePlatform,
    SourceTask,
    SourceTaskQueryTooLong,
    SourceTaskState,
)
from vimi_social.telegram.identity import TelegramPrincipal


class SourceTaskBindingConflict(RuntimeError):
    pass


class SourceTaskRepository:
    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def begin_ai_search(self, update_id: int, principal: TelegramPrincipal) -> bool:
        return self._transition_intake(
            update_id,
            principal,
            state="AWAITING_AI_SEARCH_QUERY",
        )

    def clear_pending_intake(self, update_id: int, principal: TelegramPrincipal) -> bool:
        return self._transition_intake(update_id, principal, state="IDLE")

    def _transition_intake(
        self,
        update_id: int,
        principal: TelegramPrincipal,
        *,
        state: str,
    ) -> bool:
        if update_id < 0:
            raise ValueError("Telegram update id must be non-negative")
        if state not in {"IDLE", "AWAITING_AI_SEARCH_QUERY"}:
            raise ValueError("unsupported Telegram intake state")

        tenant_id = principal.context.tenant_id
        with (
            self._session_factory() as session,
            tenant_transaction(session, tenant_id) as tx,
        ):
            row = tx.execute(
                text(
                    """
                    INSERT INTO telegram_intake_state (
                        tenant_id,
                        user_id,
                        state,
                        last_update_id
                    )
                    VALUES (
                        :tenant_id,
                        :user_id,
                        :state,
                        :update_id
                    )
                    ON CONFLICT (tenant_id, user_id)
                    DO UPDATE SET
                        state = EXCLUDED.state,
                        last_update_id = EXCLUDED.last_update_id,
                        updated_at = clock_timestamp()
                    WHERE telegram_intake_state.last_update_id < EXCLUDED.last_update_id
                    RETURNING state, last_update_id
                    """
                ),
                {
                    "tenant_id": str(tenant_id.value),
                    "user_id": str(principal.user_id),
                    "state": state,
                    "update_id": update_id,
                },
            ).mappings().one_or_none()

            if row is None:
                row = tx.execute(
                    text(
                        """
                        SELECT state, last_update_id
                        FROM telegram_intake_state
                        WHERE tenant_id = :tenant_id AND user_id = :user_id
                        """
                    ),
                    {
                        "tenant_id": str(tenant_id.value),
                        "user_id": str(principal.user_id),
                    },
                ).mappings().one()

            return row["state"] == state and row["last_update_id"] == update_id

    def consume_ai_search_text(
        self,
        update_id: int,
        principal: TelegramPrincipal,
        query_text: str,
    ) -> SourceTask | None:
        query = query_text.strip()
        tenant_id = principal.context.tenant_id
        origin_key = f"telegram:update:{update_id}:source-task"
        query_too_long = False
        task: SourceTask | None = None

        with (
            self._session_factory() as session,
            tenant_transaction(session, tenant_id) as tx,
        ):
            existing = tx.execute(
                text(
                    """
                    SELECT *
                    FROM source_task
                    WHERE origin_key = :origin_key
                    """
                ),
                {"origin_key": origin_key},
            ).mappings().one_or_none()

            if existing is not None:
                existing_row = cast(Mapping[str, object], existing)
                _validate_existing_binding(
                    existing_row,
                    tenant_id,
                    principal.user_id,
                    query,
                )
                return _source_task_from_row(existing_row)

            intake = tx.execute(
                text(
                    """
                    SELECT state, last_update_id
                    FROM telegram_intake_state
                    WHERE tenant_id = :tenant_id AND user_id = :user_id
                    FOR UPDATE
                    """
                ),
                {
                    "tenant_id": str(tenant_id.value),
                    "user_id": str(principal.user_id),
                },
            ).mappings().one_or_none()
            if intake is None or intake["state"] != "AWAITING_AI_SEARCH_QUERY":
                return None

            last_update_id = intake["last_update_id"]
            if not isinstance(last_update_id, int):
                raise RuntimeError("Telegram intake last_update_id was not an integer")
            if update_id <= last_update_id:
                return None
            if not query:
                return None

            if len(query) > 2000:
                tx.execute(
                    text(
                        """
                        UPDATE telegram_intake_state
                        SET last_update_id = :update_id,
                            updated_at = clock_timestamp()
                        WHERE tenant_id = :tenant_id AND user_id = :user_id
                        """
                    ),
                    {
                        "tenant_id": str(tenant_id.value),
                        "user_id": str(principal.user_id),
                        "update_id": update_id,
                    },
                )
                query_too_long = True
            else:
                row = tx.execute(
                    text(
                        """
                        INSERT INTO source_task (
                            tenant_id,
                            actor_user_id,
                            origin_key,
                            source_mode,
                            query_text,
                            requested_source,
                            state
                        )
                        VALUES (
                            :tenant_id,
                            :actor_user_id,
                            :origin_key,
                            'AI_SEARCH',
                            :query_text,
                            NULL,
                            'QUEUED'
                        )
                        RETURNING *
                        """
                    ),
                    {
                        "tenant_id": str(tenant_id.value),
                        "actor_user_id": str(principal.user_id),
                        "origin_key": origin_key,
                        "query_text": query,
                    },
                ).mappings().one()

                tx.execute(
                    text(
                        """
                        UPDATE telegram_intake_state
                        SET state = 'IDLE',
                            last_update_id = :update_id,
                            updated_at = clock_timestamp()
                        WHERE tenant_id = :tenant_id AND user_id = :user_id
                        """
                    ),
                    {
                        "tenant_id": str(tenant_id.value),
                        "user_id": str(principal.user_id),
                        "update_id": update_id,
                    },
                )
                task = _source_task_from_row(cast(Mapping[str, object], row))

        if query_too_long:
            raise SourceTaskQueryTooLong(
                "AI search task must be at most 2000 characters"
            )
        return task


class SourceCandidateRepository:
    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def save_all(self, task: SourceTask, candidates: tuple[CandidateContent, ...]) -> None:
        tenant_id = TenantId(task.tenant_id)
        with (
            self._session_factory() as session,
            tenant_transaction(session, tenant_id) as tx,
        ):
            for candidate in candidates:
                tx.execute(
                    text(
                        """
                        INSERT INTO source_candidate (
                            tenant_id,
                            source_task_id,
                            source,
                            external_id,
                            canonical_url,
                            author_handle,
                            text_body,
                            published_at,
                            possibly_sensitive,
                            media_kind,
                            media_refs
                        )
                        VALUES (
                            :tenant_id,
                            :source_task_id,
                            :source,
                            :external_id,
                            :canonical_url,
                            :author_handle,
                            :text_body,
                            :published_at,
                            :possibly_sensitive,
                            :media_kind,
                            :media_refs
                        )
                        ON CONFLICT (source_task_id, source, external_id) DO NOTHING
                        """
                    ),
                    {
                        "tenant_id": str(task.tenant_id),
                        "source_task_id": str(task.id),
                        "source": candidate.source.value,
                        "external_id": candidate.external_id,
                        "canonical_url": candidate.canonical_url,
                        "author_handle": candidate.author_handle,
                        "text_body": candidate.text,
                        "published_at": candidate.published_at,
                        "possibly_sensitive": candidate.possibly_sensitive,
                        "media_kind": candidate.media_kind.value,
                        "media_refs": list(candidate.media_refs),
                    },
                )


def _validate_existing_binding(
    row: Mapping[str, object],
    tenant_id: TenantId,
    actor_user_id: UUID,
    query: str,
) -> None:
    if (
        row["tenant_id"] != tenant_id.value
        or row["actor_user_id"] != actor_user_id
        or row["query_text"] != query
    ):
        raise SourceTaskBindingConflict(
            "source task operation key is already bound differently"
        )


def _source_task_from_row(row: Mapping[str, object]) -> SourceTask:
    return SourceTask(
        id=_uuid(row["id"], "id"),
        tenant_id=_uuid(row["tenant_id"], "tenant_id"),
        actor_user_id=_uuid(row["actor_user_id"], "actor_user_id"),
        origin_key=_string(row["origin_key"], "origin_key"),
        source_mode=SourceMode(_string(row["source_mode"], "source_mode")),
        query_text=_string(row["query_text"], "query_text"),
        requested_source=(
            SourcePlatform(_string(row["requested_source"], "requested_source"))
            if row["requested_source"] is not None
            else None
        ),
        state=SourceTaskState(_string(row["state"], "state")),
        created_at=_datetime(row["created_at"], "created_at"),
    )


def _uuid(value: object, name: str) -> UUID:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        return UUID(value)
    raise RuntimeError(f"{name} was not returned as UUID")


def _string(value: object, name: str) -> str:
    if isinstance(value, str):
        return value
    raise RuntimeError(f"{name} was not returned as text")


def _datetime(value: object, name: str) -> datetime:
    if isinstance(value, datetime):
        return value
    raise RuntimeError(f"{name} was not returned as datetime")
