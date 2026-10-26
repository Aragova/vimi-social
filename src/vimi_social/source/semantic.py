from typing import Protocol

from vimi_social.domain.source import CandidateContent


class SemanticRelevanceUnavailable(RuntimeError):
    pass


class SemanticRelevanceScorer(Protocol):
    async def score_candidates(
        self,
        query_variants: tuple[str, ...],
        candidates: tuple[CandidateContent, ...],
    ) -> tuple[float, ...]: ...

    async def score_texts(
        self,
        query_variants: tuple[str, ...],
        texts: tuple[str | None, ...],
    ) -> tuple[float | None, ...]: ...
