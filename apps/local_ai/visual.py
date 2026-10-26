import asyncio
import io
import os
from collections.abc import Callable, Mapping
from importlib import import_module
from pathlib import Path
from threading import Lock
from typing import Any, cast
from urllib.parse import urlparse

from vimi_social.media.secure_ingest.addressing import DestinationPolicy, SystemHostResolver
from vimi_social.media.secure_ingest.models import FetchTimeouts, OneHopTransport
from vimi_social.media.secure_ingest.transport import PinnedAiohttpTransport

_DEFAULT_VISUAL_MODEL = "Xenova/siglip-base-patch16-224"
_DEFAULT_OCR_MODEL = "RapidOCR/PP-OCRv6-small"
_ALLOWED_PREVIEW_HOSTS = frozenset({"pbs.twimg.com"})
_MAX_PREVIEW_BYTES = 4 * 1024 * 1024
_PREVIEW_CHUNK_SIZE = 64 * 1024
_PREVIEW_TIMEOUTS = FetchTimeouts(
    connect_seconds=5.0,
    read_seconds=10.0,
    total_seconds=15.0,
)
_OCR_TEXT_SCORE = 0.55
_MAX_OCR_LINES = 32
_MAX_OCR_CHARS = 2000


class SiglipPreviewScorer:
    """CPU-only preview evidence for official X image previews.

    Scout discovery is intentionally limited to connector-provided previews. Full video
    acquisition remains behind the existing rights gate and media-preparation workflow.
    """

    def __init__(
        self,
        cache_dir: Path,
        *,
        destination_policy: DestinationPolicy | None = None,
        transport: OneHopTransport | None = None,
    ) -> None:
        self._cache_dir = cache_dir
        self._model_repo = os.getenv("VIMI_LOCAL_VISUAL_MODEL", _DEFAULT_VISUAL_MODEL)
        self._destination_policy = destination_policy or DestinationPolicy(SystemHostResolver())
        self._transport = transport or PinnedAiohttpTransport()
        self._lock = Lock()
        self._ocr_model_lock = Lock()
        self._ocr_inference_lock = Lock()
        self._text_session: Any | None = None
        self._vision_session: Any | None = None
        self._tokenizer: Any | None = None
        self._ocr_engine: Any | None = None

    @property
    def model(self) -> str:
        return self._model_repo

    @property
    def ocr_model(self) -> str:
        return _DEFAULT_OCR_MODEL

    def score(
        self,
        query_variants: list[str],
        preview_image_urls: list[str],
    ) -> list[float | None]:
        text_session, vision_session, tokenizer = self._ensure_models()
        np = cast(Any, import_module("numpy"))
        text_embeddings = self._text_embeddings(text_session, tokenizer, query_variants, np)
        if text_embeddings.shape[0] == 0:
            return [None] * len(preview_image_urls)

        scores: list[float | None] = []
        for preview_url in preview_image_urls:
            try:
                pixel_values = self._download_and_preprocess(preview_url, np)
                image_embedding = self._vision_embedding(vision_session, pixel_values, np)
                similarities = image_embedding @ text_embeddings.T
                score = float(similarities.max())
                scores.append(round(max(-1.0, min(1.0, score)), 6))
            except Exception:
                scores.append(None)
        return scores

    def extract_texts(self, preview_image_urls: list[str]) -> list[str | None]:
        engine = self._ensure_ocr_engine()
        texts: list[str | None] = []
        for preview_url in preview_image_urls:
            try:
                data = asyncio.run(self._download_preview(preview_url))
                with self._ocr_inference_lock:
                    result = engine(data, use_cls=False)
                lines = self._ocr_lines(result)
                merged = " | ".join(lines)
                texts.append(merged[:_MAX_OCR_CHARS] or None)
            except Exception:
                texts.append(None)
        return texts

    def _configure_cache_environment(self) -> None:
        huggingface_home = self._cache_dir / "huggingface"
        os.environ.setdefault("XDG_CACHE_HOME", str(self._cache_dir / "xdg"))
        os.environ.setdefault("HF_HOME", str(huggingface_home))
        os.environ.setdefault("HF_HUB_CACHE", str(huggingface_home / "hub"))
        os.environ.setdefault("HF_XET_CACHE", str(huggingface_home / "xet"))

    def _ensure_models(self) -> tuple[Any, Any, Any]:
        if (
            self._text_session is not None
            and self._vision_session is not None
            and self._tokenizer is not None
        ):
            return self._text_session, self._vision_session, self._tokenizer

        with self._lock:
            if (
                self._text_session is not None
                and self._vision_session is not None
                and self._tokenizer is not None
            ):
                return self._text_session, self._vision_session, self._tokenizer

            self._configure_cache_environment()
            huggingface_module = cast(Any, import_module("huggingface_hub"))
            ort = cast(Any, import_module("onnxruntime"))
            tokenizers_module = cast(Any, import_module("tokenizers"))
            snapshot_download = cast(Callable[..., str], huggingface_module.snapshot_download)

            model_path = Path(
                snapshot_download(
                    repo_id=self._model_repo,
                    cache_dir=str(self._cache_dir / "huggingface"),
                    allow_patterns=[
                        "onnx/text_model_quantized.onnx",
                        "onnx/vision_model_quantized.onnx",
                        "tokenizer.json",
                    ],
                )
            )

            session_options = ort.SessionOptions()
            session_options.intra_op_num_threads = max(1, min(2, os.cpu_count() or 1))
            session_options.inter_op_num_threads = 1
            session_options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            session_options.enable_mem_pattern = False

            text_session = ort.InferenceSession(
                str(model_path / "onnx" / "text_model_quantized.onnx"),
                sess_options=session_options,
                providers=["CPUExecutionProvider"],
            )
            vision_session = ort.InferenceSession(
                str(model_path / "onnx" / "vision_model_quantized.onnx"),
                sess_options=session_options,
                providers=["CPUExecutionProvider"],
            )
            tokenizer = tokenizers_module.Tokenizer.from_file(str(model_path / "tokenizer.json"))
            tokenizer.enable_truncation(max_length=64)
            tokenizer.enable_padding(length=64, pad_id=1, pad_token="</s>")

            self._text_session = text_session
            self._vision_session = vision_session
            self._tokenizer = tokenizer
            return text_session, vision_session, tokenizer

    def _ensure_ocr_engine(self) -> Any:
        if self._ocr_engine is not None:
            return self._ocr_engine

        with self._ocr_model_lock:
            if self._ocr_engine is not None:
                return self._ocr_engine
            rapidocr_module = cast(Any, import_module("rapidocr"))
            engine_factory = cast(Callable[..., Any], rapidocr_module.RapidOCR)
            model_root = self._cache_dir / "rapidocr"
            model_root.mkdir(parents=True, exist_ok=True)
            self._ocr_engine = engine_factory(params=self._ocr_parameters(model_root))
            return self._ocr_engine

    @staticmethod
    def _ocr_parameters(model_root: Path) -> dict[str, object]:
        return {
            "Global.model_root_dir": str(model_root),
            "Global.text_score": _OCR_TEXT_SCORE,
            "Global.use_cls": False,
        }

    def _text_embeddings(
        self,
        session: Any,
        tokenizer: Any,
        query_variants: list[str],
        np: Any,
    ) -> Any:
        prompts = [f"a photo of {' '.join(query.split()).strip()}" for query in query_variants]
        prompts = [prompt for prompt in prompts if prompt != "a photo of "]
        if not prompts:
            return np.empty((0, 768), dtype=np.float32)

        encodings = tokenizer.encode_batch(prompts)
        input_ids = np.asarray([encoding.ids for encoding in encodings], dtype=np.int64)
        attention_mask = np.asarray(
            [encoding.attention_mask for encoding in encodings],
            dtype=np.int64,
        )
        feed: dict[str, Any] = {}
        for model_input in session.get_inputs():
            if model_input.name == "input_ids":
                feed[model_input.name] = input_ids
            elif model_input.name == "attention_mask":
                feed[model_input.name] = attention_mask
            else:
                raise RuntimeError(f"unsupported SigLIP text input: {model_input.name}")
        embeddings = np.asarray(self._pooler_output(session, feed), dtype=np.float32)
        return self._normalize_rows(embeddings, np)

    def _vision_embedding(self, session: Any, pixel_values: Any, np: Any) -> Any:
        inputs = session.get_inputs()
        if len(inputs) != 1 or inputs[0].name != "pixel_values":
            names = ",".join(model_input.name for model_input in inputs)
            raise RuntimeError(f"unsupported SigLIP vision inputs: {names}")
        feed = {"pixel_values": pixel_values}
        embedding = np.asarray(self._pooler_output(session, feed), dtype=np.float32)
        return self._normalize_rows(embedding, np)

    @staticmethod
    def _pooler_output(session: Any, feed: dict[str, Any]) -> Any:
        output_names = [output.name for output in session.get_outputs()]
        values = session.run(None, feed)
        if "pooler_output" in output_names:
            return values[output_names.index("pooler_output")]
        if len(values) == 1:
            return values[0]
        for index, name in enumerate(output_names):
            if "pooler" in name:
                return values[index]
        raise RuntimeError("SigLIP ONNX model omitted pooler output")

    def _download_and_preprocess(self, url: str, np: Any) -> Any:
        data = asyncio.run(self._download_preview(url))
        image_module = cast(Any, import_module("PIL.Image"))
        with image_module.open(io.BytesIO(data)) as image:
            rgb = image.convert("RGB")
            resized = rgb.resize((224, 224), image_module.Resampling.BICUBIC)
            pixels = np.asarray(resized, dtype=np.float32)
        normalized = (pixels / 127.5) - 1.0
        return np.transpose(normalized, (2, 0, 1))[None, ...]

    async def _download_preview(self, url: str) -> bytes:
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or hostname not in _ALLOWED_PREVIEW_HOSTS:
            raise ValueError("preview URL is not an allowed official X image host")

        target = await self._destination_policy.resolve_url(
            url,
            timeout_seconds=_PREVIEW_TIMEOUTS.connect_seconds,
        )
        if target.scheme != "https" or target.host not in _ALLOWED_PREVIEW_HOSTS:
            raise ValueError("resolved preview target is not an allowed official X image host")

        response = await self._transport.open(target, timeouts=_PREVIEW_TIMEOUTS)
        try:
            if response.status != 200:
                raise RuntimeError(f"preview fetch failed with HTTP {response.status}")
            content_type = (_header_value(response.headers, "content-type") or "").lower()
            if not content_type.startswith("image/"):
                raise RuntimeError("preview response is not an image")
            raw_length = _header_value(response.headers, "content-length")
            if raw_length is not None and int(raw_length) > _MAX_PREVIEW_BYTES:
                raise RuntimeError("preview image exceeds size limit")

            data = bytearray()
            async for chunk in response.iter_chunks(_PREVIEW_CHUNK_SIZE):
                data.extend(chunk)
                if len(data) > _MAX_PREVIEW_BYTES:
                    raise RuntimeError("preview image exceeds size limit")
            return bytes(data)
        finally:
            await response.close()

    @staticmethod
    def _ocr_lines(result: Any) -> tuple[str, ...]:
        raw_texts_obj = getattr(result, "txts", None)
        raw_scores_obj = getattr(result, "scores", None)
        if not isinstance(raw_texts_obj, (list, tuple)):
            return ()

        raw_texts = cast(list[object] | tuple[object, ...], raw_texts_obj)
        raw_scores = (
            cast(list[object] | tuple[object, ...], raw_scores_obj)
            if isinstance(raw_scores_obj, (list, tuple))
            else None
        )

        lines: list[str] = []
        for index, raw_text in enumerate(raw_texts):
            text = " ".join(str(raw_text).split()).strip()
            if not text:
                continue
            confidence = 1.0
            if raw_scores is not None and index < len(raw_scores):
                raw_confidence = raw_scores[index]
                if (
                    isinstance(raw_confidence, int | float)
                    and not isinstance(raw_confidence, bool)
                ):
                    confidence = float(raw_confidence)
                else:
                    confidence = 0.0
            if confidence < _OCR_TEXT_SCORE or text in lines:
                continue
            lines.append(text)
            if len(lines) >= _MAX_OCR_LINES:
                break
        return tuple(lines)

    @staticmethod
    def _normalize_rows(matrix: Any, np: Any) -> Any:
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        return matrix / np.clip(norms, 1e-12, None)


def _header_value(headers: Mapping[str, str], name: str) -> str | None:
    direct = headers.get(name)
    if direct is not None:
        return direct
    wanted = name.casefold()
    for key, value in headers.items():
        if key.casefold() == wanted:
            return value
    return None
