import asyncio
from contextlib import suppress
from datetime import timedelta
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker
from temporalio.client import Client
from temporalio.worker import Worker

from vimi_social.core.config import get_settings
from vimi_social.db.base import build_engine
from vimi_social.publication.activities import PublicationActivities
from vimi_social.source.interest_activities import XInterestProfileActivities
from vimi_social.source.x_oauth_refresh import (
    XOAuthRefreshUnavailable,
    XOAuthTokenManager,
)
from vimi_social.source.x_user_context import (
    X_HOME_TIMELINE_SEED_LIMIT,
    XUserContextClient,
)


async def run() -> None:
    settings = get_settings()
    client = await Client.connect(
        settings.temporal_target,
        namespace=settings.temporal_namespace,
    )
    engine = build_engine()
    session_factory = sessionmaker[Session](
        bind=engine,
        expire_on_commit=False,
        autoflush=False,
    )
    oauth_token_manager = XOAuthTokenManager(
        access_token=settings.dest_x_primary_token,
        refresh_token=settings.dest_x_primary_refresh_token,
        client_id=settings.x_oauth_client_id,
        client_secret=settings.x_oauth_client_secret,
        state_path=Path(settings.x_oauth_state_path),
    )
    refresh_task: asyncio.Task[None] | None = None
    if oauth_token_manager.enabled:
        # Refresh once at worker start so publication and user-context reads share
        # a current token even after a long staging downtime or container restart.
        with suppress(XOAuthRefreshUnavailable):
            await oauth_token_manager.refresh_now()
        refresh_task = asyncio.create_task(
            oauth_token_manager.run_periodic(
                interval_seconds=settings.x_oauth_refresh_interval_seconds,
            )
        )

    publication_activities = PublicationActivities(
        session_factory,
        media_root=Path(settings.media_root),
    )
    timeline_seed_limit = min(
        X_HOME_TIMELINE_SEED_LIMIT,
        max(0, settings.scout_retrieval_budget - 10),
    )
    interest_activities = XInterestProfileActivities(
        session_factory,
        client=XUserContextClient(
            list_sample_limit=settings.x_interest_list_sample_limit,
        ),
        oauth_token_manager=oauth_token_manager,
        profile_ttl=timedelta(hours=max(1, settings.x_interest_profile_ttl_hours)),
        home_timeline_limit=timeline_seed_limit,
    )
    worker = Worker(
        client,
        task_queue=settings.destination_task_queue,
        activities=[
            publication_activities.publish_destination,
            publication_activities.reconcile_destination_publication,
            interest_activities.sync_x_user_interest_profile,
            interest_activities.fetch_x_home_timeline_seed,
        ],
    )
    try:
        await worker.run()
    finally:
        if refresh_task is not None:
            refresh_task.cancel()
            with suppress(asyncio.CancelledError):
                await refresh_task
        await interest_activities.aclose()
        await oauth_token_manager.aclose()
        await publication_activities.aclose()
        engine.dispose()


if __name__ == "__main__":
    asyncio.run(run())
