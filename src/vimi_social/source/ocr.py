from typing import Protocol

from vimi_social.domain.source import CandidateContent


class PreviewOcrUnavailable(RuntimeError):
    pass


class PreviewOcrExtractor(Protocol):
    async def extract_preview_texts(
        self,
        candidates: tuple[CandidateContent, ...],
    ) -> tuple[str | None, ...]: ...
