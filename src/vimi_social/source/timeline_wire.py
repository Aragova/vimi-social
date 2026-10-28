from dataclasses import replace

from vimi_social.domain.source import CandidateContent

_TIMELINE_PUBLISHED_AT_KEY = "x_published_at_iso"


def to_temporal_safe_timeline_candidate(candidate: CandidateContent) -> CandidateContent:
    """Remove datetime values from timeline candidates crossing Temporal JSON.

    Temporal SDK versions allowed by the project do not all encode ``datetime``
    with the default JSON converter. Preserve the provider timestamp as an ISO
    string in connector metadata and keep the wire candidate JSON-safe.
    """

    published_at = candidate.published_at
    if published_at is None:
        return candidate
    metadata = dict(candidate.connector_metadata)
    metadata[_TIMELINE_PUBLISHED_AT_KEY] = published_at.isoformat()
    return replace(candidate, published_at=None, connector_metadata=metadata)
