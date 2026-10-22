import asyncio
import hashlib
from dataclasses import dataclass
from pathlib import Path

from vimi_social.domain.analysis import RenderStrategy
from vimi_social.media.probe import MediaProbe
from vimi_social.media.process_runner import MediaToolRunner, ProcessLimits
from vimi_social.media.render_repository import RenderInput
from vimi_social.media.secure_ingest.errors import ContentValidationError, ProcessLimitError
from vimi_social.media.secure_ingest.fetcher import promote_validated_fetch
from vimi_social.media.secure_ingest.models import FetchResult


@dataclass(frozen=True, slots=True)
class RenderedVariant:
    path: Path
    sha256: str
    size_bytes: int
    duration_ms: int


class VariantRenderer:
    version = "ffmpeg-render-v1"

    def __init__(
        self,
        *,
        max_bytes: int,
        runner: MediaToolRunner | None = None,
        probe: MediaProbe | None = None,
    ) -> None:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        self._max_bytes = max_bytes
        self._runner = runner or MediaToolRunner(
            ProcessLimits(timeout_seconds=180.0, max_output_bytes=512 * 1024)
        )
        self._probe = probe or MediaProbe()

    async def render(
        self,
        media_path: Path,
        render_input: RenderInput,
        *,
        scratch_dir: Path,
        durable_dir: Path,
    ) -> RenderedVariant:
        if render_input.strategy is not RenderStrategy.CLIP_SEQUENCE:
            raise ValueError("renderer only accepts CLIP_SEQUENCE recipes")
        if not render_input.segments:
            raise ValueError("clip-sequence recipe has no segments")
        scratch_dir.mkdir(parents=True, exist_ok=True)
        output_path = scratch_dir / "variant.mp4"
        argv = _ffmpeg_argv(media_path, output_path, render_input)
        result = await self._runner.run(argv, cwd=scratch_dir)
        if result.returncode != 0 or not output_path.is_file():
            raise ProcessLimitError("ffmpeg variant render failed")
        size_bytes = output_path.stat().st_size
        if size_bytes <= 0 or size_bytes > self._max_bytes:
            raise ContentValidationError("rendered variant size is outside configured limits")

        probe = await self._probe.probe(output_path, scratch_dir=scratch_dir / "probe")
        duration_ms = probe.duration_ms
        if duration_ms is None or duration_ms <= 0 or probe.video_codec is None:
            raise ContentValidationError("rendered variant failed MediaProbe validation")
        tolerance_ms = max(1500, int(render_input.expected_duration_ms * 0.08))
        if abs(duration_ms - render_input.expected_duration_ms) > tolerance_ms:
            raise ContentValidationError("rendered variant duration differs from render recipe")

        sha256 = await asyncio.to_thread(_sha256_file, output_path)
        staged = FetchResult(
            path=output_path,
            sha256=sha256,
            size_bytes=size_bytes,
            media_format="mp4",
            content_type="video/mp4",
            final_url="render://local",
            redirect_count=0,
        )
        promoted = await promote_validated_fetch(staged, durable_dir)
        return RenderedVariant(
            path=promoted.path,
            sha256=promoted.sha256,
            size_bytes=promoted.size_bytes,
            duration_ms=duration_ms,
        )


def _ffmpeg_argv(
    media_path: Path,
    output_path: Path,
    render_input: RenderInput,
) -> tuple[str, ...]:
    filters: list[str] = []
    concat_inputs: list[str] = []
    for index, (start_ms, end_ms) in enumerate(render_input.segments):
        if start_ms < 0 or end_ms <= start_ms:
            raise ValueError("render segment bounds are invalid")
        start = start_ms / 1000
        end = end_ms / 1000
        filters.append(
            f"[0:v]trim=start={start:.3f}:end={end:.3f},setpts=PTS-STARTPTS[v{index}]"
        )
        concat_inputs.append(f"[v{index}]")
        if render_input.has_audio:
            filters.append(
                f"[0:a]atrim=start={start:.3f}:end={end:.3f},asetpts=PTS-STARTPTS[a{index}]"
            )
            concat_inputs.append(f"[a{index}]")
    stream_count = len(render_input.segments)
    if render_input.has_audio:
        filters.append(
            "".join(concat_inputs) + f"concat=n={stream_count}:v=1:a=1[outv][outa]"
        )
    else:
        filters.append(
            "".join(concat_inputs) + f"concat=n={stream_count}:v=1:a=0[outv]"
        )

    argv: list[str] = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(media_path),
        "-filter_complex",
        ";".join(filters),
        "-map",
        "[outv]",
    ]
    if render_input.has_audio:
        argv.extend(("-map", "[outa]"))
    argv.extend(
        (
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-pix_fmt",
            "yuv420p",
        )
    )
    if render_input.has_audio:
        argv.extend(("-c:a", "aac", "-b:a", "128k"))
    argv.extend(("-movflags", "+faststart", "-y", str(output_path)))
    return tuple(argv)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
