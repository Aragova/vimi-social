from datetime import timedelta

from temporalio import workflow


@workflow.defn
class PublicationWorkflow:
    @workflow.run
    async def run(self, operation_key: str) -> str:
        """Durable orchestration shell keyed by the stable logical operation identity."""
        await workflow.sleep(timedelta(milliseconds=1))
        return operation_key
