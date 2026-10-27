import re
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, replace

from vimi_social.domain.interest import UserInterestProfile, XInterestSnapshot
from vimi_social.domain.source import CandidateContent

_TOKEN = re.compile(r"[^\W_]+(?:[-'][^\W_]+)*", re.UNICODE)
_HASHTAG = re.compile(r"(?<!\w)#([^\s#]+)", re.UNICODE)
_URL = re.compile(r"https?://\S+", re.IGNORECASE)
_PROFILE_NOISE = {
    "all",
    "content",
    "follow",
    "here",
    "just",
    "like",
    "more",
    "newvideo",
    "only",
    "promo",
    "today",
    "video",
    "videos",
    "wait",
}
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
    "in", "is", "it", "of", "on", "or", "that", "the", "this", "to",
    "with", "you", "your", "\u0432", "\u0434\u043b\u044f", "\u0438", "\u0438\u0437",
    "\u0438\u043b\u0438", "\u043d\u0430", "\u043e", "\u043e\u0431", "\u043e\u0442",
    "\u043f\u043e", "\u043f\u0440\u043e", "\u0441", "\u0441\u043e", "\u0447\u0442\u043e",
    *_PROFILE_NOISE,
}
_MAX_TERMS = 160
_MAX_HASHTAGS = 96
_MAX_AUTHORS = 160
_SUMMARY_TERMS = 48
_SUMMARY_HASHTAGS = 16
_SEMANTIC_AFFINITY_WEIGHT = 0.50
_PERSONALIZED_RETRIEVAL_LIMIT = 4


@dataclass(frozen=True, slots=True)
class InterestProfileDraft:
    term_weights: dict[str, float]
    hashtag_weights: dict[str, float]
    author_weights: dict[str, float]
    source_stats: dict[str, int]
    sample_size: int


def build_interest_profile(snapshot: XInterestSnapshot) -> InterestProfileDraft:
    terms: defaultdict[str, float] = defaultdict(float)
    hashtags: defaultdict[str, float] = defaultdict(float)
    authors: defaultdict[str, float] = defaultdict(float)

    def add_text(text: str | None, weight: float) -> None:
        if not text:
            return
        normalized = _URL.sub(" ", text).casefold()
        for raw_hashtag in _HASHTAG.findall(normalized):
            hashtag = raw_hashtag.strip(".,:;!?()[]{}\"'").casefold()
            if hashtag and hashtag not in _PROFILE_NOISE:
                hashtags[hashtag] += weight
        for token in _TOKEN.findall(normalized):
            cleaned = token.casefold().strip("-'_")
            if len(cleaned) < 3 or cleaned in _STOPWORDS or cleaned.isdigit():
                continue
            terms[cleaned] += weight

    for user in snapshot.following:
        authors[user.id] += 1.0
        add_text(
            " ".join(
                part
                for part in (user.name, user.username, user.description)
                if part
            ),
            0.8,
        )

    for post in snapshot.liked_posts:
        if post.author_id:
            authors[post.author_id] += 2.5
        add_text(post.text, 2.5)

    for post in snapshot.bookmarked_posts:
        if post.author_id:
            authors[post.author_id] += 4.0
        add_text(post.text, 4.0)

    for item in snapshot.lists:
        add_text(f"{item.name} {item.description or ''}", 2.0)

    for post in snapshot.list_posts:
        if post.author_id:
            authors[post.author_id] += 1.5
        add_text(post.text, 1.5)

    source_stats = {
        "following": len(snapshot.following),
        "likes": len(snapshot.liked_posts),
        "bookmarks": len(snapshot.bookmarked_posts),
        "lists": len(snapshot.lists),
        "list_posts": len(snapshot.list_posts),
    }
    sample_size = sum(source_stats.values())
    return InterestProfileDraft(
        term_weights=_normalized_top(terms, _MAX_TERMS),
        hashtag_weights=_normalized_top(hashtags, _MAX_HASHTAGS),
        author_weights=_normalized_top(authors, _MAX_AUTHORS),
        source_stats=source_stats,
        sample_size=sample_size,
    )


def build_interest_summary(profile: UserInterestProfile) -> str | None:
    """Build a compact semantic query from persisted, privacy-minimized aggregates."""

    terms = _ranked_keys(profile.term_weights, _SUMMARY_TERMS)
    hashtags = _ranked_keys(profile.hashtag_weights, _SUMMARY_HASHTAGS)
    if not terms and not hashtags:
        return None

    parts = [*terms]
    parts.extend(f"#{tag}" for tag in hashtags if tag not in terms)
    if not parts:
        return None
    return "user interests: " + " ".join(parts)


def build_personalized_retrieval_terms(
    profile: UserInterestProfile | None,
    query_variants: tuple[str, ...],
    *,
    limit: int = _PERSONALIZED_RETRIEVAL_LIMIT,
) -> tuple[str, ...]:
    """Select profile terms lexically related to the full intent for one bounded X recall round."""

    if profile is None or limit < 1:
        return ()

    query_tokens = tuple(
        dict.fromkeys(
            token.casefold().strip("-'_")
            for variant in query_variants
            for token in _TOKEN.findall(variant)
            if len(token.strip("-'_")) >= 3
            and token.casefold().strip("-'_") not in _STOPWORDS
        )
    )
    if not query_tokens:
        return ()

    ranked: dict[str, tuple[float, float, int]] = {}
    for source_priority, values in (
        (1, profile.hashtag_weights),
        (0, profile.term_weights),
    ):
        for raw_key, raw_weight in values.items():
            key = raw_key.casefold().strip().strip("#").strip("-'_")
            if len(key) < 3 or key in _PROFILE_NOISE or key.isdigit():
                continue
            weight = max(0.0, min(1.0, float(raw_weight)))
            if weight <= 0:
                continue
            relatedness = max(
                (_lexical_relatedness(key, token) for token in query_tokens),
                default=0.0,
            )
            if relatedness <= 0:
                continue
            score = weight * relatedness
            current = ranked.get(key)
            candidate = (score, weight, source_priority)
            if current is None or candidate > current:
                ranked[key] = candidate

    ordered = sorted(
        ranked.items(),
        key=lambda item: (
            -item[1][0],
            -item[1][1],
            -item[1][2],
            item[0],
        ),
    )
    return tuple(key for key, _ in ordered[:limit])


def apply_interest_profile(
    candidate: CandidateContent,
    profile: UserInterestProfile | None,
    *,
    semantic_affinity: float | None = None,
) -> CandidateContent:
    if profile is None:
        return candidate

    author_score = 0.0
    if candidate.author:
        author_score = _mapping_score(profile.author_weights, candidate.author)

    text = " ".join(
        part
        for part in (
            candidate.title or "",
            candidate.caption or "",
            " ".join(candidate.tags),
        )
        if part
    ).casefold()
    hashtag_matches = tuple(
        dict.fromkeys(
            tag.strip(".,:;!?()[]{}\"'").casefold()
            for tag in _HASHTAG.findall(text)
            if tag.strip(".,:;!?()[]{}\"'")
        )
    )
    hashtag_values = sorted(
        (_mapping_score(profile.hashtag_weights, tag) for tag in hashtag_matches),
        reverse=True,
    )
    hashtag_score = hashtag_values[0] if hashtag_values else 0.0

    tokens = tuple(
        dict.fromkeys(
            token.casefold().strip("-'")
            for token in _TOKEN.findall(_URL.sub(" ", text))
            if len(token.strip("-'_")) >= 3
        )
    )
    term_matches = sorted(
        (
            (token, _mapping_score(profile.term_weights, token))
            for token in tokens
            if _mapping_score(profile.term_weights, token) > 0
        ),
        key=lambda item: item[1],
        reverse=True,
    )
    top_term_values = [score for _, score in term_matches[:5]]
    term_score = (
        sum(top_term_values) / len(top_term_values)
        if top_term_values
        else 0.0
    )

    lexical_affinity = min(
        1.0,
        (0.50 * author_score) + (0.30 * hashtag_score) + (0.20 * term_score),
    )
    semantic_score = _semantic_score(semantic_affinity)
    if semantic_affinity is None:
        affinity = round(lexical_affinity, 6)
    else:
        affinity = round(
            min(
                1.0,
                (_SEMANTIC_AFFINITY_WEIGHT * semantic_score)
                + ((1.0 - _SEMANTIC_AFFINITY_WEIGHT) * lexical_affinity),
            ),
            6,
        )

    reasons: list[str] = []
    if author_score > 0 and candidate.author:
        reasons.append(f"author:{candidate.author}")
    for hashtag in hashtag_matches:
        if _mapping_score(profile.hashtag_weights, hashtag) > 0:
            reasons.append(f"hashtag:{hashtag}")
            if len(reasons) >= 4:
                break
    for term, score in term_matches:
        if score <= 0 or len(reasons) >= 6:
            break
        reasons.append(f"term:{term}")
    if semantic_affinity is not None and semantic_score > 0 and len(reasons) < 6:
        reasons.append("semantic:e5")

    metadata = dict(candidate.connector_metadata)
    metadata["personal_affinity_score"] = affinity
    metadata["personal_affinity_lexical_score"] = round(lexical_affinity, 6)
    if semantic_affinity is not None:
        metadata["personal_affinity_semantic_score"] = round(semantic_score, 6)
    metadata["personal_affinity_reasons"] = reasons
    metadata["personal_affinity_profile_sample_size"] = profile.sample_size
    metadata["personal_affinity_profile_generated_at"] = profile.generated_at.isoformat()
    return replace(candidate, connector_metadata=metadata)


def _normalized_top(values: Mapping[str, float], limit: int) -> dict[str, float]:
    if not values:
        return {}
    highest = max(values.values())
    if highest <= 0:
        return {}
    ranked = sorted(values.items(), key=lambda item: (-item[1], item[0]))
    return {
        key: round(value / highest, 6)
        for key, value in ranked[:limit]
        if value > 0
    }


def _ranked_keys(values: Mapping[str, float], limit: int) -> tuple[str, ...]:
    ranked = sorted(
        (
            (key.strip(), float(value))
            for key, value in values.items()
            if key.strip()
            and key.casefold().strip("#") not in _PROFILE_NOISE
            and float(value) > 0
        ),
        key=lambda item: (-item[1], item[0]),
    )
    return tuple(key for key, _ in ranked[:limit])


def _lexical_relatedness(profile_term: str, query_token: str) -> float:
    if profile_term == query_token:
        return 1.0
    if query_token in profile_term or profile_term in query_token:
        return 0.9
    return 0.0


def _mapping_score(values: Mapping[str, float], key: str) -> float:
    raw = values.get(key)
    if isinstance(raw, int | float) and not isinstance(raw, bool):
        return max(0.0, min(1.0, float(raw)))
    return 0.0


def _semantic_score(value: float | None) -> float:
    if not isinstance(value, int | float) or isinstance(value, bool):
        return 0.0
    return max(0.0, min(1.0, float(value)))
