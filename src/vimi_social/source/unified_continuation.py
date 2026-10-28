from dataclasses import replace

from vimi_social.domain.source import CandidateContent
from vimi_social.source.curator import CandidateCurator
from vimi_social.source.unified_ranking import (
    distinct_query_token_count,
    known_short,
    lexical_relevance,
    metadata_float,
    passes_query_gate,
    score_candidate,
)


class UnifiedContinuationCandidateCurator(CandidateCurator):
    """Continuation ranking with the same relevance gate as initial unified Scout.

    Known sub-minute videos are rejected. Distinct posts are intentionally not
    text-deduplicated; exact provider IDs are already excluded against persisted rows.
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
        del preferred_languages, preview_ocr_texts
        if limit < 1:
            return ()

        query_token_count = distinct_query_token_count(query_variants)
        scored: list[tuple[float, float, float, int, CandidateContent]] = []
        for index, candidate in enumerate(candidates):
            if known_short(candidate):
                continue

            semantic_raw = semantic_scores[index] if semantic_scores is not None else None
            lexical, lexical_matches = lexical_relevance(candidate, query_variants)
            if not passes_query_gate(
                candidate,
                semantic_raw=semantic_raw,
                lexical=lexical,
                lexical_matches=lexical_matches,
                query_token_count=query_token_count,
                minimum_relevance=minimum_relevance,
            ):
                continue

            visual = visual_scores[index] if visual_scores is not None else None
            ocr = (
                preview_ocr_semantic_scores[index]
                if preview_ocr_semantic_scores is not None
                else None
            )
            final_score, updated = score_candidate(
                candidate,
                semantic_raw=semantic_raw,
                lexical=lexical,
                visual_relevance=visual,
                ocr_relevance=ocr,
                visual_weight=visual_weight,
                ocr_weight=preview_ocr_weight,
            )
            metadata = updated.connector_metadata
            scored.append(
                (
                    final_score,
                    metadata_float(metadata, "curator_relevance_score", 0.0),
                    metadata_float(metadata, "curator_quality_score", 0.0),
                    -index,
                    updated,
                )
            )

        scored.sort(key=lambda item: item[:4], reverse=True)
        result: list[CandidateContent] = []
        for rank, item in enumerate(scored[:limit], start=1):
            candidate = item[4]
            metadata = dict(candidate.connector_metadata)
            metadata["curator_rank"] = rank
            metadata["scout_engine"] = "unified_v4"
            result.append(replace(candidate, connector_metadata=metadata))
        return tuple(result)
