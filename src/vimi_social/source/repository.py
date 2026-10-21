from collections.abc import Mapping
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from vimi_social.domain.identity import OperationKey, TenantId
from vimi_social.domain.source import (
    AdultClassification,
    CandidateContent,
    SourceMode,
    SourceTask,
    SourceTaskState,
)


class SourceTaskBindingConflict(RuntimeError):
    pass


class SourceTaskRepository:
    def begin_ai_search_conversation(
        self,
        session: Session,
        *,
        tenant_id: TenantId,
        user_id: UUID,
        chat_id: int,
    ) -> None:
        session.execute(
            text(
                """
                INSERT INTO telegram_conversation_state (
                    tenant_id, user_id, chat_id, state, updated_at
                )
                VALUES (
                    :tenant_id, :user_id, :chat_id, 'AWAITING_AI_SEARCH_INTENT',
                    clock_timestamp()
                )
                ON CONFLICT (tenant_id, user_id, chat_id) DO UPDATE
                SET state = EXCLUDED.state,
                    updated_at = clock_timestamp()
                """
            ),
            {
                "tenant_id": str(tenant_id.value),
                "user_id": str(user_id),
                "chat_id": chat_id,
            },
        )

    def is_waiting_for_ai_search(
        self,
        session: Session,
        *,
        tenant_id: TenantId,
        user_id: UUID,
        chat_id: int,
    ) -> bool:
        return (
            session.execute(
                text(
                    """
                    SELECT 1
                    FROM telegram_conversation_state
                    WHERE tenant_id = :tenant_id
                      AND user_id = :user_id
                      AND chat_id = :chat_id
                      AND state = 'AWAITING_AI_SEARCH_INTENT'
                    """
                ),
                {
                    "tenant_id": str(tenant_id.value),
                    "user_id": str(user_id),
                    "chat_id": chat_id,
                },
            ).first()
            is not None
        )

    def clear_ai_search_conversation(
        self,
        session: Session,
        *,
        tenant_id: TenantId,
        user_id: UUID,
        chat_id: int,
    ) -> None:
        session.execute(
            text(
                """
                DELETE FROM telegram_conversation_state
                WHERE tenant_id = :tenant_id
                  AND user_id = :user_id
                  AND chat_id = :chat_id
                """
            ),
            {
                "tenant_id": str(tenant_id.value),
                "user_id": str(user_id),
                "chat_id": chat_id,
            },
        )

    def get_by_operation_key(
        self,
        session: Session,
        operation_key: OperationKey,
    ) -> SourceTask | None:
        row = session.execute(
            text(
                """
                SELECT id, tenant_id, actor_user_id, operation_key, execution_token, source_mode,
                       user_intent, requested_sources, preferred_languages, state, failure_code,
                       telegram_update_id, telegram_message_id, telegram_chat_id,
                       locale
                FROM source_task
                WHERE operation_key = :operation_key
                """
            ),
            {"operation_key": operation_key.value},
        ).mappings().one_or_none()
        if row is None:
            return None
        return _source_task_from_row(cast(Mapping[str, object], row))

    def create_ai_search_task(
        self,
        session: Session,
        *,
        tenant_id: TenantId,
        actor_user_id: UUID,
        operation_key: OperationKey,
        user_intent: str,
        requested_sources: tuple[str, ...],
        preferred_languages: tuple[str, ...],
        telegram_update_id: int,
        telegram_message_id: int,
        telegram_chat_id: int,
        locale: str,
    ) -> SourceTask:
        row = session.execute(
            text(
                """
                INSERT INTO source_task (
                    tenant_id,
                    actor_user_id,
                    operation_key,
                    source_mode,
                    user_intent,
                    requested_sources,
                    preferred_languages,
                    state,
                    failure_code,
                    telegram_update_id,
                    telegram_message_id,
                    telegram_chat_id,
                    locale
                )
                VALUES (
                    :tenant_id,
                    :actor_user_id,
                    :operation_key,
                    'AI_SEARCH',
                    :user_intent,
                    :requested_sources,
                    :preferred_languages,
                    'QUEUED',
                    NULL,
                    :telegram_update_id,
                    :telegram_message_id,
                    :telegram_chat_id,
                    :locale
                )
                RETURNING id, tenant_id, actor_user_id, operation_key, execution_token, source_mode,
                          user_intent, requested_sources, preferred_languages, state, failure_code,
                          telegram_update_id, telegram_message_id, telegram_chat_id,
                          locale
                """
            ),
            {
                "tenant_id": str(tenant_id.value),
                "actor_user_id": str(actor_user_id),
                "operation_key": operation_key.value,
                "user_intent": user_intent,
                "requested_sources": list(requested_sources),
                "preferred_languages": list(preferred_languages),
                "telegram_update_id": telegram_update_id,
                "telegram_message_id": telegram_message_id,
                "telegram_chat_id": telegram_chat_id,
                "locale": locale,
            },
        ).mappings().one()
        return _source_task_from_row(cast(Mapping[str, object], row))

    def bind_existing_task(
        self,
        task: SourceTask,
        *,
        tenant_id: TenantId,
        actor_user_id: UUID,
        user_intent: str,
        telegram_update_id: int,
        telegram_message_id: int,
        telegram_chat_id: int,
    ) -> None:
        expected = (
            tenant_id.value,
            actor_user_id,
            user_intent,
            telegram_update_id,
            telegram_message_id,
            telegram_chat_id,
        )
        actual = (
            task.tenant_id.value,
            task.actor_user_id,
            task.user_intent,
            task.telegram_update_id,
            task.telegram_message_id,
            task.telegram_chat_id,
        )
        if expected != actual:
            raise SourceTaskBindingConflict(
                "source task operation key is bound to different request data"
            )

    def set_state(
        self,
        session: Session,
        operation_key: OperationKey,
        state: SourceTaskState,
        *,
        failure_code: str | None = None,
    ) -> None:
        updated_id = session.execute(
            text(
                """
                UPDATE source_task
                SET state = :state,
                    failure_code = :failure_code,
                    updated_at = clock_timestamp()
                WHERE operation_key = :operation_key
                RETURNING id::text
                """
            ),
            {
                "state": state.value,
                "failure_code": failure_code,
                "operation_key": operation_key.value,
            },
        ).scalar_one_or_none()
        if updated_id is None:
            raise RuntimeError("source task was not found in tenant context")

    def replace_candidates(
        self,
        session: Session,
        *,
        task_id: UUID,
        tenant_id: TenantId,
        candidates: tuple[CandidateContent, ...],
    ) -> tuple[CandidateContent, ...]:
        persisted: list[CandidateContent] = []
        for candidate in candidates:
            row = session.execute(
                text(
                    """
                    INSERT INTO source_task_candidate (
                        tenant_id,
                        source_task_id,
                        source,
                        source_id,
                        source_url,
                        author,
                        published_at,
                        media_type,
                        duration_ms,
                        width,
                        height,
                        title,
                        caption,
                        tags,
                        engagement,
                        adult_classification,
                        explicitness_score,
                        provenance_hint,
                        availability,
                        connector_metadata
                    )
                    VALUES (
                        :tenant_id,
                        :source_task_id,
                        :source,
                        :source_id,
                        :source_url,
                        :author,
                        :published_at,
                        :media_type,
                        :duration_ms,
                        :width,
                        :height,
                        :title,
                        :caption,
                        :tags,
                        CAST(:engagement AS jsonb),
                        :adult_classification,
                        :explicitness_score,
                        :provenance_hint,
                        :availability,
                        CAST(:connector_metadata AS jsonb)
                    )
                    ON CONFLICT (source_task_id, source, source_id) DO UPDATE
                    SET source_url = EXCLUDED.source_url,
                        author = EXCLUDED.author,
                        published_at = EXCLUDED.published_at,
                        media_type = EXCLUDED.media_type,
                        duration_ms = EXCLUDED.duration_ms,
                        width = EXCLUDED.width,
                        height = EXCLUDED.height,
                        title = EXCLUDED.title,
                        caption = EXCLUDED.caption,
                        tags = EXCLUDED.tags,
                        engagement = EXCLUDED.engagement,
                        adult_classification = EXCLUDED.adult_classification,
                        explicitness_score = EXCLUDED.explicitness_score,
                        provenance_hint = EXCLUDED.provenance_hint,
                        availability = EXCLUDED.availability,
                        connector_metadata = EXCLUDED.connector_metadata
                    RETURNING id
                    """
                ),
                {
                    "tenant_id": str(tenant_id.value),
                    "source_task_id": str(task_id),
                    "source": candidate.source,
                    "source_id": candidate.source_id,
                    "source_url": candidate.source_url,
                    "author": candidate.author,
                    "published_at": candidate.published_at,
                    "media_type": candidate.media_type,
                    "duration_ms": candidate.duration_ms,
                    "width": candidate.width,
                    "height": candidate.height,
                    "title": candidate.title,
                    "caption": candidate.caption,
                    "tags": list(candidate.tags),
                    "engagement": _json_text(dict(candidate.engagement)),
                    "adult_classification": candidate.adult_classification.value,
                    "explicitness_score": candidate.explicitness_score,
                    "provenance_hint": candidate.provenance_hint,
                    "availability": candidate.availability,
                    "connector_metadata": _json_text(dict(candidate.connector_metadata)),
                },
            ).scalar_one()
            persisted.append(
                CandidateContent(
                    id=_require_uuid(row, "candidate id"),
                    source=candidate.source,
                    source_id=candidate.source_id,
                    source_url=candidate.source_url,
                    author=candidate.author,
                    published_at=candidate.published_at,
                    media_type=candidate.media_type,
                    duration_ms=candidate.duration_ms,
                    width=candidate.width,
                    height=candidate.height,
                    title=candidate.title,
                    caption=candidate.caption,
                    tags=candidate.tags,
                    engagement=candidate.engagement,
                    adult_classification=candidate.adult_classification,
                    explicitness_score=candidate.explicitness_score,
                    provenance_hint=candidate.provenance_hint,
                    availability=candidate.availability,
                    connector_metadata=candidate.connector_metadata,
                )
            )
        return tuple(persisted)

    def list_candidates(
        self,
        session: Session,
        task_id: UUID,
        *,
        limit: int = 5,
    ) -> tuple[CandidateContent, ...]:
        rows = session.execute(
            text(
                """
                SELECT id, source, source_id, source_url, author, published_at,
                       media_type, duration_ms, width, height, title, caption, tags,
                       engagement, adult_classification, explicitness_score,
                       provenance_hint, availability, connector_metadata
                FROM source_task_candidate
                WHERE source_task_id = :source_task_id
                ORDER BY created_at ASC, id ASC
                LIMIT :limit
                """
            ),
            {"source_task_id": str(task_id), "limit": limit},
        ).mappings().all()
        return tuple(
            _candidate_from_row(cast(Mapping[str, object], row)) for row in rows
        )

    def select_candidate(
        self,
        session: Session,
        *,
        candidate_id: UUID,
        actor_user_id: UUID,
    ) -> bool:
        selected_id = session.execute(
            text(
                """
                UPDATE source_task_candidate AS candidate
                SET selected_at = COALESCE(selected_at, clock_timestamp()),
                    selected_by_user_id = COALESCE(selected_by_user_id, :actor_user_id)
                FROM source_task AS task
                WHERE candidate.id = :candidate_id
                  AND candidate.source_task_id = task.id
                  AND task.actor_user_id = :actor_user_id
                RETURNING candidate.id::text
                """
            ),
            {
                "candidate_id": str(candidate_id),
                "actor_user_id": str(actor_user_id),
            },
        ).scalar_one_or_none()
        return selected_id is not None

    def resolve_tenant(
        self,
        session: Session,
        *,
        operation_key: OperationKey,
        execution_token: UUID,
    ) -> TenantId:
        raw = session.execute(
            text(
                """
                SELECT resolve_source_task_tenant(
                    :operation_key,
                    CAST(:execution_token AS uuid)
                )
                """
            ),
            {
                "operation_key": operation_key.value,
                "execution_token": str(execution_token),
            },
        ).scalar_one_or_none()
        if raw is None:
            raise RuntimeError("source task execution authority was not found")
        return TenantId(_require_uuid(raw, "resolved_tenant_id"))


def _source_task_from_row(row: Mapping[str, object]) -> SourceTask:
    return SourceTask(
        id=_require_uuid(row["id"], "id"),
        tenant_id=TenantId(_require_uuid(row["tenant_id"], "tenant_id")),
        actor_user_id=_require_uuid(row["actor_user_id"], "actor_user_id"),
        operation_key=OperationKey(_require_str(row["operation_key"], "operation_key")),
        execution_token=_require_uuid(row["execution_token"], "execution_token"),
        source_mode=SourceMode(_require_str(row["source_mode"], "source_mode")),
        user_intent=_require_str(row["user_intent"], "user_intent"),
        requested_sources=_require_text_tuple(
            row["requested_sources"], "requested_sources"
        ),
        preferred_languages=_require_text_tuple(
            row["preferred_languages"], "preferred_languages"
        ),
        state=SourceTaskState(_require_str(row["state"], "state")),
        failure_code=_optional_str(row["failure_code"]),
        telegram_update_id=_optional_int(row["telegram_update_id"]),
        telegram_message_id=_optional_int(row["telegram_message_id"]),
        telegram_chat_id=_optional_int(row["telegram_chat_id"]),
        locale=_require_str(row["locale"], "locale"),
    )


def _candidate_from_row(row: Mapping[str, object]) -> CandidateContent:
    engagement = _int_mapping(row["engagement"])
    connector_metadata = _object_mapping(row["connector_metadata"])
    published_at = row["published_at"]
    return CandidateContent(
        id=_require_uuid(row["id"], "id"),
        source=_require_str(row["source"], "source"),
        source_id=_require_str(row["source_id"], "source_id"),
        source_url=_require_str(row["source_url"], "source_url"),
        author=_optional_str(row["author"]),
        published_at=published_at if isinstance(published_at, datetime) else None,
        media_type=_require_str(row["media_type"], "media_type"),
        duration_ms=_optional_int(row["duration_ms"]),
        width=_optional_int(row["width"]),
        height=_optional_int(row["height"]),
        title=_optional_str(row["title"]),
        caption=_optional_str(row["caption"]),
        tags=_require_text_tuple(row["tags"], "tags"),
        engagement=engagement,
        adult_classification=AdultClassification(
            _require_str(row["adult_classification"], "adult_classification")
        ),
        explicitness_score=_optional_float(row["explicitness_score"]),
        provenance_hint=_require_str(row["provenance_hint"], "provenance_hint"),
        availability=_require_str(row["availability"], "availability"),
        connector_metadata=connector_metadata,
    )


def _json_text(value: object) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _require_uuid(value: object, name: str) -> UUID:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        return UUID(value)
    raise RuntimeError(f"{name} must be a UUID")


def _require_str(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise RuntimeError(f"{name} must be text")
    return value


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _optional_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def _require_text_tuple(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise RuntimeError(f"{name} must be a text array")
    items = cast(list[object] | tuple[object, ...], value)
    result: list[str] = []
    for item in items:
        if not isinstance(item, str):
            raise RuntimeError(f"{name} must contain only text values")
        result.append(item)
    return tuple(result)


def _int_mapping(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    raw = cast(dict[object, object], value)
    result: dict[str, int] = {}
    for key, item in raw.items():
        if isinstance(key, str) and isinstance(item, int) and not isinstance(item, bool):
            result[key] = item
    return result


def _object_mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    raw = cast(dict[object, object], value)
    return {key: item for key, item in raw.items() if isinstance(key, str)}
