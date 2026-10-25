from typing import Protocol

from vimi_social.domain.source import CandidateContent


class VisualRelevanceUnavailable(RuntimeError):
    pass


class VisualRelevanceScorer(Protocol):
    async def score_candidates(
        self,
        query_variants: tuple[str, ...],
        candidates: tuple[CandidateContent, ...],
    ) -> tuple[float | None, ...]: ...
