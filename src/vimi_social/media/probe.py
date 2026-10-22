import json
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol, cast

from vimi_social.domain.media import MediaProbeResult
from vimi_social.media.process_runner import MediaToolRunner, ProcessResult
from vimi_social.media.secure_ingest.errors import ContentValidationError, ProcessLimitError


class ToolRunner(Protocol):
    async def run(self, argv: Sequence[str], *, cwd: Path) -> ProcessResult: ...


class MediaProbe:
    def __init__(self, runner: ToolRunner | None = None) -> None:
        self._runner = runner or MediaToolRunner()

    async def probe(self, path: Path, *, scratch_dir: Path) -> MediaProbeResult:
        result = await self._runner.run(
            (
                "ffprobe",
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                "--",
                str(path),
            ),
            cwd=scratch_dir,
        )
        if result.returncode != 0:
            raise ProcessLimitError("ffprobe rejected the ingested media")
        try:
            raw: object = json.loads(result.stdout)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ContentValidationError("ffprobe returned invalid JSON") from exc
        if not isinstance(raw, dict):
            raise ContentValidationError("ffprobe returned an invalid response shape")
        payload = cast(dict[str, object], raw)
        streams = _object_list(payload.get("streams"))
        video = next(
            (stream for stream in streams if stream.get("codec_type") == "video"),
            None,
        )
        if video is None:
            raise ContentValidationError("ingested media does not contain a video stream")
        audio = next(
            (stream for stream in streams if stream.get("codec_type") == "audio"),
            None,
        )
        format_obj = payload.get("format")
        format_data = cast(dict[str, object], format_obj) if isinstance(format_obj, dict) else {}

        duration_ms = _seconds_to_ms(format_data.get("duration"))
        if duration_ms is None:
            duration_ms = _seconds_to_ms(video.get("duration"))

        return MediaProbeResult(
            duration_ms=duration_ms,
            width=_positive_int(video.get("width")),
            height=_positive_int(video.get("height")),
            video_codec=_optional_str(video.get("codec_name")),
            audio_codec=(
                _optional_str(audio.get("codec_name")) if audio is not None else None
            ),
            container=_optional_str(format_data.get("format_name")),
            frame_rate=_parse_frame_rate(video.get("avg_frame_rate")),
            has_audio=audio is not None,
        )


def _object_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    items = cast(list[object], value)
    return [cast(dict[str, object], item) for item in items if isinstance(item, dict)]


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _positive_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _seconds_to_ms(value: object) -> int | None:
    if isinstance(value, int | float) and not isinstance(value, bool):
        seconds = float(value)
    elif isinstance(value, str):
        try:
            seconds = float(value)
        except ValueError:
            return None
    else:
        return None
    if seconds < 0:
        return None
    return round(seconds * 1000)


def _parse_frame_rate(value: object) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    numerator, separator, denominator = value.partition("/")
    try:
        if separator:
            denominator_value = float(denominator)
            if denominator_value == 0:
                return None
            result = float(numerator) / denominator_value
        else:
            result = float(value)
    except ValueError:
        return None
    return result if result > 0 else None
