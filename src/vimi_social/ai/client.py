from typing import cast

import httpx

from vimi_social.domain.source import CandidateContent
from vimi_social.source.semantic import SemanticRelevanceUnavailable


class LocalAiClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 20.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        normalized = base_url.strip().rstrip("/")
        if not normalized:
            raise ValueError("local AI base URL must not be empty")
        self._base_url = normalized
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_client = client is None

    async def translate_to_english(self, intent: str) -> str | None:
        prompt = " ".join(intent.split()).strip()
        if not prompt:
            return None
        try:
            response = await self._client.post(
                f"{self._base_url}/v1/translate",
                json={
                    "text": prompt,
                    "source_language": "ru",
                    "target_language": "en",
                },
            )
        except httpx.HTTPError:
            return None
        if response.status_code >= 400:
            return None
        try:
            payload_obj: object = response.json()
        except ValueError:
            return None
        if not isinstance(payload_obj, dict):
            return None
        payload = cast(dict[str, object], payload_obj)
        text = payload.get("text")
        if not isinstance(text, str):
            return None
        normalized = " ".join(text.split()).strip()
        return normalized or None

    async def score_candidates(
        self,
        query_variants: tuple[str, ...],
        candidates: tuple[CandidateContent, ...],
    ) -> tuple[float, ...]:
        if not candidates:
            return ()

        documents: list[str] = []
        active_indices: list[int] = []
        scores = [0.0] * len(candidates)
        for index, candidate in enumerate(candidates):
            document = _candidate_search_text(candidate)
            if not document:
                continue
            active_indices.append(index)
            documents.append(document)

        if not documents:
            return tuple(scores)

        try:
            response = await self._client.post(
                f"{self._base_url}/v1/semantic-score",
                json={
                    "query_variants": list(query_variants),
                    "documents": documents,
                },
            )
        except httpx.HTTPError as error:
            raise SemanticRelevanceUnavailable("local semantic AI transport failed") from error
        if response.status_code >= 400:
            raise SemanticRelevanceUnavailable(
                f"local semantic AI failed with HTTP {response.status_code}"
            )
        try:
            payload_obj: object = response.json()
        except ValueError as error:
            raise SemanticRelevanceUnavailable("local semantic AI returned invalid JSON") from error
        if not isinstance(payload_obj, dict):
            raise SemanticRelevanceUnavailable("local semantic AI returned invalid response shape")
        payload = cast(dict[str, object], payload_obj)
        raw_scores = payload.get("scores")
        if not isinstance(raw_scores, list):
            raise SemanticRelevanceUnavailable("local semantic AI omitted scores")
        values = cast(list[object], raw_scores)
        if len(values) != len(active_indices):
            raise SemanticRelevanceUnavailable("local semantic AI returned wrong score count")

        for index, raw_score in zip(active_indices, values, strict=True):
            if not isinstance(raw_score, int | float) or isinstance(raw_score, bool):
                raise SemanticRelevanceUnavailable("local semantic AI returned non-numeric score")
            scores[index] = max(-1.0, min(1.0, float(raw_score)))
        return tuple(scores)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def _candidate_search_text(candidate: CandidateContent) -> str:
    parts = [candidate.title or "", candidate.caption or "", " ".join(candidate.tags)]
    return " ".join(" ".join(parts).split()).strip()
