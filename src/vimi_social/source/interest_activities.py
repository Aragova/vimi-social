from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.orm import Session
from temporalio import activity

from vimi_social.db.tenant import tenant_transaction
from vimi_social.domain.identity import OperationKey
from vimi_social.domain.interest import XInterestSyncResult, XInterestSyncState
from vimi_social.domain.source import ScoutWorkflowInput, SourceTask, XTimelineSeedResult
from vimi_social.publication.x_adapter import (
    DestinationCredentialError,
    EnvironmentCredentialResolver,
)
from vimi_social.source.interest_profile import build_interest_profile
from vimi_social.source.interest_repository import UserInterestProfileRepository
from vimi_social.source.repository import SourceTaskRepository
from vimi_social.source.timeline_wire import to_temporal_safe_timeline_candidate
from vimi_social.source.x_oauth_refresh import (
    XOAuthRefreshUnavailable,
    XOAuthTokenManager,
)
from vimi_social.source.x_user_context import (
    XUserContextClient,
    XUserContextReauthRequired,
    XUserContextScopeUnavailable,
    XUserContextUnavailable,
)


class XInterestProfileActivities:
    """Read X user context on the credential-owning destination worker."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        *,
        source_repository: SourceTaskRepository | None = None,
        interest_repository: UserInterestProfileRepository | None = None,
        credential_resolver: EnvironmentCredentialResolver | None = None,
        client: XUserContextClient | None = None,
        oauth_token_manager: XOAuthTokenManager | None = None,
        profile_ttl: timedelta = timedelta(hours=6),
        home_timeline_limit: int = 50,
    ) -> None:
        self._session_factory = session_factory
        self._source_repository = source_repository or SourceTaskRepository()
        self._interest_repository = interest_repository or UserInterestProfileRepository()
        self._credential_resolver = credential_resolver or EnvironmentCredentialResolver()
        self._client = client or XUserContextClient()
        self._oauth_token_manager = oauth_token_manager
        self._profile_ttl = max(timedelta(minutes=15), profile_ttl)
        self._home_timeline_limit = max(0, min(100, home_timeline_limit))

    @activity.defn(name="sync_x_user_interest_profile")
    async def sync_x_user_interest_profile(
        self,
        workflow_input: ScoutWorkflowInput,
    ) -> XInterestSyncResult:
        task = self._authorized_task(workflow_input)

        with self._session_factory() as session, tenant_transaction(
            session,
            task.tenant_id,
        ):
            accounts = self._interest_repository.active_x_accounts_for_user(
                session,
                user_id=task.actor_user_id,
            )
            if not accounts:
                return XInterestSyncResult(XInterestSyncState.NO_ACCOUNT)
            if len(accounts) != 1:
                return XInterestSyncResult(XInterestSyncState.MULTIPLE_ACCOUNTS)
            account = accounts[0]
            cached = self._interest_repository.get(
                session,
                user_id=task.actor_user_id,
            )
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
            access_token = self._resolve_access_token(credential_ref)
        except DestinationCredentialError:
            return XInterestSyncResult(XInterestSyncState.UNAVAILABLE)

        try:
            snapshot = await self._client.fetch_snapshot(access_token)
        except XUserContextReauthRequired:
            refreshed = await self._refresh_access_token(credential_ref, access_token)
            if refreshed is None:
                return XInterestSyncResult(XInterestSyncState.REAUTH_REQUIRED)
            try:
                snapshot = await self._client.fetch_snapshot(refreshed)
            except XUserContextReauthRequired:
                return XInterestSyncResult(XInterestSyncState.REAUTH_REQUIRED)
            except XUserContextUnavailable:
                return XInterestSyncResult(XInterestSyncState.UNAVAILABLE)
        except XUserContextUnavailable:
            return XInterestSyncResult(XInterestSyncState.UNAVAILABLE)

        # A successful provider read is cacheable even when the account has no
        # usable taste signals yet. Persisting a neutral profile prevents every
        # subsequent Scout run from repeating the same paid user-context reads.
        # Provider failures above remain uncached, so an outage is never mistaken
        # for a genuinely empty interest graph.
        draft = build_interest_profile(snapshot)
        with self._session_factory() as session, tenant_transaction(
            session,
            task.tenant_id,
        ):
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

    @activity.defn(name="fetch_x_home_timeline_seed")
    async def fetch_x_home_timeline_seed(
        self,
        workflow_input: ScoutWorkflowInput,
    ) -> XTimelineSeedResult:
        """Fetch one bounded personalized timeline page without exposing the token."""

        if self._home_timeline_limit < 10:
            return XTimelineSeedResult(failure_code="DISABLED_BY_BUDGET")
        task = self._authorized_task(workflow_input)
        with self._session_factory() as session, tenant_transaction(
            session,
            task.tenant_id,
        ):
            accounts = self._interest_repository.active_x_accounts_for_user(
                session,
                user_id=task.actor_user_id,
            )
            if not accounts:
                return XTimelineSeedResult(failure_code="NO_ACCOUNT")
            if len(accounts) != 1:
                return XTimelineSeedResult(failure_code="MULTIPLE_ACCOUNTS")
            account = accounts[0]
            profile = self._interest_repository.get(
                session,
                user_id=task.actor_user_id,
            )
            if profile is None or profile.destination_account_id != account.id:
                return XTimelineSeedResult(failure_code="NO_PROFILE")
            credential_ref = account.credential_ref
            external_user_id = profile.external_account_id

        try:
            access_token = self._resolve_access_token(credential_ref)
        except DestinationCredentialError:
            return XTimelineSeedResult(failure_code="CREDENTIAL_UNAVAILABLE")

        try:
            candidates, posts_read = await self._client.fetch_home_timeline_candidates(
                access_token,
                external_user_id,
                max_results=self._home_timeline_limit,
            )
        except XUserContextReauthRequired:
            refreshed = await self._refresh_access_token(credential_ref, access_token)
            if refreshed is None:
                return XTimelineSeedResult(failure_code="REAUTH_REQUIRED")
            try:
                candidates, posts_read = await self._client.fetch_home_timeline_candidates(
                    refreshed,
                    external_user_id,
                    max_results=self._home_timeline_limit,
                )
            except XUserContextReauthRequired:
                return XTimelineSeedResult(failure_code="REAUTH_REQUIRED")
            except (XUserContextScopeUnavailable, XUserContextUnavailable):
                return XTimelineSeedResult(failure_code="TIMELINE_UNAVAILABLE")
        except (XUserContextScopeUnavailable, XUserContextUnavailable):
            return XTimelineSeedResult(failure_code="TIMELINE_UNAVAILABLE")

        return XTimelineSeedResult(
            candidates=tuple(
                to_temporal_safe_timeline_candidate(candidate) for candidate in candidates
            ),
            posts_read=posts_read,
        )

    def _resolve_access_token(self, credential_ref: str) -> str:
        manager = self._oauth_token_manager
        if manager is not None and manager.supports(credential_ref):
            managed = manager.current_access_token().strip()
            if managed:
                return managed
        return self._credential_resolver.resolve(credential_ref)

    async def _refresh_access_token(
        self,
        credential_ref: str,
        rejected_access_token: str,
    ) -> str | None:
        manager = self._oauth_token_manager
        if manager is None or not manager.supports(credential_ref):
            return None
        try:
            return await manager.refresh_after_rejection(rejected_access_token)
        except XOAuthRefreshUnavailable:
            return None

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
        value = value.replace(tzinfo=UTC)
    return datetime.now(UTC) - value <= ttl