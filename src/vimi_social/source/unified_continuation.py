from vimi_social.domain.source import CandidateContent
from vimi_social.source.curator import CandidateCurator

_MIN_VIDEO_DURATION_MS = 60_000


class UnifiedContinuationCandidateCurator(CandidateCurator):
    """Continuation curator that rejects only known sub-minute videos.

    Distinct posts are intentionally not text-deduplicated. Exact provider IDs are
    already excluded by ScoutContinuationActivities against the persisted pool.
    """

    def rank(
        self,
        candidates: tuple[CandidateContent, ...],
        *,
        query_variants: tuple[str, ...],
        preferred_languages: tuple[str, ...],
        limit: int,
        semantic_scores: tuple[float, ...] | None = None,
        visual_scores: tuple[float | None, ...] | None = None,
        preview_ocr_texts: tuple[str | None, ...] | None = None,
        preview_ocr_semantic_scores: tuple[float | None, ...] | None = None,
        visual_weight: float = 0.15,
        preview_ocr_weight: float = 0.10,
        minimum_relevance: float = 0.0,
    ) -> tuple[CandidateContent, ...]:
        if limit < 1:
            return ()

        indices = tuple(
            index
            for index, candidate in enumerate(candidates)
            if not _known_short_video(candidate)
        )
        if not indices:
            return ()

        filtered = tuple(candidates[index] for index in indices)
        return super().rank(
            filtered,
            query_variants=query_variants,
            preferred_languages=preferred_languages,
            limit=min(limit, len(filtered)),
            semantic_scores=_align(semantic_scores, indices),
            visual_scores=_align(visual_scores, indices),
            preview_ocr_texts=_align(preview_ocr_texts, indices),
            preview_ocr_semantic_scores=_align(
                preview_ocr_semantic_scores,
                indices,
            ),
            visual_weight=visual_weight,
            preview_ocr_weight=preview_ocr_weight,
            minimum_relevance=minimum_relevance,
        )


def _known_short_video(candidate: CandidateContent) -> bool:
    return (
        candidate.media_type == "video"
        and candidate.duration_ms is not None
        and 0 < candidate.duration_ms < _MIN_VIDEO_DURATION_MS
    )


def _align[T](
    values: tuple[T, ...] | None,
    indices: tuple[int, ...],
) -> tuple[T, ...] | None:
    if values is None:
        return None
    return tuple(values[index] for index in indices)
