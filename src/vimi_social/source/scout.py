from vimi_social.source.connectors import SourceConnectorRegistry
from vimi_social.source.models import CandidateContent, SourceSearchRequest, SourceTask
from vimi_social.source.repository import SourceCandidateRepository


class ScoutService:
    def __init__(
        self,
        registry: SourceConnectorRegistry,
        candidates: SourceCandidateRepository,
    ) -> None:
        self._registry = registry
        self._candidates = candidates

    async def discover(
        self,
        task: SourceTask,
        request: SourceSearchRequest,
    ) -> tuple[CandidateContent, ...]:
        connector = self._registry.get(request.source)
        found = await connector.search(request)
        self._candidates.save_all(task, found)
        return found

    async def aclose(self) -> None:
        await self._registry.aclose()
