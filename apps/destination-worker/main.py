import asyncio
from datetime import timedelta
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker
from temporalio.client import Client
from temporalio.worker import Worker

from vimi_social.core.config import get_settings
from vimi_social.db.base import build_engine
from vimi_social.publication.activities import PublicationActivities
from vimi_social.source.interest_activities import XInterestProfileActivities
from vimi_social.source.x_user_context import XUserContextClient


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
    publication_activities = PublicationActivities(
        session_factory,
        media_root=Path(settings.media_root),
    )
    interest_activities = XInterestProfileActivities(
        session_factory,
        client=XUserContextClient(
            list_sample_limit=settings.x_interest_list_sample_limit,
        ),
        profile_ttl=timedelta(hours=max(1, settings.x_interest_profile_ttl_hours)),
    )
    worker = Worker(
        client,
        task_queue=settings.destination_task_queue,
        activities=[
            publication_activities.publish_destination,
            publication_activities.reconcile_destination_publication,
            interest_activities.sync_x_user_interest_profile,
        ],
    )
    try:
        await worker.run()
    finally:
        await interest_activities.aclose()
        await publication_activities.aclose()
        engine.dispose()


if __name__ == "__main__":
    asyncio.run(run())
