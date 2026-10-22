import re

from vimi_social.domain.media import BaseAdultClassification, BaseContentClassification
from vimi_social.domain.source import AdultClassification, CandidateContent

_CLASSIFIER_VERSION = "base-signals-v1"
_EXPLICIT_PATTERN = re.compile(
    r"(?:\b(?:porn|porno|nsfw|sex|sexual|nude|nudes|xxx)\b|"
    r"(?:порно|порнограф|нюд|обнаж|секс))",
    re.IGNORECASE,
)


class BasicContentClassifier:
    """Conservative metadata/text baseline, not a visual safety classifier."""

    def classify(self, candidate: CandidateContent) -> BaseContentClassification:
        text = " ".join(
            value for value in (candidate.title, candidate.caption, " ".join(candidate.tags)) if value
        )
        signals: list[str] = []

        if _EXPLICIT_PATTERN.search(text):
            signals.append("explicit_text_signal")
        if candidate.adult_classification is AdultClassification.POSSIBLY_SENSITIVE:
            signals.append("source_possibly_sensitive")
        if candidate.explicitness_score is not None and candidate.explicitness_score >= 0.8:
            signals.append("source_high_explicitness_score")

        if "explicit_text_signal" in signals or "source_high_explicitness_score" in signals:
            return BaseContentClassification(
                adult=BaseAdultClassification.ADULT_EXPLICIT,
                explicitness_score=max(candidate.explicitness_score or 0.0, 0.85),
                classifier_version=_CLASSIFIER_VERSION,
                signals=tuple(signals),
            )
        if signals:
            return BaseContentClassification(
                adult=BaseAdultClassification.POSSIBLY_SENSITIVE,
                explicitness_score=candidate.explicitness_score,
                classifier_version=_CLASSIFIER_VERSION,
                signals=tuple(signals),
            )
        return BaseContentClassification(
            adult=BaseAdultClassification.NO_ADULT_SIGNAL_DETECTED,
            explicitness_score=None,
            classifier_version=_CLASSIFIER_VERSION,
            signals=("metadata_text_only_no_adult_signal",),
        )
