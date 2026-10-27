from dataclasses import replace

from vimi_social.domain.source import CandidateContent

_PREVIEW_GUARANTEED_HEAD = 10
_PREVIEW_UNCERTAINTY_MARGIN = 0.12


def select_preview_evidence_candidates(
    candidates: tuple[CandidateContent, ...],
    *,
    limit: int,
    guaranteed_head: int = _PREVIEW_GUARANTEED_HEAD,
    uncertainty_margin: float = _PREVIEW_UNCERTAINTY_MARGIN,
) -> tuple[CandidateContent, ...]:
    """Select preview candidates while protecting the visible head of the ranking.

    The first Telegram page is always eligible for preview evidence. Candidates below
    that head are routed to SigLIP/OCR only when their score-based relevance is close
    to the precision gate. Missing gate metadata is treated as uncertainty so a
    metadata regression fails toward more evidence rather than silently less.
    """

    cap = max(0, limit)
    if cap == 0 or not candidates:
        return ()

    head_size = min(max(0, guaranteed_head), len(candidates), cap)
    bounded_margin = max(0.0, min(1.0, uncertainty_margin))
    selected: list[CandidateContent] = []

    for position, candidate in enumerate(candidates):
        reason: str | None = None
        gate_margin = _gate_margin(candidate)
        if position < head_size:
            reason = "ranking_head"
        elif gate_margin is None or gate_margin <= bounded_margin:
            reason = "text_uncertain"

        if reason is None:
            continue
        selected.append(_with_selection_metadata(candidate, reason, gate_margin))
        if len(selected) >= cap:
            break

    return tuple(selected)


def apply_preview_selection_metadata(
    candidates: tuple[CandidateContent, ...],
    selected: tuple[CandidateContent, ...],
) -> tuple[CandidateContent, ...]:
    """Persist preview routing provenance on the candidates sent to final ranking."""

    selected_metadata = {
        (candidate.source, candidate.source_id): candidate.connector_metadata
        for candidate in selected
    }
    result: list[CandidateContent] = []
    for candidate in candidates:
        key = (candidate.source, candidate.source_id)
        metadata = dict(candidate.connector_metadata)
        routing_metadata = selected_metadata.get(key)
        metadata["preview_evidence_selected"] = routing_metadata is not None
        if routing_metadata is not None:
            metadata["preview_evidence_reason"] = routing_metadata[
                "preview_evidence_reason"
            ]
            if "preview_evidence_gate_margin" in routing_metadata:
                metadata["preview_evidence_gate_margin"] = routing_metadata[
                    "preview_evidence_gate_margin"
                ]
        result.append(replace(candidate, connector_metadata=metadata))
    return tuple(result)


def _gate_margin(candidate: CandidateContent) -> float | None:
    gate = _metadata_float(candidate, "curator_text_gate_score")
    minimum = _metadata_float(candidate, "curator_minimum_text_relevance_score")
    if gate is None or minimum is None:
        return None
    return round(max(0.0, gate - minimum), 6)


def _metadata_float(candidate: CandidateContent, key: str) -> float | None:
    value = candidate.connector_metadata.get(key)
    if not isinstance(value, int | float) or isinstance(value, bool):
        return None
    return float(value)


def _with_selection_metadata(
    candidate: CandidateContent,
    reason: str,
    gate_margin: float | None,
) -> CandidateContent:
    metadata = dict(candidate.connector_metadata)
    metadata["preview_evidence_selected"] = True
    metadata["preview_evidence_reason"] = reason
    if gate_margin is not None:
        metadata["preview_evidence_gate_margin"] = gate_margin
    return replace(candidate, connector_metadata=metadata)
