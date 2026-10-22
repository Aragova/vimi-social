from vimi_social.media.secure_ingest.errors import ContentValidationError
from vimi_social.media.secure_ingest.models import MediaFormat

JPEG = MediaFormat("jpeg", "jpg", frozenset({"image/jpeg", "application/octet-stream"}))
PNG = MediaFormat("png", "png", frozenset({"image/png", "application/octet-stream"}))
GIF = MediaFormat("gif", "gif", frozenset({"image/gif", "application/octet-stream"}))
WEBP = MediaFormat("webp", "webp", frozenset({"image/webp", "application/octet-stream"}))
MP4 = MediaFormat(
    "mp4",
    "mp4",
    frozenset({"video/mp4", "audio/mp4", "application/mp4", "application/octet-stream"}),
)
WEBM = MediaFormat(
    "webm",
    "webm",
    frozenset(
        {
            "video/webm",
            "audio/webm",
            "video/x-matroska",
            "audio/x-matroska",
            "application/octet-stream",
        }
    ),
)
MP3 = MediaFormat("mp3", "mp3", frozenset({"audio/mpeg", "application/octet-stream"}))
OGG = MediaFormat(
    "ogg",
    "ogg",
    frozenset({"audio/ogg", "video/ogg", "application/ogg", "application/octet-stream"}),
)
WAV = MediaFormat(
    "wav",
    "wav",
    frozenset({"audio/wav", "audio/x-wav", "application/octet-stream"}),
)


def sniff_media_format(prefix: bytes) -> MediaFormat:
    if prefix.startswith(b"\xff\xd8\xff"):
        return JPEG
    if prefix.startswith(b"\x89PNG\r\n\x1a\n"):
        return PNG
    if prefix.startswith((b"GIF87a", b"GIF89a")):
        return GIF
    if len(prefix) >= 12 and prefix[:4] == b"RIFF" and prefix[8:12] == b"WEBP":
        return WEBP
    if len(prefix) >= 12 and prefix[4:8] == b"ftyp":
        return MP4
    if prefix.startswith(b"\x1a\x45\xdf\xa3"):
        return WEBM
    if prefix.startswith(b"ID3") or _looks_like_mp3_frame(prefix):
        return MP3
    if prefix.startswith(b"OggS"):
        return OGG
    if len(prefix) >= 12 and prefix[:4] == b"RIFF" and prefix[8:12] == b"WAVE":
        return WAV
    raise ContentValidationError("response bytes do not match an accepted media signature")


def validate_declared_content_type(content_type_header: str | None, media: MediaFormat) -> str:
    if content_type_header is None:
        raise ContentValidationError("response is missing Content-Type")
    normalized = content_type_header.split(";", 1)[0].strip().lower()
    if not normalized:
        raise ContentValidationError("response Content-Type is empty")
    if normalized not in media.allowed_content_types:
        raise ContentValidationError(
            f"declared Content-Type {normalized!r} does not match detected {media.name}"
        )
    return normalized


def _looks_like_mp3_frame(prefix: bytes) -> bool:
    return len(prefix) >= 2 and prefix[0] == 0xFF and (prefix[1] & 0xE0) == 0xE0
