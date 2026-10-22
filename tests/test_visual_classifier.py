from pathlib import Path

import httpx
import pytest

from vimi_social.domain.analysis import RankedScene, SceneClassificationBasis
from vimi_social.domain.media import BaseAdultClassification
from vimi_social.media.visual_classifier import (
    OpenAIVisualModerationProvider,
    _classification_for_score,
)


def test_visual_score_thresholds_are_conservative() -> None:
    assert (
        _classification_for_score(
            0.01,
            explicit_threshold=0.65,
            sensitive_threshold=0.15,
        )
        is BaseAdultClassification.NO_ADULT_SIGNAL_DETECTED
    )
    assert (
        _classification_for_score(
            0.20,
            explicit_threshold=0.65,
            sensitive_threshold=0.15,
        )
        is BaseAdultClassification.POSSIBLY_SENSITIVE
    )
    assert (
        _classification_for_score(
            0.80,
            explicit_threshold=0.65,
            sensitive_threshold=0.15,
        )
        is BaseAdultClassification.ADULT_EXPLICIT
    )


@pytest.mark.asyncio
async def test_openai_visual_moderation_reads_sexual_score_without_age_claim(
    tmp_path: Path,
) -> None:
    captured_authorization: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_authorization.append(request.headers.get("authorization", ""))
        return httpx.Response(
            200,
            json={
                "id": "modr-test",
                "model": "omni-moderation-latest",
                "results": [
                    {
                        "flagged": True,
                        "categories": {"sexual": True},
                        "category_scores": {"sexual": 0.82},
                    }
                ],
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAIVisualModerationProvider("test-secret", client=client)
    image = tmp_path / "frame.jpg"
    image.write_bytes(b"\xff\xd8\xff\xd9")

    result = await provider.classify(image)

    assert result.sexual_score == pytest.approx(0.82)
    assert result.flagged is True
    assert result.model == "omni-moderation-latest"
    assert captured_authorization == ["Bearer test-secret"]
    await provider.aclose()


def test_ranked_scene_supports_visual_evidence_without_implying_age() -> None:
    scene = RankedScene(
        ordinal=0,
        start_ms=0,
        end_ms=10_000,
        rank_score=0.9,
        adult_classification=BaseAdultClassification.POSSIBLY_SENSITIVE,
        explicitness_score=0.4,
        classification_basis=SceneClassificationBasis.VISUAL_MODERATION,
        signals=("visual_age_not_verified",),
        classifier_version="visual-moderation-v1:omni-moderation-latest",
    )

    assert scene.classification_basis is SceneClassificationBasis.VISUAL_MODERATION
    assert "visual_age_not_verified" in scene.signals
