import math
import re
from collections.abc import Iterable

from vimi_social.domain.source import CandidateContent

_MIN_VIDEO_DURATION_MS = 60_000
_URL = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
_MENTION = re.compile(r"(?<!\w)@[\w_]+", re.UNICODE)
_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)


def filter_scout_candidates(
    candidates: Iterable[CandidateContent],
    *,
    existing: Iterable[CandidateContent] = (),
    minimum_video_duration_ms: int = _MIN_VIDEO_DURATION_MS,
) -> tuple[CandidateContent, ...]:
    """Drop short videos and conservative near-duplicates before expensive ranking.

    Unknown durations fail open because provider metadata can be incomplete. Known video
    durations below the configured minimum are rejected. Near-duplicate suppression is
    intentionally conservative and compares caption/title text after removing URLs and
    mentions. Existing persisted candidates are treated as immutable representatives so
    continuation pages cannot re-introduce the same promotional template.
    """

    minimum_duration = max(0, minimum_video_duration_ms)
    existing_candidates = tuple(existing)
    seen_ids = {(candidate.source, candidate.source_id) for candidate in existing_candidates}
    protected_texts = tuple(
        text for candidate in existing_candidates if (text := _canonical_text(candidate))
    )

    result: list[CandidateContent] = []
    result_texts: list[tuple[str, tuple[str, ...]]] = []

    for candidate in candidates:
        source_key = (candidate.source, candidate.source_id)
        if source_key in seen_ids:
            continue
        seen_ids.add(source_key)

        if _is_known_short_video(candidate, minimum_duration):
            continue

        canonical = _canonical_text(candidate)
        if canonical and any(_near_duplicate(canonical, known) for known in protected_texts):
            continue

        duplicate_index: int | None = None
        if canonical:
            for index, known in enumerate(result_texts):
                if _near_duplicate(canonical, known):
                    duplicate_index = index
                    break

        if duplicate_index is None:
            result.append(candidate)
            result_texts.append(canonical)
            continue

        if _representative_key(candidate) > _representative_key(result[duplicate_index]):
            result[duplicate_index] = candidate
            result_texts[duplicate_index] = canonical

    return tuple(result)


def _is_known_short_video(candidate: CandidateContent, minimum_duration_ms: int) -> bool:
    if candidate.media_type != "video":
        return False
    duration_ms = candidate.duration_ms
    return duration_ms is not None and 0 < duration_ms < minimum_duration_ms


def _canonical_text(candidate: CandidateContent) -> tuple[str, tuple[str, ...]]:
    raw = candidate.caption or candidate.title or ""
    if candidate.tags:
        raw = f"{raw} {' '.join(candidate.tags)}"
    normalized = _MENTION.sub(" ", _URL.sub(" ", raw)).casefold()
    tokens = tuple(token for token in _TOKEN.findall(normalized) if token)
    return (" ".join(tokens), tokens)


def _near_duplicate(
    left: tuple[str, tuple[str, ...]],
    right: tuple[str, tuple[str, ...]],
) -> bool:
    left_text, left_tokens = left
    right_text, right_tokens = right
    if not left_text or not right_text:
        return False
    if left_text == right_text:
        return True

    left_set = set(left_tokens)
    right_set = set(right_tokens)
    smaller = min(len(left_set), len(right_set))
    if smaller < 6:
        return False

    shared = len(left_set & right_set)
    required_shared = max(6, math.ceil(smaller * 0.88))
    if shared < required_shared:
        return False

    union = len(left_set | right_set)
    jaccard = shared / union if union else 0.0
    containment = shared / smaller
    return containment >= 0.88 and jaccard >= 0.70


def _representative_key(candidate: CandidateContent) -> tuple[int, int, int]:
    duration = candidate.duration_ms if candidate.duration_ms is not None else 0
    engagement = sum(max(0, value) for value in candidate.engagement.values())
    acquisition = candidate.connector_metadata.get("acquisition_url")
    has_acquisition = int(isinstance(acquisition, str) and bool(acquisition))
    return (duration, engagement, has_acquisition)
