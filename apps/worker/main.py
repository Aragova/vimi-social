import asyncio

from temporalio.client import Client
from temporalio.worker import Worker

from vimi_social.core.config import get_settings
from vimi_social.workflows.publication import PublicationWorkflow


async def run() -> None:
    settings = get_settings()
    client = await Client.connect(
        settings.temporal_target,
        namespace=settings.temporal_namespace,
    )
    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=[PublicationWorkflow],
    )
    await worker.run()


if __name__ == "__main__":
    asyncio.run(run())
