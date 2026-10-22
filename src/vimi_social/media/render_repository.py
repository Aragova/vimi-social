from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from vimi_social.domain.analysis import PolicyDecision, RenderStrategy
from vimi_social.domain.publication import VariantArtifact, VariantArtifactState


@dataclass(frozen=True, slots=True)
class RenderInput:
    tenant_id: UUID
    analysis_id: UUID
    plan_id: UUID
    asset_id: UUID
    destination: str
    decision: PolicyDecision
    strategy: RenderStrategy
    expected_duration_ms: int
    asset_storage_path: str
    asset_sha256: str
    asset_size_bytes: int
    has_audio: bool
    segments: tuple[tuple[int, int], ...]


@dataclass(frozen=True, slots=True)
class RenderClaim:
    state: VariantArtifactState
    attempt_token: UUID | None
    owns_attempt: bool


class RenderOwnershipLost(RuntimeError):
    pass


class VariantRenderRepository:
    def load_input(
        self,
        session: Session,
        *,
        analysis_id: UUID,
        destination: str,
    ) -> RenderInput | None:
        row = session.execute(
            text(
                """
                SELECT analysis.tenant_id,
                       analysis.id AS analysis_id,
                       plan.id AS plan_id,
                       plan.asset_id,
                       plan.destination,
                       plan.decision,
                       plan.render_strategy,
                       plan.expected_duration_ms,
                       asset.storage_path,
                       asset.sha256,
                       asset.size_bytes,
                       asset.has_audio
                FROM media_analysis AS analysis
                JOIN variant_plan AS plan
                  ON plan.analysis_id = analysis.id
                 AND plan.tenant_id = analysis.tenant_id
                JOIN media_asset AS asset
                  ON asset.id = plan.asset_id
                 AND asset.tenant_id = plan.tenant_id
                WHERE analysis.id = :analysis_id
                  AND analysis.state = 'READY'
                  AND plan.destination = :destination
                """
            ),
            {"analysis_id": str(analysis_id), "destination": destination},
        ).mappings().one_or_none()
        if row is None:
            return None
        mapped = cast(Mapping[str, object], row)
        strategy_raw = mapped["render_strategy"]
        duration_raw = mapped["expected_duration_ms"]
        if strategy_raw is None or duration_raw is None:
            return None
        segments_rows = session.execute(
            text(
                """
                SELECT start_ms, end_ms
                FROM variant_plan_segment
                WHERE plan_id = :plan_id
                ORDER BY sequence_index
                """
            ),
            {"plan_id": str(mapped["plan_id"])},
        ).all()
        return RenderInput(
            tenant_id=UUID(str(mapped["tenant_id"])),
            analysis_id=UUID(str(mapped["analysis_id"])),
            plan_id=UUID(str(mapped["plan_id"])),
            asset_id=UUID(str(mapped["asset_id"])),
            destination=str(mapped["destination"]),
            decision=PolicyDecision(str(mapped["decision"])),
            strategy=RenderStrategy(str(strategy_raw)),
            expected_duration_ms=int(duration_raw),
            asset_storage_path=str(mapped["storage_path"]),
            asset_sha256=str(mapped["sha256"]),
            asset_size_bytes=int(mapped["size_bytes"]),
            has_audio=bool(mapped["has_audio"]),
            segments=tuple((int(item.start_ms), int(item.end_ms)) for item in segments_rows),
        )

    def ensure_artifact(self, session: Session, render_input: RenderInput) -> VariantArtifact:
        operation_key = f"render:{render_input.plan_id}"
        session.execute(
            text(
                """
                INSERT INTO variant_artifact (
                    tenant_id, plan_id, asset_id, operation_key, state
                ) VALUES (
                    :tenant_id, :plan_id, :asset_id, :operation_key, 'QUEUED'
                )
                ON CONFLICT (plan_id) DO NOTHING
                """
            ),
            {
                "tenant_id": str(render_input.tenant_id),
                "plan_id": str(render_input.plan_id),
                "asset_id": str(render_input.asset_id),
                "operation_key": operation_key,
            },
        )
        artifact = self.get_by_plan(session, render_input.plan_id)
        if artifact is None:
            raise RuntimeError("variant artifact persistence failed")
        return artifact

    def get_by_plan(self, session: Session, plan_id: UUID) -> VariantArtifact | None:
        row = session.execute(
            text("SELECT * FROM variant_artifact WHERE plan_id = :plan_id"),
            {"plan_id": str(plan_id)},
        ).mappings().one_or_none()
        return _artifact_from_row(cast(Mapping[str, object], row)) if row is not None else None

    def get_by_id(self, session: Session, artifact_id: UUID) -> VariantArtifact | None:
        row = session.execute(
            text("SELECT * FROM variant_artifact WHERE id = :artifact_id"),
            {"artifact_id": str(artifact_id)},
        ).mappings().one_or_none()
        return _artifact_from_row(cast(Mapping[str, object], row)) if row is not None else None

    def claim_render(
        self,
        session: Session,
        artifact_id: UUID,
        attempt_token: UUID,
    ) -> RenderClaim:
        state = session.execute(
            text(
                """
                UPDATE variant_artifact
                SET state = 'RENDERING',
                    render_attempt_token = :attempt_token,
                    updated_at = clock_timestamp()
                WHERE id = :artifact_id AND state = 'QUEUED'
                RETURNING state
                """
            ),
            {"artifact_id": str(artifact_id), "attempt_token": str(attempt_token)},
        ).scalar_one_or_none()
        if state is not None:
            return RenderClaim(VariantArtifactState(str(state)), attempt_token, True)
        row = session.execute(
            text(
                "SELECT state, render_attempt_token FROM variant_artifact WHERE id = :artifact_id"
            ),
            {"artifact_id": str(artifact_id)},
        ).mappings().one_or_none()
        if row is None:
            raise RuntimeError("variant artifact was not found in tenant context")
        existing_state = VariantArtifactState(str(row["state"]))
        existing_token = _optional_uuid(row["render_attempt_token"])
        return RenderClaim(
            existing_state,
            existing_token,
            existing_state is VariantArtifactState.RENDERING and existing_token == attempt_token,
        )

    def fail_ambiguous(
        self,
        session: Session,
        *,
        artifact_id: UUID,
        observed_attempt_token: UUID,
    ) -> VariantArtifactState:
        state = session.execute(
            text(
                """
                UPDATE variant_artifact
                SET state = 'FAILED_SAFE',
                    render_attempt_token = NULL,
                    failure_code = 'RENDER_ATTEMPT_AMBIGUOUS',
                    updated_at = clock_timestamp()
                WHERE id = :artifact_id
                  AND state = 'RENDERING'
                  AND render_attempt_token = :attempt_token
                RETURNING state
                """
            ),
            {"artifact_id": str(artifact_id), "attempt_token": str(observed_attempt_token)},
        ).scalar_one_or_none()
        if state is not None:
            return VariantArtifactState(str(state))
        return VariantArtifactState(
            str(
                session.execute(
                    text("SELECT state FROM variant_artifact WHERE id = :artifact_id"),
                    {"artifact_id": str(artifact_id)},
                ).scalar_one()
            )
        )

    def persist_ready(
        self,
        session: Session,
        *,
        artifact_id: UUID,
        attempt_token: UUID,
        sha256: str,
        storage_path: str,
        size_bytes: int,
        duration_ms: int,
    ) -> VariantArtifact:
        updated = session.execute(
            text(
                """
                UPDATE variant_artifact
                SET state = 'READY',
                    render_attempt_token = NULL,
                    sha256 = :sha256,
                    storage_path = :storage_path,
                    size_bytes = :size_bytes,
                    duration_ms = :duration_ms,
                    failure_code = NULL,
                    updated_at = clock_timestamp()
                WHERE id = :artifact_id
                  AND state = 'RENDERING'
                  AND render_attempt_token = :attempt_token
                RETURNING id::text
                """
            ),
            {
                "artifact_id": str(artifact_id),
                "attempt_token": str(attempt_token),
                "sha256": sha256,
                "storage_path": storage_path,
                "size_bytes": size_bytes,
                "duration_ms": duration_ms,
            },
        ).scalar_one_or_none()
        if updated is None:
            raise RenderOwnershipLost("render attempt no longer owns the artifact")
        artifact = self.get_by_id(session, artifact_id)
        if artifact is None:
            raise RuntimeError("ready variant artifact disappeared")
        return artifact

    def persist_passthrough(
        self,
        session: Session,
        *,
        artifact_id: UUID,
        attempt_token: UUID,
        render_input: RenderInput,
    ) -> VariantArtifact:
        return self.persist_ready(
            session,
            artifact_id=artifact_id,
            attempt_token=attempt_token,
            sha256=render_input.asset_sha256,
            storage_path=render_input.asset_storage_path,
            size_bytes=render_input.asset_size_bytes,
            duration_ms=render_input.expected_duration_ms,
        )

    def fail_safe(
        self,
        session: Session,
        *,
        artifact_id: UUID,
        attempt_token: UUID,
        failure_code: str,
    ) -> VariantArtifactState:
        state = session.execute(
            text(
                """
                UPDATE variant_artifact
                SET state = 'FAILED_SAFE',
                    render_attempt_token = NULL,
                    failure_code = :failure_code,
                    updated_at = clock_timestamp()
                WHERE id = :artifact_id
                  AND state = 'RENDERING'
                  AND render_attempt_token = :attempt_token
                RETURNING state
                """
            ),
            {
                "artifact_id": str(artifact_id),
                "attempt_token": str(attempt_token),
                "failure_code": failure_code,
            },
        ).scalar_one_or_none()
        if state is not None:
            return VariantArtifactState(str(state))
        current = session.execute(
            text("SELECT state FROM variant_artifact WHERE id = :artifact_id"),
            {"artifact_id": str(artifact_id)},
        ).scalar_one()
        return VariantArtifactState(str(current))


def _artifact_from_row(row: Mapping[str, object]) -> VariantArtifact:
    return VariantArtifact(
        id=UUID(str(row["id"])),
        tenant_id=UUID(str(row["tenant_id"])),
        plan_id=UUID(str(row["plan_id"])),
        asset_id=UUID(str(row["asset_id"])),
        operation_key=str(row["operation_key"]),
        state=VariantArtifactState(str(row["state"])),
        render_attempt_token=_optional_uuid(row["render_attempt_token"]),
        sha256=_optional_str(row["sha256"]),
        storage_path=_optional_str(row["storage_path"]),
        size_bytes=_optional_int(row["size_bytes"]),
        duration_ms=_optional_int(row["duration_ms"]),
        failure_code=_optional_str(row["failure_code"]),
    )


def _optional_uuid(value: object) -> UUID | None:
    return None if value is None else UUID(str(value))


def _optional_str(value: object) -> str | None:
    return None if value is None else str(value)


def _optional_int(value: object) -> int | None:
    return None if value is None else int(str(value))
