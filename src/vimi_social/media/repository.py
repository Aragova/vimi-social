from collections.abc import Mapping
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from vimi_social.domain.media import (
    BaseAdultClassification,
    BaseContentClassification,
    MediaAsset,
    MediaPreparation,
    MediaPreparationState,
    MediaProbeResult,
    RightsBasis,
)
from vimi_social.domain.source import AdultClassification, CandidateContent
from vimi_social.media.secure_ingest.models import FetchResult


class MediaPreparationRepository:
    def select_candidate(
        self,
        session: Session,
        *,
        candidate_id: UUID,
        actor_user_id: UUID,
    ) -> MediaPreparation | None:
        selected = session.execute(
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
            {"candidate_id": str(candidate_id), "actor_user_id": str(actor_user_id)},
        ).scalar_one_or_none()
        if selected is None:
            return None

        session.execute(
            text(
                """
                INSERT INTO media_preparation (
                    tenant_id, candidate_id, operation_key, rights_basis, state
                )
                SELECT candidate.tenant_id,
                       candidate.id,
                       'media-prep:' || candidate.id::text,
                       'UNKNOWN',
                       'AWAITING_RIGHTS'
                FROM source_task_candidate AS candidate
                WHERE candidate.id = :candidate_id
                ON CONFLICT (candidate_id) DO NOTHING
                """
            ),
            {"candidate_id": str(candidate_id)},
        )
        return self.get_by_candidate(session, candidate_id, actor_user_id=actor_user_id)

    def get_by_candidate(
        self,
        session: Session,
        candidate_id: UUID,
        *,
        actor_user_id: UUID | None = None,
    ) -> MediaPreparation | None:
        actor_clause = "" if actor_user_id is None else "AND task.actor_user_id = :actor_user_id"
        params: dict[str, object] = {"candidate_id": str(candidate_id)}
        if actor_user_id is not None:
            params["actor_user_id"] = str(actor_user_id)
        row = session.execute(
            text(
                f"""
                SELECT preparation.id,
                       preparation.tenant_id,
                       preparation.candidate_id,
                       preparation.operation_key,
                       preparation.rights_basis,
                       preparation.state,
                       preparation.failure_code,
                       task.operation_key AS source_task_operation_key,
                       task.execution_token AS source_task_execution_token
                FROM media_preparation AS preparation
                JOIN source_task_candidate AS candidate
                  ON candidate.id = preparation.candidate_id
                 AND candidate.tenant_id = preparation.tenant_id
                JOIN source_task AS task
                  ON task.id = candidate.source_task_id
                 AND task.tenant_id = preparation.tenant_id
                WHERE preparation.candidate_id = :candidate_id
                  {actor_clause}
                """
            ),
            params,
        ).mappings().one_or_none()
        return _preparation_from_row(cast(Mapping[str, object], row)) if row is not None else None

    def get_by_id(self, session: Session, preparation_id: UUID) -> MediaPreparation | None:
        row = session.execute(
            text(
                """
                SELECT preparation.id,
                       preparation.tenant_id,
                       preparation.candidate_id,
                       preparation.operation_key,
                       preparation.rights_basis,
                       preparation.state,
                       preparation.failure_code,
                       task.operation_key AS source_task_operation_key,
                       task.execution_token AS source_task_execution_token
                FROM media_preparation AS preparation
                JOIN source_task_candidate AS candidate
                  ON candidate.id = preparation.candidate_id
                 AND candidate.tenant_id = preparation.tenant_id
                JOIN source_task AS task
                  ON task.id = candidate.source_task_id
                 AND task.tenant_id = preparation.tenant_id
                WHERE preparation.id = :preparation_id
                """
            ),
            {"preparation_id": str(preparation_id)},
        ).mappings().one_or_none()
        return _preparation_from_row(cast(Mapping[str, object], row)) if row is not None else None

    def confirm_rights(
        self,
        session: Session,
        *,
        preparation_id: UUID,
        actor_user_id: UUID,
    ) -> MediaPreparation | None:
        candidate_id = session.execute(
            text(
                """
                UPDATE media_preparation AS preparation
                SET rights_basis = 'USER_CONFIRMED',
                    rights_confirmed_by_user_id = :actor_user_id,
                    rights_confirmed_at = COALESCE(rights_confirmed_at, clock_timestamp()),
                    state = CASE
                        WHEN state = 'AWAITING_RIGHTS' THEN 'QUEUED'
                        ELSE state
                    END,
                    updated_at = clock_timestamp()
                FROM source_task_candidate AS candidate,
                     source_task AS task
                WHERE preparation.id = :preparation_id
                  AND candidate.id = preparation.candidate_id
                  AND candidate.tenant_id = preparation.tenant_id
                  AND task.id = candidate.source_task_id
                  AND task.tenant_id = preparation.tenant_id
                  AND task.actor_user_id = :actor_user_id
                  AND preparation.state IN ('AWAITING_RIGHTS', 'QUEUED')
                RETURNING preparation.candidate_id::text
                """
            ),
            {"preparation_id": str(preparation_id), "actor_user_id": str(actor_user_id)},
        ).scalar_one_or_none()
        if candidate_id is None:
            return None
        return self.get_by_candidate(session, UUID(candidate_id), actor_user_id=actor_user_id)

    def decline_rights(
        self,
        session: Session,
        *,
        preparation_id: UUID,
        actor_user_id: UUID,
    ) -> bool:
        return (
            session.execute(
                text(
                    """
                    UPDATE media_preparation AS preparation
                    SET state = 'BLOCKED',
                        failure_code = 'RIGHTS_NOT_CONFIRMED',
                        updated_at = clock_timestamp()
                    FROM source_task_candidate AS candidate,
                         source_task AS task
                    WHERE preparation.id = :preparation_id
                      AND candidate.id = preparation.candidate_id
                      AND candidate.tenant_id = preparation.tenant_id
                      AND task.id = candidate.source_task_id
                      AND task.tenant_id = preparation.tenant_id
                      AND task.actor_user_id = :actor_user_id
                      AND preparation.state = 'AWAITING_RIGHTS'
                    RETURNING preparation.id::text
                    """
                ),
                {"preparation_id": str(preparation_id), "actor_user_id": str(actor_user_id)},
            ).scalar_one_or_none()
            is not None
        )

    def load_candidate(self, session: Session, preparation_id: UUID) -> CandidateContent | None:
        row = session.execute(
            text(
                """
                SELECT candidate.id, candidate.source, candidate.source_id, candidate.source_url,
                       candidate.author, candidate.published_at, candidate.media_type,
                       candidate.duration_ms, candidate.width, candidate.height,
                       candidate.title, candidate.caption, candidate.tags, candidate.engagement,
                       candidate.adult_classification, candidate.explicitness_score,
                       candidate.provenance_hint, candidate.availability,
                       candidate.connector_metadata
                FROM source_task_candidate AS candidate
                JOIN media_preparation AS preparation
                  ON preparation.candidate_id = candidate.id
                 AND preparation.tenant_id = candidate.tenant_id
                WHERE preparation.id = :preparation_id
                """
            ),
            {"preparation_id": str(preparation_id)},
        ).mappings().one_or_none()
        return _candidate_from_row(cast(Mapping[str, object], row)) if row is not None else None

    def claim_acquisition(self, session: Session, preparation_id: UUID) -> MediaPreparationState:
        state = session.execute(
            text(
                """
                UPDATE media_preparation
                SET state = 'ACQUIRING', updated_at = clock_timestamp()
                WHERE id = :preparation_id AND state = 'QUEUED'
                RETURNING state
                """
            ),
            {"preparation_id": str(preparation_id)},
        ).scalar_one_or_none()
        if state is not None:
            return MediaPreparationState(str(state))
        existing = session.execute(
            text("SELECT state FROM media_preparation WHERE id = :preparation_id"),
            {"preparation_id": str(preparation_id)},
        ).scalar_one_or_none()
        if existing is None:
            raise RuntimeError("media preparation was not found in tenant context")
        return MediaPreparationState(str(existing))

    def persist_asset(
        self,
        session: Session,
        *,
        preparation: MediaPreparation,
        fetch: FetchResult,
        storage_path: str,
        probe: MediaProbeResult,
        classification: BaseContentClassification,
    ) -> MediaAsset:
        session.execute(
            text(
                """
                INSERT INTO media_asset (
                    tenant_id, candidate_id, preparation_id, sha256, storage_path,
                    size_bytes, media_format, content_type, final_url,
                    duration_ms, width, height, video_codec, audio_codec, container,
                    frame_rate, has_audio, adult_classification, explicitness_score,
                    classifier_version, classification_signals
                ) VALUES (
                    :tenant_id, :candidate_id, :preparation_id, :sha256, :storage_path,
                    :size_bytes, :media_format, :content_type, :final_url,
                    :duration_ms, :width, :height, :video_codec, :audio_codec, :container,
                    :frame_rate, :has_audio, :adult_classification, :explicitness_score,
                    :classifier_version, :classification_signals
                )
                ON CONFLICT (preparation_id) DO NOTHING
                """
            ),
            {
                "tenant_id": str(preparation.tenant_id),
                "candidate_id": str(preparation.candidate_id),
                "preparation_id": str(preparation.id),
                "sha256": fetch.sha256,
                "storage_path": storage_path,
                "size_bytes": fetch.size_bytes,
                "media_format": fetch.media_format,
                "content_type": fetch.content_type,
                "final_url": fetch.final_url,
                "duration_ms": probe.duration_ms,
                "width": probe.width,
                "height": probe.height,
                "video_codec": probe.video_codec,
                "audio_codec": probe.audio_codec,
                "container": probe.container,
                "frame_rate": probe.frame_rate,
                "has_audio": probe.has_audio,
                "adult_classification": classification.adult.value,
                "explicitness_score": classification.explicitness_score,
                "classifier_version": classification.classifier_version,
                "classification_signals": list(classification.signals),
            },
        )
        session.execute(
            text(
                """
                UPDATE media_preparation
                SET state = 'READY', failure_code = NULL, updated_at = clock_timestamp()
                WHERE id = :preparation_id AND state IN ('QUEUED', 'ACQUIRING', 'READY')
                """
            ),
            {"preparation_id": str(preparation.id)},
        )
        asset = self.get_asset(session, preparation.id)
        if asset is None:
            raise RuntimeError("media asset persistence failed")
        return asset

    def get_asset(self, session: Session, preparation_id: UUID) -> MediaAsset | None:
        row = session.execute(
            text(
                """
                SELECT * FROM media_asset WHERE preparation_id = :preparation_id
                """
            ),
            {"preparation_id": str(preparation_id)},
        ).mappings().one_or_none()
        return _asset_from_row(cast(Mapping[str, object], row)) if row is not None else None

    def fail_safe(
        self,
        session: Session,
        *,
        preparation_id: UUID,
        failure_code: str,
    ) -> MediaPreparationState:
        state = session.execute(
            text(
                """
                UPDATE media_preparation
                SET state = 'FAILED_SAFE',
                    failure_code = :failure_code,
                    updated_at = clock_timestamp()
                WHERE id = :preparation_id
                  AND state IN ('QUEUED', 'ACQUIRING')
                RETURNING state
                """
            ),
            {"preparation_id": str(preparation_id), "failure_code": failure_code},
        ).scalar_one_or_none()
        if state is not None:
            return MediaPreparationState(str(state))
        existing = session.execute(
            text("SELECT state FROM media_preparation WHERE id = :preparation_id"),
            {"preparation_id": str(preparation_id)},
        ).scalar_one()
        return MediaPreparationState(str(existing))


def _preparation_from_row(row: Mapping[str, object]) -> MediaPreparation:
    return MediaPreparation(
        id=_uuid(row["id"]),
        tenant_id=_uuid(row["tenant_id"]),
        candidate_id=_uuid(row["candidate_id"]),
        operation_key=_str(row["operation_key"]),
        rights_basis=RightsBasis(_str(row["rights_basis"])),
        state=MediaPreparationState(_str(row["state"])),
        failure_code=_optional_str(row["failure_code"]),
        source_task_operation_key=_str(row["source_task_operation_key"]),
        source_task_execution_token=_uuid(row["source_task_execution_token"]),
    )


def _candidate_from_row(row: Mapping[str, object]) -> CandidateContent:
    published = row["published_at"]
    engagement_obj = row["engagement"]
    metadata_obj = row["connector_metadata"]
    return CandidateContent(
        id=_uuid(row["id"]),
        source=_str(row["source"]),
        source_id=_str(row["source_id"]),
        source_url=_str(row["source_url"]),
        author=_optional_str(row["author"]),
        published_at=published if isinstance(published, datetime) else None,
        media_type=_str(row["media_type"]),
        duration_ms=_optional_int(row["duration_ms"]),
        width=_optional_int(row["width"]),
        height=_optional_int(row["height"]),
        title=_optional_str(row["title"]),
        caption=_optional_str(row["caption"]),
        tags=_str_tuple(row["tags"]),
        engagement=_int_mapping(engagement_obj),
        adult_classification=AdultClassification(_str(row["adult_classification"])),
        explicitness_score=_optional_float(row["explicitness_score"]),
        provenance_hint=_str(row["provenance_hint"]),
        availability=_str(row["availability"]),
        connector_metadata=_object_mapping(metadata_obj),
    )


def _asset_from_row(row: Mapping[str, object]) -> MediaAsset:
    classification = BaseContentClassification(
        adult=BaseAdultClassification(_str(row["adult_classification"])),
        explicitness_score=_optional_float(row["explicitness_score"]),
        classifier_version=_str(row["classifier_version"]),
        signals=_str_tuple(row["classification_signals"]),
    )
    probe = MediaProbeResult(
        duration_ms=_optional_int(row["duration_ms"]),
        width=_optional_int(row["width"]),
        height=_optional_int(row["height"]),
        video_codec=_optional_str(row["video_codec"]),
        audio_codec=_optional_str(row["audio_codec"]),
        container=_optional_str(row["container"]),
        frame_rate=_optional_float(row["frame_rate"]),
        has_audio=row["has_audio"] is True,
    )
    return MediaAsset(
        id=_uuid(row["id"]),
        tenant_id=_uuid(row["tenant_id"]),
        candidate_id=_uuid(row["candidate_id"]),
        preparation_id=_uuid(row["preparation_id"]),
        sha256=_str(row["sha256"]),
        storage_path=_str(row["storage_path"]),
        size_bytes=_int(row["size_bytes"]),
        media_format=_str(row["media_format"]),
        content_type=_str(row["content_type"]),
        final_url=_str(row["final_url"]),
        probe=probe,
        classification=classification,
    )


def _uuid(value: object) -> UUID:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        return UUID(value)
    raise RuntimeError("expected UUID")


def _str(value: object) -> str:
    if not isinstance(value, str):
        raise RuntimeError("expected text")
    return value


def _int(value: object) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    raise RuntimeError("expected integer")


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _optional_float(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _str_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(item for item in cast(list[object] | tuple[object, ...], value) if isinstance(item, str))


def _int_mapping(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, int] = {}
    for key, item in cast(dict[object, object], value).items():
        if isinstance(key, str) and isinstance(item, int) and not isinstance(item, bool):
            result[key] = item
    return result


def _object_mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {key: item for key, item in cast(dict[object, object], value).items() if isinstance(key, str)}
