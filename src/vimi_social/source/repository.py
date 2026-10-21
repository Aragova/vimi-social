from collections.abc import Callable
from datetime import datetime
from typing import Mapping, cast
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

    def begin_ai_search(self, principal: TelegramPrincipal) -> None:
        with self._session_factory() as session:
            with tenant_transaction(session, principal.context.tenant_id) as tx:
                tx.execute(
                    text(
                        """
                        INSERT INTO telegram_intake_state (tenant_id, user_id, state)
                        VALUES (:tenant_id, :user_id, 'AWAITING_AI_SEARCH_QUERY')
                        ON CONFLICT (tenant_id, user_id)
                        DO UPDATE SET
                            state = EXCLUDED.state,
                            updated_at = clock_timestamp()
                        """
                    ),
                    {
                        "tenant_id": str(principal.context.tenant_id.value),
                        "user_id": str(principal.user_id),
                    },
                )

    def consume_ai_search_text(
        self,
        update_id: int,
        principal: TelegramPrincipal,
        query_text: str,
    ) -> SourceTask | None:
        query = query_text.strip()
        tenant_id = principal.context.tenant_id
        origin_key = f"telegram:update:{update_id}:source-task"
        with self._session_factory() as session:
            with tenant_transaction(session, tenant_id) as tx:
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
                    _validate_existing_binding(existing, tenant_id, principal.user_id, query)
                    return _source_task_from_row(cast(Mapping[str, object], existing))

                state = tx.execute(
                    text(
                        """
                        SELECT state
                        FROM telegram_intake_state
                        WHERE tenant_id = :tenant_id AND user_id = :user_id
                        FOR UPDATE
                        """
                    ),
                    {
                        "tenant_id": str(tenant_id.value),
                        "user_id": str(principal.user_id),
                    },
                ).scalar_one_or_none()
                if state != "AWAITING_AI_SEARCH_QUERY":
                    return None
                if not query:
                    return None
                if len(query) > 2000:
                    raise SourceTaskQueryTooLong(
                        "AI search task must be at most 2000 characters"
                    )

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
                        DELETE FROM telegram_intake_state
                        WHERE tenant_id = :tenant_id AND user_id = :user_id
                        """
                    ),
                    {
                        "tenant_id": str(tenant_id.value),
                        "user_id": str(principal.user_id),
                    },
                )

        return _source_task_from_row(cast(Mapping[str, object], row))


class SourceCandidateRepository:
    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def save_all(self, task: SourceTask, candidates: tuple[CandidateContent, ...]) -> None:
        tenant_id = TenantId(task.tenant_id)
        with self._session_factory() as session:
            with tenant_transaction(session, tenant_id) as tx:
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
