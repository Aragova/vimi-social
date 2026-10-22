from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from vimi_social.domain.analysis import (
    MediaAnalysis,
    MediaAnalysisResult,
    PolicyDecision,
    RankedScene,
    RenderStrategy,
    SceneAnalysisState,
    VariantPlan,
)
from vimi_social.domain.media import MediaAsset


@dataclass(frozen=True, slots=True)
class AnalysisClaim:
    state: SceneAnalysisState
    attempt_token: UUID | None
    owns_attempt: bool


class MediaAnalysisOwnershipLost(RuntimeError):
    pass


class MediaAnalysisRepository:
    def ensure_analysis(self, session: Session, asset: MediaAsset) -> MediaAnalysis:
        session.execute(
            text(
                """
                INSERT INTO media_analysis (
                    tenant_id, asset_id, preparation_id, operation_key, state
                ) VALUES (
                    :tenant_id, :asset_id, :preparation_id, :operation_key, 'QUEUED'
                )
                ON CONFLICT (asset_id) DO NOTHING
                """
            ),
            {
                "tenant_id": str(asset.tenant_id),
                "asset_id": str(asset.id),
                "preparation_id": str(asset.preparation_id),
                "operation_key": f"scene-analysis:{asset.id}",
            },
        )
        analysis = self.get_by_asset(session, asset.id)
        if analysis is None:
            raise RuntimeError("media analysis persistence failed")
        return analysis

    def get_by_asset(self, session: Session, asset_id: UUID) -> MediaAnalysis | None:
        row = session.execute(
            text("SELECT * FROM media_analysis WHERE asset_id = :asset_id"),
            {"asset_id": str(asset_id)},
        ).mappings().one_or_none()
        return _analysis_from_row(cast(Mapping[str, object], row)) if row is not None else None

    def claim_analysis(
        self,
        session: Session,
        analysis_id: UUID,
        attempt_token: UUID,
    ) -> AnalysisClaim:
        state = session.execute(
            text(
                """
                UPDATE media_analysis
                SET state = 'ANALYZING',
                    analysis_attempt_token = :attempt_token,
                    updated_at = clock_timestamp()
                WHERE id = :analysis_id AND state = 'QUEUED'
                RETURNING state
                """
            ),
            {"analysis_id": str(analysis_id), "attempt_token": str(attempt_token)},
        ).scalar_one_or_none()
        if state is not None:
            return AnalysisClaim(
                state=SceneAnalysisState(str(state)),
                attempt_token=attempt_token,
                owns_attempt=True,
            )

        row = session.execute(
            text(
                """
                SELECT state, analysis_attempt_token
                FROM media_analysis
                WHERE id = :analysis_id
                """
            ),
            {"analysis_id": str(analysis_id)},
        ).mappings().one_or_none()
        if row is None:
            raise RuntimeError("media analysis was not found in tenant context")
        existing_state = SceneAnalysisState(_str(row["state"]))
        existing_token = _optional_uuid(row["analysis_attempt_token"])
        return AnalysisClaim(
            state=existing_state,
            attempt_token=existing_token,
            owns_attempt=(
                existing_state is SceneAnalysisState.ANALYZING
                and existing_token == attempt_token
            ),
        )

    def fail_ambiguous(
        self,
        session: Session,
        *,
        analysis_id: UUID,
        observed_attempt_token: UUID,
    ) -> SceneAnalysisState:
        state = session.execute(
            text(
                """
                UPDATE media_analysis
                SET state = 'FAILED_SAFE',
                    analysis_attempt_token = NULL,
                    failure_code = 'ANALYSIS_ATTEMPT_AMBIGUOUS',
                    updated_at = clock_timestamp()
                WHERE id = :analysis_id
                  AND state = 'ANALYZING'
                  AND analysis_attempt_token = :observed_attempt_token
                RETURNING state
                """
            ),
            {
                "analysis_id": str(analysis_id),
                "observed_attempt_token": str(observed_attempt_token),
            },
        ).scalar_one_or_none()
        if state is not None:
            return SceneAnalysisState(str(state))
        existing = session.execute(
            text("SELECT state FROM media_analysis WHERE id = :analysis_id"),
            {"analysis_id": str(analysis_id)},
        ).scalar_one()
        return SceneAnalysisState(str(existing))

    def fail_safe(
        self,
        session: Session,
        *,
        analysis_id: UUID,
        attempt_token: UUID,
        failure_code: str,
    ) -> SceneAnalysisState:
        state = session.execute(
            text(
                """
                UPDATE media_analysis
                SET state = 'FAILED_SAFE',
                    analysis_attempt_token = NULL,
                    failure_code = :failure_code,
                    updated_at = clock_timestamp()
                WHERE id = :analysis_id
                  AND state = 'ANALYZING'
                  AND analysis_attempt_token = :attempt_token
                RETURNING state
                """
            ),
            {
                "analysis_id": str(analysis_id),
                "attempt_token": str(attempt_token),
                "failure_code": failure_code,
            },
        ).scalar_one_or_none()
        if state is not None:
            return SceneAnalysisState(str(state))
        existing = session.execute(
            text("SELECT state FROM media_analysis WHERE id = :analysis_id"),
            {"analysis_id": str(analysis_id)},
        ).scalar_one()
        return SceneAnalysisState(str(existing))

    def persist_success(
        self,
        session: Session,
        *,
        analysis: MediaAnalysis,
        attempt_token: UUID,
        detector_version: str,
        ranker_version: str,
        scenes: Sequence[RankedScene],
        plan: VariantPlan,
    ) -> None:
        ownership = session.execute(
            text(
                """
                SELECT state, analysis_attempt_token
                FROM media_analysis
                WHERE id = :analysis_id
                FOR UPDATE
                """
            ),
            {"analysis_id": str(analysis.id)},
        ).mappings().one_or_none()
        if ownership is None:
            raise MediaAnalysisOwnershipLost("media analysis disappeared before persistence")
        state = SceneAnalysisState(_str(ownership["state"]))
        current_token = _optional_uuid(ownership["analysis_attempt_token"])
        if state is SceneAnalysisState.READY:
            return
        if state is not SceneAnalysisState.ANALYZING or current_token != attempt_token:
            raise MediaAnalysisOwnershipLost("scene analysis attempt no longer owns the task")

        scene_ids: dict[int, UUID] = {}
        for scene in scenes:
            scene_id = uuid4()
            session.execute(
                text(
                    """
                    INSERT INTO media_scene (
                        id, tenant_id, analysis_id, asset_id, ordinal,
                        start_ms, end_ms, rank_score, adult_classification,
                        explicitness_score, classification_basis, classification_signals
                    ) VALUES (
                        :id, :tenant_id, :analysis_id, :asset_id, :ordinal,
                        :start_ms, :end_ms, :rank_score, :adult_classification,
                        :explicitness_score, :classification_basis, :classification_signals
                    )
                    ON CONFLICT (analysis_id, ordinal) DO NOTHING
                    """
                ),
                {
                    "id": str(scene_id),
                    "tenant_id": str(analysis.tenant_id),
                    "analysis_id": str(analysis.id),
                    "asset_id": str(analysis.asset_id),
                    "ordinal": scene.ordinal,
                    "start_ms": scene.start_ms,
                    "end_ms": scene.end_ms,
                    "rank_score": scene.rank_score,
                    "adult_classification": scene.adult_classification.value,
                    "explicitness_score": scene.explicitness_score,
                    "classification_basis": scene.classification_basis.value,
                    "classification_signals": list(scene.signals),
                },
            )
            persisted_id = session.execute(
                text(
                    """
                    SELECT id::text FROM media_scene
                    WHERE analysis_id = :analysis_id AND ordinal = :ordinal
                    """
                ),
                {"analysis_id": str(analysis.id), "ordinal": scene.ordinal},
            ).scalar_one()
            scene_ids[scene.ordinal] = UUID(str(persisted_id))

        recipe = plan.recipe
        plan_id = UUID(
            session.execute(
                text(
                    """
                    INSERT INTO variant_plan (
                        tenant_id, analysis_id, asset_id, destination, decision,
                        capability_version, policy_version, planner_version,
                        render_strategy, expected_duration_ms, requires_sensitive_label,
                        reason_codes
                    ) VALUES (
                        :tenant_id, :analysis_id, :asset_id, :destination, :decision,
                        :capability_version, :policy_version, :planner_version,
                        :render_strategy, :expected_duration_ms, :requires_sensitive_label,
                        :reason_codes
                    )
                    ON CONFLICT (analysis_id, destination) DO UPDATE SET
                        decision = EXCLUDED.decision
                    RETURNING id::text
                    """
                ),
                {
                    "tenant_id": str(analysis.tenant_id),
                    "analysis_id": str(analysis.id),
                    "asset_id": str(analysis.asset_id),
                    "destination": plan.destination,
                    "decision": plan.decision.value,
                    "capability_version": plan.capability_version,
                    "policy_version": plan.policy_version,
                    "planner_version": plan.planner_version,
                    "render_strategy": recipe.strategy.value if recipe is not None else None,
                    "expected_duration_ms": recipe.expected_duration_ms if recipe is not None else None,
                    "requires_sensitive_label": plan.requires_sensitive_label,
                    "reason_codes": list(plan.reason_codes),
                },
            ).scalar_one()
        )
        if recipe is not None:
            for index, segment in enumerate(recipe.segments):
                scene_id = scene_ids.get(segment.scene_ordinal)
                if scene_id is None:
                    raise ValueError("render recipe references an unknown scene ordinal")
                session.execute(
                    text(
                        """
                        INSERT INTO variant_plan_segment (
                            tenant_id, plan_id, scene_id, sequence_index,
                            start_ms, end_ms, rank_score
                        ) VALUES (
                            :tenant_id, :plan_id, :scene_id, :sequence_index,
                            :start_ms, :end_ms, :rank_score
                        )
                        ON CONFLICT (plan_id, sequence_index) DO NOTHING
                        """
                    ),
                    {
                        "tenant_id": str(analysis.tenant_id),
                        "plan_id": str(plan_id),
                        "scene_id": str(scene_id),
                        "sequence_index": index,
                        "start_ms": segment.start_ms,
                        "end_ms": segment.end_ms,
                        "rank_score": segment.rank_score,
                    },
                )

        updated = session.execute(
            text(
                """
                UPDATE media_analysis
                SET state = 'READY',
                    analysis_attempt_token = NULL,
                    detector_version = :detector_version,
                    ranker_version = :ranker_version,
                    failure_code = NULL,
                    updated_at = clock_timestamp()
                WHERE id = :analysis_id
                  AND state = 'ANALYZING'
                  AND analysis_attempt_token = :attempt_token
                RETURNING id::text
                """
            ),
            {
                "analysis_id": str(analysis.id),
                "attempt_token": str(attempt_token),
                "detector_version": detector_version,
                "ranker_version": ranker_version,
            },
        ).scalar_one_or_none()
        if updated is None:
            raise MediaAnalysisOwnershipLost("scene analysis ownership changed before commit")

    def build_result(self, session: Session, analysis_id: UUID) -> MediaAnalysisResult:
        analysis = session.execute(
            text("SELECT * FROM media_analysis WHERE id = :analysis_id"),
            {"analysis_id": str(analysis_id)},
        ).mappings().one_or_none()
        if analysis is None:
            raise RuntimeError("media analysis result was not found")
        state = SceneAnalysisState(_str(analysis["state"]))
        if state is not SceneAnalysisState.READY:
            return MediaAnalysisResult(
                state=state,
                failure_code=_optional_str(analysis["failure_code"]),
                analysis_id=str(analysis_id),
            )

        scene_count = int(
            session.execute(
                text("SELECT count(*) FROM media_scene WHERE analysis_id = :analysis_id"),
                {"analysis_id": str(analysis_id)},
            ).scalar_one()
        )
        top_scene = session.execute(
            text(
                """
                SELECT start_ms, end_ms
                FROM media_scene
                WHERE analysis_id = :analysis_id
                ORDER BY rank_score DESC, ordinal ASC
                LIMIT 1
                """
            ),
            {"analysis_id": str(analysis_id)},
        ).mappings().one_or_none()
        plan = session.execute(
            text(
                """
                SELECT destination, decision, policy_version, render_strategy,
                       expected_duration_ms, requires_sensitive_label
                FROM variant_plan
                WHERE analysis_id = :analysis_id
                ORDER BY destination
                LIMIT 1
                """
            ),
            {"analysis_id": str(analysis_id)},
        ).mappings().one_or_none()
        return MediaAnalysisResult(
            state=state,
            analysis_id=str(analysis_id),
            scene_count=scene_count,
            top_scene_start_ms=int(top_scene["start_ms"]) if top_scene is not None else None,
            top_scene_end_ms=int(top_scene["end_ms"]) if top_scene is not None else None,
            destination=_optional_str(plan["destination"]) if plan is not None else None,
            policy_decision=(
                PolicyDecision(_str(plan["decision"])) if plan is not None else None
            ),
            policy_version=_optional_str(plan["policy_version"]) if plan is not None else None,
            render_strategy=(
                RenderStrategy(_str(plan["render_strategy"]))
                if plan is not None and plan["render_strategy"] is not None
                else None
            ),
            planned_duration_ms=(
                int(plan["expected_duration_ms"])
                if plan is not None and plan["expected_duration_ms"] is not None
                else None
            ),
            requires_sensitive_label=(
                bool(plan["requires_sensitive_label"]) if plan is not None else False
            ),
        )


def _analysis_from_row(row: Mapping[str, object]) -> MediaAnalysis:
    return MediaAnalysis(
        id=UUID(_str(row["id"])),
        tenant_id=UUID(_str(row["tenant_id"])),
        asset_id=UUID(_str(row["asset_id"])),
        preparation_id=UUID(_str(row["preparation_id"])),
        operation_key=_str(row["operation_key"]),
        state=SceneAnalysisState(_str(row["state"])),
        analysis_attempt_token=_optional_uuid(row["analysis_attempt_token"]),
        detector_version=_optional_str(row["detector_version"]),
        ranker_version=_optional_str(row["ranker_version"]),
        failure_code=_optional_str(row["failure_code"]),
    )


def _str(value: object) -> str:
    if value is None:
        raise TypeError("expected non-null database value")
    return str(value)


def _optional_str(value: object) -> str | None:
    return None if value is None else str(value)


def _optional_uuid(value: object) -> UUID | None:
    return None if value is None else UUID(str(value))
