import base64
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol, cast

import httpx

from vimi_social.domain.analysis import RankedScene, SceneClassificationBasis
from vimi_social.domain.media import BaseAdultClassification
from vimi_social.media.process_runner import MediaToolRunner, ProcessLimits
from vimi_social.media.secure_ingest.errors import ContentValidationError, ProcessLimitError


@dataclass(frozen=True, slots=True)
class VisualModerationResult:
    sexual_score: float
    flagged: bool
    model: str


class VisualModerationProvider(Protocol):
    async def classify(self, image_path: Path) -> VisualModerationResult: ...

    async def aclose(self) -> None: ...


class OpenAIVisualModerationProvider:
    """Classify sampled video frames with the standalone OpenAI moderation API."""

    def __init__(
        self,
        api_key: str,
        *,
        model: str = "omni-moderation-latest",
        timeout_seconds: float = 20.0,
        max_image_bytes: int = 2 * 1024 * 1024,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        token = api_key.strip()
        if not token:
            raise ValueError("OpenAI API key must not be empty")
        if max_image_bytes <= 0:
            raise ValueError("max_image_bytes must be positive")
        self._api_key = token
        self._model = model
        self._max_image_bytes = max_image_bytes
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)

    async def classify(self, image_path: Path) -> VisualModerationResult:
        data = image_path.read_bytes()
        if not data or len(data) > self._max_image_bytes:
            raise ContentValidationError("sampled frame size is invalid for visual moderation")
        encoded = base64.b64encode(data).decode("ascii")
        payload: dict[str, object] = {
            "model": self._model,
            "input": [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
                }
            ],
        }
        try:
            response = await self._client.post(
                "https://api.openai.com/v1/moderations",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        except httpx.HTTPError as exc:
            raise ContentValidationError("visual moderation transport failed") from exc
        if response.status_code >= 500 or response.status_code == 429:
            raise ContentValidationError("visual moderation service unavailable")
        if response.status_code >= 300:
            raise ContentValidationError(
                f"visual moderation request rejected with HTTP {response.status_code}"
            )
        try:
            decoded = cast(object, response.json())
        except ValueError as exc:
            raise ContentValidationError("visual moderation returned invalid JSON") from exc
        return _decode_moderation(decoded, fallback_model=self._model)

    async def aclose(self) -> None:
        await self._client.aclose()


class VisualSceneClassifier:
    version = "visual-moderation-v1"

    def __init__(
        self,
        provider: VisualModerationProvider,
        *,
        max_scenes: int = 6,
        explicit_threshold: float = 0.65,
        sensitive_threshold: float = 0.15,
        runner: MediaToolRunner | None = None,
    ) -> None:
        if max_scenes <= 0:
            raise ValueError("max_scenes must be positive")
        if not 0 <= sensitive_threshold < explicit_threshold <= 1:
            raise ValueError("visual classification thresholds are invalid")
        self._provider = provider
        self._max_scenes = max_scenes
        self._explicit_threshold = explicit_threshold
        self._sensitive_threshold = sensitive_threshold
        self._runner = runner or MediaToolRunner(
            ProcessLimits(timeout_seconds=20.0, max_output_bytes=256 * 1024)
        )

    async def classify(
        self,
        media_path: Path,
        scenes: Sequence[RankedScene],
        *,
        scratch_dir: Path,
    ) -> tuple[RankedScene, ...]:
        if not scenes:
            return ()
        selected_ordinals = {
            scene.ordinal
            for scene in sorted(scenes, key=lambda item: (-item.rank_score, item.ordinal))[
                : self._max_scenes
            ]
        }
        updated: list[RankedScene] = []
        frames_dir = scratch_dir / "visual-frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        for scene in scenes:
            if scene.ordinal not in selected_ordinals:
                updated.append(scene)
                continue
            frame_path = frames_dir / f"scene-{scene.ordinal}.jpg"
            midpoint_ms = scene.start_ms + max(1, (scene.end_ms - scene.start_ms) // 2)
            await self._extract_frame(media_path, midpoint_ms, frame_path, scratch_dir)
            result = await self._provider.classify(frame_path)
            classification = classification_for_visual_score(
                result.sexual_score,
                explicit_threshold=self._explicit_threshold,
                sensitive_threshold=self._sensitive_threshold,
            )
            updated.append(
                replace(
                    scene,
                    adult_classification=classification,
                    explicitness_score=result.sexual_score,
                    classification_basis=SceneClassificationBasis.VISUAL_MODERATION,
                    signals=(
                        "visual_moderation_sampled_frame",
                        "visual_sexual_score_available",
                        "visual_age_not_verified",
                    ),
                    classifier_version=f"{self.version}:{result.model}",
                )
            )
        return tuple(updated)

    async def _extract_frame(
        self,
        media_path: Path,
        midpoint_ms: int,
        frame_path: Path,
        scratch_dir: Path,
    ) -> None:
        timestamp = f"{midpoint_ms / 1000:.3f}"
        result = await self._runner.run(
            (
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                timestamp,
                "-i",
                str(media_path),
                "-frames:v",
                "1",
                "-vf",
                "scale=512:-2:force_original_aspect_ratio=decrease",
                "-q:v",
                "3",
                "-y",
                str(frame_path),
            ),
            cwd=scratch_dir,
        )
        if result.returncode != 0 or not frame_path.is_file() or frame_path.stat().st_size == 0:
            raise ProcessLimitError("ffmpeg did not produce a visual-classification frame")

    async def aclose(self) -> None:
        await self._provider.aclose()


def classification_for_visual_score(
    score: float,
    *,
    explicit_threshold: float,
    sensitive_threshold: float,
) -> BaseAdultClassification:
    if score >= explicit_threshold:
        return BaseAdultClassification.ADULT_EXPLICIT
    if score >= sensitive_threshold:
        return BaseAdultClassification.POSSIBLY_SENSITIVE
    return BaseAdultClassification.NO_ADULT_SIGNAL_DETECTED


def _decode_moderation(decoded: object, *, fallback_model: str) -> VisualModerationResult:
    if not isinstance(decoded, dict):
        raise ContentValidationError("visual moderation response root is invalid")
    root = cast(Mapping[str, object], decoded)
    raw_results = root.get("results")
    if not isinstance(raw_results, list) or not raw_results or not isinstance(raw_results[0], dict):
        raise ContentValidationError("visual moderation result is missing")
    first = cast(Mapping[str, object], raw_results[0])
    raw_scores = first.get("category_scores")
    if not isinstance(raw_scores, dict):
        raise ContentValidationError("visual moderation category scores are missing")
    scores = cast(Mapping[str, object], raw_scores)
    score_raw = scores.get("sexual")
    if isinstance(score_raw, bool) or not isinstance(score_raw, (int, float)):
        raise ContentValidationError("visual moderation sexual score is invalid")
    score = float(score_raw)
    if not 0 <= score <= 1:
        raise ContentValidationError("visual moderation sexual score is out of range")
    flagged_raw = first.get("flagged")
    flagged = bool(flagged_raw) if isinstance(flagged_raw, bool) else False
    model_raw = root.get("model")
    model = str(model_raw) if isinstance(model_raw, str) and model_raw else fallback_model
    return VisualModerationResult(sexual_score=score, flagged=flagged, model=model)
