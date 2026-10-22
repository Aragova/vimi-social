import math
import re
from collections.abc import Sequence
from itertools import pairwise
from pathlib import Path
from typing import Protocol

from vimi_social.domain.analysis import (
    RankedScene,
    SceneBoundary,
    SceneClassificationBasis,
)
from vimi_social.domain.media import BaseContentClassification
from vimi_social.media.process_runner import MediaToolRunner, ProcessResult
from vimi_social.media.secure_ingest.errors import ContentValidationError, ProcessLimitError

_SCENE_TIME = re.compile(rb"pts_time:([0-9]+(?:\.[0-9]+)?)")


class SceneToolRunner(Protocol):
    async def run(self, argv: Sequence[str], *, cwd: Path) -> ProcessResult: ...


class SceneDetector:
    version = "ffmpeg-scene-v1"

    def __init__(
        self,
        runner: SceneToolRunner | None = None,
        *,
        threshold: float = 0.35,
        min_scene_ms: int = 750,
        max_scenes: int = 200,
    ) -> None:
        if not math.isfinite(threshold) or not 0 < threshold < 1:
            raise ValueError("threshold must be between 0 and 1")
        if min_scene_ms <= 0:
            raise ValueError("min_scene_ms must be positive")
        if max_scenes <= 0:
            raise ValueError("max_scenes must be positive")
        self._runner = runner or MediaToolRunner()
        self._threshold = threshold
        self._min_scene_ms = min_scene_ms
        self._max_scenes = max_scenes

    async def detect(
        self,
        path: Path,
        *,
        duration_ms: int | None,
        scratch_dir: Path,
    ) -> tuple[SceneBoundary, ...]:
        if duration_ms is None or duration_ms <= 0:
            raise ContentValidationError("scene detection requires a positive media duration")
        filter_graph = f"select=gt(scene\\,{self._threshold:.3f}),showinfo"
        result = await self._runner.run(
            (
                "ffmpeg",
                "-hide_banner",
                "-nostdin",
                "-i",
                str(path),
                "-vf",
                filter_graph,
                "-an",
                "-f",
                "null",
                "-",
            ),
            cwd=scratch_dir,
        )
        if result.returncode != 0:
            raise ProcessLimitError("ffmpeg scene detection failed")

        cuts = sorted(
            {
                round(float(match.group(1)) * 1000)
                for match in _SCENE_TIME.finditer(result.stderr)
                if 0 < float(match.group(1)) * 1000 < duration_ms
            }
        )
        boundaries = [0]
        for cut in cuts:
            if cut - boundaries[-1] < self._min_scene_ms:
                continue
            if duration_ms - cut < self._min_scene_ms:
                continue
            boundaries.append(cut)
            if len(boundaries) >= self._max_scenes:
                break
        boundaries.append(duration_ms)

        scenes = tuple(
            SceneBoundary(ordinal=index, start_ms=start, end_ms=end)
            for index, (start, end) in enumerate(pairwise(boundaries))
            if end > start
        )
        if not scenes:
            raise ContentValidationError("scene detector produced no valid scenes")
        return scenes


class SceneRanker:
    version = "deterministic-duration-position-v1"

    def rank(
        self,
        scenes: Sequence[SceneBoundary],
        *,
        asset_duration_ms: int,
        classification: BaseContentClassification,
    ) -> tuple[RankedScene, ...]:
        if asset_duration_ms <= 0:
            raise ValueError("asset_duration_ms must be positive")
        ranked: list[RankedScene] = []
        for scene in scenes:
            duration = scene.end_ms - scene.start_ms
            duration_score = max(0.0, 1.0 - abs(duration - 12_000) / 20_000)
            midpoint = (scene.start_ms + scene.end_ms) / 2
            normalized_midpoint = midpoint / asset_duration_ms
            center_score = max(0.0, 1.0 - abs(normalized_midpoint - 0.5) * 2)
            score = 0.8 * duration_score + 0.2 * center_score
            if duration < 1_500:
                score *= 0.35
            score = round(min(1.0, max(0.0, score)), 6)
            ranked.append(
                RankedScene(
                    ordinal=scene.ordinal,
                    start_ms=scene.start_ms,
                    end_ms=scene.end_ms,
                    rank_score=score,
                    adult_classification=classification.adult,
                    explicitness_score=classification.explicitness_score,
                    classification_basis=SceneClassificationBasis.ASSET_LEVEL_INHERITED,
                    signals=(
                        *classification.signals,
                        "scene_classification_inherits_asset_baseline",
                    ),
                )
            )
        return tuple(sorted(ranked, key=lambda scene: (-scene.rank_score, scene.ordinal)))
