from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from vimi_social.domain.identity import OperationKey
from vimi_social.domain.source import SourceTaskState


@dataclass(frozen=True, slots=True)
class ScoutAttemptClaim:
    claimed: bool
    state: SourceTaskState


class ScoutAttemptStore:
    """Database fence for paid Scout connector executions.

    Initial Scout owns the task while it is SCOUTING. Manual continuations keep
    the task COMPLETED but reuse ``scout_attempt_token`` as an execution fence so
    a worker crash after provider I/O cannot blindly repeat the same paid page.
    """

    def claim(
        self,
        session: Session,
        *,
        operation_key: OperationKey,
        attempt_token: UUID,
    ) -> ScoutAttemptClaim:
        claimed = session.execute(
            text(
                """
                UPDATE source_task
                SET state = 'SCOUTING',
                    failure_code = NULL,
                    scout_attempt_token = CAST(:attempt_token AS uuid),
                    updated_at = clock_timestamp()
                WHERE operation_key = :operation_key
                  AND state = 'QUEUED'
                RETURNING state
                """
            ),
            {
                "operation_key": operation_key.value,
                "attempt_token": str(attempt_token),
            },
        ).scalar_one_or_none()
        if isinstance(claimed, str):
            return ScoutAttemptClaim(claimed=True, state=SourceTaskState(claimed))

        state = self.current_state(session, operation_key=operation_key)
        return ScoutAttemptClaim(claimed=False, state=state)

    def lock_continuation_guard(
        self,
        session: Session,
        *,
        operation_key: OperationKey,
    ) -> None:
        """Serialize continuation state transitions for one source task."""
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:operation_key, 0))"),
            {"operation_key": operation_key.value},
        ).scalar_one()

    def claim_completed_continuation(
        self,
        session: Session,
        *,
        operation_key: OperationKey,
        attempt_token: UUID,
    ) -> bool:
        claimed = session.execute(
            text(
                """
                UPDATE source_task
                SET scout_attempt_token = CAST(:attempt_token AS uuid),
                    updated_at = clock_timestamp()
                WHERE operation_key = :operation_key
                  AND state = 'COMPLETED'
                  AND scout_attempt_token IS NULL
                RETURNING id::text
                """
            ),
            {
                "operation_key": operation_key.value,
                "attempt_token": str(attempt_token),
            },
        ).scalar_one_or_none()
        return claimed is not None

    def lock_owned_completed_continuation(
        self,
        session: Session,
        *,
        operation_key: OperationKey,
        attempt_token: UUID,
    ) -> bool:
        row = session.execute(
            text(
                """
                SELECT 1
                FROM source_task
                WHERE operation_key = :operation_key
                  AND state = 'COMPLETED'
                  AND scout_attempt_token = CAST(:attempt_token AS uuid)
                FOR UPDATE
                """
            ),
            {
                "operation_key": operation_key.value,
                "attempt_token": str(attempt_token),
            },
        ).scalar_one_or_none()
        return row == 1

    def clear_owned_completed_continuation(
        self,
        session: Session,
        *,
        operation_key: OperationKey,
        attempt_token: UUID,
    ) -> bool:
        cleared = session.execute(
            text(
                """
                UPDATE source_task
                SET scout_attempt_token = NULL,
                    updated_at = clock_timestamp()
                WHERE operation_key = :operation_key
                  AND state = 'COMPLETED'
                  AND scout_attempt_token = CAST(:attempt_token AS uuid)
                RETURNING id::text
                """
            ),
            {
                "operation_key": operation_key.value,
                "attempt_token": str(attempt_token),
            },
        ).scalar_one_or_none()
        return cleared is not None

    def clear_ambiguous_completed_continuation(
        self,
        session: Session,
        *,
        operation_key: OperationKey,
    ) -> bool:
        cleared = session.execute(
            text(
                """
                UPDATE source_task
                SET scout_attempt_token = NULL,
                    updated_at = clock_timestamp()
                WHERE operation_key = :operation_key
                  AND state = 'COMPLETED'
                  AND scout_attempt_token IS NOT NULL
                RETURNING id::text
                """
            ),
            {"operation_key": operation_key.value},
        ).scalar_one_or_none()
        return cleared is not None

    def fail_queued(
        self,
        session: Session,
        *,
        operation_key: OperationKey,
        failure_code: str,
    ) -> bool:
        updated = session.execute(
            text(
                """
                UPDATE source_task
                SET state = 'FAILED_SAFE',
                    failure_code = :failure_code,
                    scout_attempt_token = NULL,
                    updated_at = clock_timestamp()
                WHERE operation_key = :operation_key
                  AND state = 'QUEUED'
                RETURNING id::text
                """
            ),
            {
                "operation_key": operation_key.value,
                "failure_code": failure_code,
            },
        ).scalar_one_or_none()
        return updated is not None

    def mark_ambiguous_retry(
        self,
        session: Session,
        *,
        operation_key: OperationKey,
        retry_token: UUID,
    ) -> SourceTaskState:
        updated = session.execute(
            text(
                """
                UPDATE source_task
                SET state = 'UNKNOWN',
                    failure_code = 'SCOUT_ATTEMPT_AMBIGUOUS',
                    scout_attempt_token = NULL,
                    updated_at = clock_timestamp()
                WHERE operation_key = :operation_key
                  AND state = 'SCOUTING'
                  AND scout_attempt_token IS DISTINCT FROM CAST(:retry_token AS uuid)
                RETURNING state
                """
            ),
            {
                "operation_key": operation_key.value,
                "retry_token": str(retry_token),
            },
        ).scalar_one_or_none()
        if isinstance(updated, str):
            return SourceTaskState(updated)
        return self.current_state(session, operation_key=operation_key)

    def lock_owned_attempt(
        self,
        session: Session,
        *,
        operation_key: OperationKey,
        attempt_token: UUID,
    ) -> bool:
        row = session.execute(
            text(
                """
                SELECT 1
                FROM source_task
                WHERE operation_key = :operation_key
                  AND state = 'SCOUTING'
                  AND scout_attempt_token = CAST(:attempt_token AS uuid)
                FOR UPDATE
                """
            ),
            {
                "operation_key": operation_key.value,
                "attempt_token": str(attempt_token),
            },
        ).scalar_one_or_none()
        return row == 1

    def finish_owned_attempt(
        self,
        session: Session,
        *,
        operation_key: OperationKey,
        attempt_token: UUID,
        state: SourceTaskState,
        failure_code: str | None = None,
    ) -> bool:
        if state not in {
            SourceTaskState.COMPLETED,
            SourceTaskState.FAILED_SAFE,
            SourceTaskState.UNKNOWN,
        }:
            raise ValueError("Scout attempt can only finish in a terminal state")

        updated = session.execute(
            text(
                """
                UPDATE source_task
                SET state = :state,
                    failure_code = :failure_code,
                    scout_attempt_token = NULL,
                    updated_at = clock_timestamp()
                WHERE operation_key = :operation_key
                  AND state = 'SCOUTING'
                  AND scout_attempt_token = CAST(:attempt_token AS uuid)
                RETURNING id::text
                """
            ),
            {
                "operation_key": operation_key.value,
                "attempt_token": str(attempt_token),
                "state": state.value,
                "failure_code": failure_code,
            },
        ).scalar_one_or_none()
        return updated is not None

    def current_state(
        self,
        session: Session,
        *,
        operation_key: OperationKey,
    ) -> SourceTaskState:
        raw = session.execute(
            text(
                """
                SELECT state
                FROM source_task
                WHERE operation_key = :operation_key
                """
            ),
            {"operation_key": operation_key.value},
        ).scalar_one_or_none()
        if not isinstance(raw, str):
            raise RuntimeError("source task was not found in tenant context")
        return SourceTaskState(raw)
