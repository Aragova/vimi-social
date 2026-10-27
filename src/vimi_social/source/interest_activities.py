from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy.orm import Session
from temporalio import activity

from vimi_social.db.tenant import tenant_transaction
from vimi_social.domain.identity import OperationKey
from vimi_social.domain.interest import XInterestSyncResult, XInterestSyncState
from vimi_social.domain.source import ScoutWorkflowInput, SourceTask
from vimi_social.publication.repository import PublicationRepository
from vimi_social.publication.x_adapter import (
    DestinationCredentialError,
    EnvironmentCredentialResolver,
)
from vimi_social.source.interest_profile import build_interest_profile
from vimi_social.source.interest_repository import UserInterestProfileRepository
from vimi_social.source.repository import SourceTaskRepository
from vimi_social.source.x_user_context import (
    XUserContextClient,
    XUserContextReauthRequired,
    XUserContextUnavailable,
)


class XInterestProfileActivities:
    """Refresh an explainable X taste profile without exposing OAuth secrets to Scout."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        *,
        source_repository: SourceTaskRepository | None = None,
        publication_repository: PublicationRepository | None = None,
        interest_repository: UserInterestProfileRepository | None = None,
        credential_resolver: EnvironmentCredentialResolver | None = None,
        client: XUserContextClient | None = None,
        profile_ttl: timedelta = timedelta(hours=6),
    ) -> None:
        self._session_factory = session_factory
        self._source_repository = source_repository or SourceTaskRepository()
        self._publication_repository = publication_repository or PublicationRepository()
        self._interest_repository = interest_repository or UserInterestProfileRepository()
        self._credential_resolver = credential_resolver or EnvironmentCredentialResolver()
        self._client = client or XUserContextClient()
        self._profile_ttl = max(timedelta(minutes=15), profile_ttl)

    @activity.defn(name="sync_x_user_interest_profile")
    async def sync_x_user_interest_profile(
        self,
        workflow_input: ScoutWorkflowInput,
    ) -> XInterestSyncResult:
        task = self._authorized_task(workflow_input)

        with self._session_factory() as session, tenant_transaction(session, task.tenant_id):
            accounts = self._publication_repository.active_accounts(session, platform="x")
            if not accounts:
                return XInterestSyncResult(XInterestSyncState.NO_ACCOUNT)
            if len(accounts) != 1:
                return XInterestSyncResult(XInterestSyncState.MULTIPLE_ACCOUNTS)
            account = accounts[0]
            cached = self._interest_repository.get(session, user_id=task.actor_user_id)
            if (
                cached is not None
                and cached.destination_account_id == account.id
                and _is_fresh(cached.generated_at, self._profile_ttl)
            ):
                return XInterestSyncResult(
                    XInterestSyncState.CACHED,
                    sample_size=cached.sample_size,
                )
            credential_ref = account.credential_ref

        try:
            access_token = self._credential_resolver.resolve(credential_ref)
        except DestinationCredentialError:
            return XInterestSyncResult(XInterestSyncState.UNAVAILABLE)

        try:
            snapshot = await self._client.fetch_snapshot(access_token)
        except XUserContextReauthRequired:
            return XInterestSyncResult(XInterestSyncState.REAUTH_REQUIRED)
        except XUserContextUnavailable:
            return XInterestSyncResult(XInterestSyncState.UNAVAILABLE)

        draft = build_interest_profile(snapshot)
        if draft.sample_size == 0:
            return XInterestSyncResult(
                XInterestSyncState.UNAVAILABLE,
                unavailable_sources=snapshot.unavailable_sources,
            )

        with self._session_factory() as session, tenant_transaction(session, task.tenant_id):
            profile = self._interest_repository.upsert(
                session,
                tenant_id=task.tenant_id,
                user_id=task.actor_user_id,
                destination_account_id=account.id,
                external_account_id=snapshot.user_id,
                draft=draft,
            )
        return XInterestSyncResult(
            XInterestSyncState.SYNCED,
            sample_size=profile.sample_size,
            unavailable_sources=snapshot.unavailable_sources,
        )

    def _authorized_task(self, workflow_input: ScoutWorkflowInput) -> SourceTask:
        operation_key = OperationKey(workflow_input.operation_key)
        try:
            execution_token = UUID(workflow_input.execution_token)
        except ValueError:
            raise RuntimeError("invalid source task execution token") from None

        with self._session_factory() as session, session.begin():
            tenant_id = self._source_repository.resolve_tenant(
                session,
                operation_key=operation_key,
                execution_token=execution_token,
            )
        with self._session_factory() as session, tenant_transaction(session, tenant_id):
            task = self._source_repository.get_by_operation_key(session, operation_key)
            if task is None or task.execution_token != execution_token:
                raise RuntimeError("source task authority binding mismatch")
            return task

    async def aclose(self) -> None:
        await self._client.aclose()


def _is_fresh(generated_at: datetime, ttl: timedelta) -> bool:
    value = generated_at
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - value <= ttl
