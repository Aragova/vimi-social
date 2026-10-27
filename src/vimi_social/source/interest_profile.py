import re
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, replace

from vimi_social.domain.interest import UserInterestProfile, XInterestSnapshot
from vimi_social.domain.source import CandidateContent

_TOKEN = re.compile(r"[^\W_]+(?:[-'][^\W_]+)*", re.UNICODE)
_HASHTAG = re.compile(r"(?<!\w)#([^\s#]+)", re.UNICODE)
_URL = re.compile(r"https?://\S+", re.IGNORECASE)
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
    "in", "is", "it", "of", "on", "or", "that", "the", "this", "to",
    "with", "you", "your", "\u0432", "\u0434\u043b\u044f", "\u0438", "\u0438\u0437",
    "\u0438\u043b\u0438", "\u043d\u0430", "\u043e", "\u043e\u0431", "\u043e\u0442",
    "\u043f\u043e", "\u043f\u0440\u043e", "\u0441", "\u0441\u043e", "\u0447\u0442\u043e",
}
_MAX_TERMS = 160
_MAX_HASHTAGS = 96
_MAX_AUTHORS = 160


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
            if hashtag:
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


def apply_interest_profile(
    candidate: CandidateContent,
    profile: UserInterestProfile | None,
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

    affinity = round(
        min(
            1.0,
            (0.50 * author_score) + (0.30 * hashtag_score) + (0.20 * term_score),
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

    metadata = dict(candidate.connector_metadata)
    metadata["personal_affinity_score"] = affinity
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


def _mapping_score(values: Mapping[str, float], key: str) -> float:
    raw = values.get(key)
    if isinstance(raw, int | float) and not isinstance(raw, bool):
        return max(0.0, min(1.0, float(raw)))
    return 0.0
