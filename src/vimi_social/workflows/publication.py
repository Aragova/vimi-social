from dataclasses import dataclass

from temporalio import workflow


@dataclass(frozen=True)
class PublicationWorkflowInput:
    operation_key: str
    target_id: str
    tenant_id: str


@workflow.defn
class PublicationWorkflow:
    @workflow.run
    async def run(self, request: PublicationWorkflowInput) -> str:
        # Real provider dispatch is deliberately not wired yet. It must go through
        # the Architecture 1.0 external-effect handoff/reconciliation boundary.
        return f"ready:{request.operation_key}"
