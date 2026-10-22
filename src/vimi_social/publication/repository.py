from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from vimi_social.domain.analysis import PolicyDecision
from vimi_social.domain.publication import (
    DestinationAccount,
    DestinationAccountState,
    PublicationOperation,
    PublicationPreviewResult,
    PublicationPreviewState,
    PublicationResult,
    PublicationState,
    ReconciliationKind,
    ReconciliationResult,
    VariantArtifactState,
)


@dataclass(frozen=True, slots=True)
class PublishClaim:
    state: PublicationState
    attempt_token: UUID | None
    owns_attempt: bool


class PublicationBindingConflict(RuntimeError):
    pass


class PublicationRepository:
    def active_accounts(
        self,
        session: Session,
        *,
        platform: str,
    ) -> tuple[DestinationAccount, ...]:
        rows = session.execute(
            text(
                """
                SELECT id, tenant_id, platform, external_account_id,
                       display_name, credential_ref, state
                FROM destination_account
                WHERE platform = :platform AND state = 'ACTIVE'
                ORDER BY created_at, id
                """
            ),
            {"platform": platform},
        ).mappings().all()
        return tuple(_account_from_row(cast(Mapping[str, object], row)) for row in rows)

    def upsert_account(
        self,
        session: Session,
        *,
        tenant_id: UUID,
        platform: str,
        external_account_id: str,
        display_name: str | None,
        credential_ref: str,
    ) -> DestinationAccount:
        row = session.execute(
            text(
                """
                INSERT INTO destination_account (
                    tenant_id, platform, external_account_id, display_name, credential_ref, state
                ) VALUES (
                    :tenant_id, :platform, :external_account_id, :display_name, :credential_ref,
                    'ACTIVE'
                )
                ON CONFLICT (tenant_id, platform, external_account_id)
                DO UPDATE SET display_name = EXCLUDED.display_name,
                              credential_ref = EXCLUDED.credential_ref,
                              state = 'ACTIVE',
                              updated_at = clock_timestamp()
                RETURNING id, tenant_id, platform, external_account_id,
                          display_name, credential_ref, state
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "platform": platform,
                "external_account_id": external_account_id,
                "display_name": display_name,
                "credential_ref": credential_ref,
            },
        ).mappings().one()
        return _account_from_row(cast(Mapping[str, object], row))

    def prepare_preview(
        self,
        session: Session,
        *,
        artifact_id: UUID,
        destination: str,
    ) -> PublicationPreviewResult:
        row = session.execute(
            text(
                """
                SELECT artifact.id AS artifact_id,
                       artifact.tenant_id,
                       artifact.state AS artifact_state,
                       plan.decision,
                       plan.destination
                FROM variant_artifact AS artifact
                JOIN variant_plan AS plan
                  ON plan.id = artifact.plan_id
                 AND plan.tenant_id = artifact.tenant_id
                WHERE artifact.id = :artifact_id
                """
            ),
            {"artifact_id": str(artifact_id)},
        ).mappings().one_or_none()
        if row is None:
            return PublicationPreviewResult(
                state=PublicationPreviewState.RENDER_FAILED,
                artifact_id=str(artifact_id),
                reason_code="VARIANT_ARTIFACT_NOT_FOUND",
            )
        mapped = cast(Mapping[str, object], row)
        if str(mapped["artifact_state"]) != VariantArtifactState.READY.value:
            return PublicationPreviewResult(
                state=PublicationPreviewState.RENDER_FAILED,
                artifact_id=str(artifact_id),
                reason_code="VARIANT_ARTIFACT_NOT_READY",
            )
        if str(mapped["destination"]) != destination:
            raise PublicationBindingConflict("variant artifact belongs to another destination")

        decision = PolicyDecision(str(mapped["decision"]))
        if decision is PolicyDecision.BLOCKED:
            return PublicationPreviewResult(
                state=PublicationPreviewState.BLOCKED,
                artifact_id=str(artifact_id),
                destination=destination,
                reason_code="DESTINATION_POLICY_BLOCKED",
            )
        if decision is PolicyDecision.MANUAL_REVIEW_REQUIRED:
            return PublicationPreviewResult(
                state=PublicationPreviewState.REVIEW_REQUIRED,
                artifact_id=str(artifact_id),
                destination=destination,
                reason_code="DESTINATION_POLICY_REVIEW_REQUIRED",
            )

        accounts = self.active_accounts(session, platform=destination)
        if not accounts:
            return PublicationPreviewResult(
                state=PublicationPreviewState.NO_DESTINATION,
                artifact_id=str(artifact_id),
                destination=destination,
                reason_code="NO_ACTIVE_DESTINATION_ACCOUNT",
            )
        if len(accounts) != 1:
            return PublicationPreviewResult(
                state=PublicationPreviewState.ACCOUNT_SELECTION_REQUIRED,
                artifact_id=str(artifact_id),
                destination=destination,
                reason_code="MULTIPLE_DESTINATION_ACCOUNTS",
            )
        account = accounts[0]
        operation_key = f"publish:{artifact_id}:{account.id}"
        target_id = f"{destination}:{account.external_account_id}"
        session.execute(
            text(
                """
                INSERT INTO publication_operation (
                    tenant_id, operation_key, target_id, state,
                    artifact_id, destination_account_id, caption
                )
                SELECT artifact.tenant_id,
                       :operation_key,
                       :target_id,
                       'AWAITING_APPROVAL',
                       artifact.id,
                       :destination_account_id,
                       ''
                FROM variant_artifact AS artifact
                WHERE artifact.id = :artifact_id
                  AND artifact.state = 'READY'
                ON CONFLICT (operation_key) DO NOTHING
                """
            ),
            {
                "operation_key": operation_key,
                "target_id": target_id,
                "destination_account_id": str(account.id),
                "artifact_id": str(artifact_id),
            },
        )
        operation = self.get_by_operation_key(session, operation_key)
        if operation is None:
            raise RuntimeError("publication operation persistence failed")
        if operation.artifact_id != artifact_id or operation.destination_account_id != account.id:
            raise PublicationBindingConflict("operation key is bound to different publication data")
        return PublicationPreviewResult(
            state=PublicationPreviewState.AWAITING_APPROVAL,
            artifact_id=str(artifact_id),
            publication_id=str(operation.id),
            destination=destination,
            destination_name=account.display_name or account.external_account_id,
        )

    def get_by_id(self, session: Session, publication_id: UUID) -> PublicationOperation | None:
        row = session.execute(
            text(
                """
                SELECT id, tenant_id, artifact_id, destination_account_id,
                       operation_key, state, publish_attempt_token, caption,
                       remote_media_id, remote_post_id, failure_code
                FROM publication_operation
                WHERE id = :publication_id
                  AND artifact_id IS NOT NULL
                  AND destination_account_id IS NOT NULL
                """
            ),
            {"publication_id": str(publication_id)},
        ).mappings().one_or_none()
        return _operation_from_row(cast(Mapping[str, object], row)) if row is not None else None

    def get_by_operation_key(
        self,
        session: Session,
        operation_key: str,
    ) -> PublicationOperation | None:
        row = session.execute(
            text(
                """
                SELECT id, tenant_id, artifact_id, destination_account_id,
                       operation_key, state, publish_attempt_token, caption,
                       remote_media_id, remote_post_id, failure_code
                FROM publication_operation
                WHERE operation_key = :operation_key
                  AND artifact_id IS NOT NULL
                  AND destination_account_id IS NOT NULL
                """
            ),
            {"operation_key": operation_key},
        ).mappings().one_or_none()
        return _operation_from_row(cast(Mapping[str, object], row)) if row is not None else None

    def approve(
        self,
        session: Session,
        *,
        publication_id: UUID,
        actor_user_id: UUID,
    ) -> PublicationOperation | None:
        updated = session.execute(
            text(
                """
                UPDATE publication_operation AS publication
                SET state = 'READY',
                    approved_by_user_id = :actor_user_id,
                    approved_at = COALESCE(approved_at, clock_timestamp()),
                    updated_at = clock_timestamp()
                FROM variant_artifact AS artifact,
                     variant_plan AS plan,
                     media_analysis AS analysis,
                     media_asset AS asset,
                     source_task_candidate AS candidate,
                     source_task AS task
                WHERE publication.id = :publication_id
                  AND publication.state IN ('AWAITING_APPROVAL', 'READY')
                  AND artifact.id = publication.artifact_id
                  AND artifact.tenant_id = publication.tenant_id
                  AND plan.id = artifact.plan_id
                  AND plan.tenant_id = artifact.tenant_id
                  AND plan.decision IN ('DIRECT_ALLOWED', 'ADAPTATION_REQUIRED')
                  AND analysis.id = plan.analysis_id
                  AND analysis.tenant_id = plan.tenant_id
                  AND asset.id = analysis.asset_id
                  AND asset.tenant_id = analysis.tenant_id
                  AND candidate.id = asset.candidate_id
                  AND candidate.tenant_id = asset.tenant_id
                  AND task.id = candidate.source_task_id
                  AND task.tenant_id = candidate.tenant_id
                  AND task.actor_user_id = :actor_user_id
                RETURNING publication.id::text
                """
            ),
            {"publication_id": str(publication_id), "actor_user_id": str(actor_user_id)},
        ).scalar_one_or_none()
        if updated is None:
            return None
        return self.get_by_id(session, publication_id)

    def claim_dispatch(
        self,
        session: Session,
        *,
        publication_id: UUID,
        attempt_token: UUID,
    ) -> PublishClaim:
        state = session.execute(
            text(
                """
                UPDATE publication_operation
                SET state = 'DISPATCHING',
                    publish_attempt_token = :attempt_token,
                    updated_at = clock_timestamp()
                WHERE id = :publication_id AND state = 'READY'
                RETURNING state
                """
            ),
            {"publication_id": str(publication_id), "attempt_token": str(attempt_token)},
        ).scalar_one_or_none()
        if state is not None:
            return PublishClaim(PublicationState(str(state)), attempt_token, True)
        row = session.execute(
            text(
                """
                SELECT state, publish_attempt_token
                FROM publication_operation WHERE id = :publication_id
                """
            ),
            {"publication_id": str(publication_id)},
        ).mappings().one_or_none()
        if row is None:
            raise RuntimeError("publication operation was not found in tenant context")
        existing_state = PublicationState(str(row["state"]))
        existing_token = _optional_uuid(row["publish_attempt_token"])
        return PublishClaim(
            state=existing_state,
            attempt_token=existing_token,
            owns_attempt=(
                existing_state is PublicationState.DISPATCHING
                and existing_token == attempt_token
            ),
        )

    def fail_ambiguous_retry(
        self,
        session: Session,
        *,
        publication_id: UUID,
        observed_attempt_token: UUID,
    ) -> PublicationState:
        state = session.execute(
            text(
                """
                UPDATE publication_operation
                SET state = 'UNKNOWN',
                    publish_attempt_token = NULL,
                    failure_code = 'PUBLICATION_ATTEMPT_AMBIGUOUS',
                    updated_at = clock_timestamp()
                WHERE id = :publication_id
                  AND state = 'DISPATCHING'
                  AND publish_attempt_token = :attempt_token
                RETURNING state
                """
            ),
            {"publication_id": str(publication_id), "attempt_token": str(observed_attempt_token)},
        ).scalar_one_or_none()
        if state is not None:
            return PublicationState(str(state))
        current = session.execute(
            text("SELECT state FROM publication_operation WHERE id = :publication_id"),
            {"publication_id": str(publication_id)},
        ).scalar_one()
        return PublicationState(str(current))

    def checkpoint_media(
        self,
        session: Session,
        *,
        publication_id: UUID,
        attempt_token: UUID,
        remote_media_id: str,
    ) -> bool:
        return (
            session.execute(
                text(
                    """
                    UPDATE publication_operation
                    SET remote_media_id = :remote_media_id,
                        updated_at = clock_timestamp()
                    WHERE id = :publication_id
                      AND state = 'DISPATCHING'
                      AND publish_attempt_token = :attempt_token
                    RETURNING id::text
                    """
                ),
                {
                    "publication_id": str(publication_id),
                    "attempt_token": str(attempt_token),
                    "remote_media_id": remote_media_id,
                },
            ).scalar_one_or_none()
            is not None
        )

    def finish_mutation(
        self,
        session: Session,
        *,
        publication_id: UUID,
        attempt_token: UUID,
        state: PublicationState,
        remote_media_id: str | None = None,
        remote_post_id: str | None = None,
        failure_code: str | None = None,
    ) -> PublicationResult:
        if state not in {
            PublicationState.CONFIRMED,
            PublicationState.PROVIDER_ACCEPTED,
            PublicationState.UNKNOWN,
            PublicationState.FAILED_SAFE,
            PublicationState.FAILED_PERMANENT,
        }:
            raise ValueError("invalid publication mutation terminal state")
        updated = session.execute(
            text(
                """
                UPDATE publication_operation
                SET state = :state,
                    publish_attempt_token = NULL,
                    remote_media_id = COALESCE(:remote_media_id, remote_media_id),
                    remote_post_id = COALESCE(:remote_post_id, remote_post_id),
                    failure_code = :failure_code,
                    updated_at = clock_timestamp()
                WHERE id = :publication_id
                  AND state = 'DISPATCHING'
                  AND publish_attempt_token = :attempt_token
                RETURNING id::text
                """
            ),
            {
                "publication_id": str(publication_id),
                "attempt_token": str(attempt_token),
                "state": state.value,
                "remote_media_id": remote_media_id,
                "remote_post_id": remote_post_id,
                "failure_code": failure_code,
            },
        ).scalar_one_or_none()
        if updated is None:
            current = self.get_by_id(session, publication_id)
            if current is None:
                raise RuntimeError("publication disappeared during mutation finalization")
            return _publication_result(current)
        current = self.get_by_id(session, publication_id)
        if current is None:
            raise RuntimeError("publication disappeared after mutation finalization")
        return _publication_result(current)

    def apply_reconciliation(
        self,
        session: Session,
        *,
        publication_id: UUID,
        result: ReconciliationResult,
    ) -> PublicationResult:
        current = self.get_by_id(session, publication_id)
        if current is None:
            raise RuntimeError("publication operation was not found")
        if current.state is PublicationState.CONFIRMED:
            return _publication_result(current)
        if current.state is not PublicationState.UNKNOWN:
            return _publication_result(current)

        if result.kind is ReconciliationKind.CONFIRMED:
            state = PublicationState.CONFIRMED
            failure_code = None
            remote_post_id = result.remote_post_id
        elif result.kind is ReconciliationKind.PROVED_ABSENT:
            state = PublicationState.FAILED_SAFE
            failure_code = "PROVIDER_PROVED_PUBLICATION_ABSENT"
            remote_post_id = None
        else:
            return _publication_result(current)

        session.execute(
            text(
                """
                UPDATE publication_operation
                SET state = :state,
                    remote_post_id = COALESCE(:remote_post_id, remote_post_id),
                    failure_code = :failure_code,
                    updated_at = clock_timestamp()
                WHERE id = :publication_id AND state = 'UNKNOWN'
                """
            ),
            {
                "publication_id": str(publication_id),
                "state": state.value,
                "remote_post_id": remote_post_id,
                "failure_code": failure_code,
            },
        )
        refreshed = self.get_by_id(session, publication_id)
        if refreshed is None:
            raise RuntimeError("publication disappeared after reconciliation")
        return _publication_result(refreshed)


def _account_from_row(row: Mapping[str, object]) -> DestinationAccount:
    return DestinationAccount(
        id=UUID(str(row["id"])),
        tenant_id=UUID(str(row["tenant_id"])),
        platform=str(row["platform"]),
        external_account_id=str(row["external_account_id"]),
        display_name=_optional_str(row["display_name"]),
        credential_ref=str(row["credential_ref"]),
        state=DestinationAccountState(str(row["state"])),
    )


def _operation_from_row(row: Mapping[str, object]) -> PublicationOperation:
    artifact_raw = row["artifact_id"]
    account_raw = row["destination_account_id"]
    if artifact_raw is None or account_raw is None:
        raise TypeError("new publication operation is missing destination binding")
    return PublicationOperation(
        id=UUID(str(row["id"])),
        tenant_id=UUID(str(row["tenant_id"])),
        artifact_id=UUID(str(artifact_raw)),
        destination_account_id=UUID(str(account_raw)),
        operation_key=str(row["operation_key"]),
        state=PublicationState(str(row["state"])),
        publish_attempt_token=_optional_uuid(row["publish_attempt_token"]),
        caption=str(row["caption"]),
        remote_media_id=_optional_str(row["remote_media_id"]),
        remote_post_id=_optional_str(row["remote_post_id"]),
        failure_code=_optional_str(row["failure_code"]),
    )


def _publication_result(operation: PublicationOperation) -> PublicationResult:
    return PublicationResult(
        state=operation.state,
        publication_id=str(operation.id),
        remote_post_id=operation.remote_post_id,
        failure_code=operation.failure_code,
    )


def _optional_uuid(value: object) -> UUID | None:
    return None if value is None else UUID(str(value))


def _optional_str(value: object) -> str | None:
    return None if value is None else str(value)
