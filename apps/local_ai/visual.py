import io
import os
from collections.abc import Callable
from importlib import import_module
from pathlib import Path
from threading import Lock
from typing import Any, cast
from urllib.parse import urlparse

import httpx

_DEFAULT_VISUAL_MODEL = "Xenova/siglip-base-patch16-224"
_ALLOWED_PREVIEW_HOSTS = frozenset({"pbs.twimg.com"})
_MAX_PREVIEW_BYTES = 4 * 1024 * 1024


class SiglipPreviewScorer:
    """CPU-only SigLIP scorer for official X preview images.

    Scout discovery is intentionally limited to connector-provided previews. Full video
    acquisition remains behind the existing rights gate and media-preparation workflow.
    """

    def __init__(self, cache_dir: Path) -> None:
        self._cache_dir = cache_dir
        self._model_repo = os.getenv("VIMI_LOCAL_VISUAL_MODEL", _DEFAULT_VISUAL_MODEL)
        self._lock = Lock()
        self._text_session: Any | None = None
        self._vision_session: Any | None = None
        self._tokenizer: Any | None = None

    @property
    def model(self) -> str:
        return self._model_repo

    def score(self, query_variants: list[str], preview_image_urls: list[str]) -> list[float | None]:
        text_session, vision_session, tokenizer = self._ensure_models()
        np = cast(Any, import_module("numpy"))
        text_embeddings = self._text_embeddings(text_session, tokenizer, query_variants, np)
        if text_embeddings.shape[0] == 0:
            return [None] * len(preview_image_urls)

        scores: list[float | None] = []
        with httpx.Client(timeout=10.0, follow_redirects=False) as client:
            for preview_url in preview_image_urls:
                try:
                    pixel_values = self._download_and_preprocess(preview_url, client, np)
                    image_embedding = self._vision_embedding(vision_session, pixel_values, np)
                    similarities = image_embedding @ text_embeddings.T
                    score = float(similarities.max())
                    scores.append(round(max(-1.0, min(1.0, score)), 6))
                except Exception:
                    scores.append(None)
        return scores

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

            self._text_session = ort.InferenceSession(
                str(model_path / "onnx" / "text_model_quantized.onnx"),
                sess_options=session_options,
                providers=["CPUExecutionProvider"],
            )
            self._vision_session = ort.InferenceSession(
                str(model_path / "onnx" / "vision_model_quantized.onnx"),
                sess_options=session_options,
                providers=["CPUExecutionProvider"],
            )
            self._tokenizer = tokenizers_module.Tokenizer.from_file(
                str(model_path / "tokenizer.json")
            )
            self._tokenizer.enable_truncation(max_length=64)
            self._tokenizer.enable_padding(length=64, pad_id=1, pad_token="</s>")
            return self._text_session, self._vision_session, self._tokenizer

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

    def _download_and_preprocess(self, url: str, client: httpx.Client, np: Any) -> Any:
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or hostname not in _ALLOWED_PREVIEW_HOSTS:
            raise ValueError("preview URL is not an allowed official X image host")

        with client.stream("GET", url, headers={"Accept": "image/*"}) as response:
            if response.status_code != 200:
                raise RuntimeError(f"preview fetch failed with HTTP {response.status_code}")
            content_type = response.headers.get("content-type", "").lower()
            if not content_type.startswith("image/"):
                raise RuntimeError("preview response is not an image")
            raw_length = response.headers.get("content-length")
            if raw_length is not None and int(raw_length) > _MAX_PREVIEW_BYTES:
                raise RuntimeError("preview image exceeds size limit")
            data = bytearray()
            for chunk in response.iter_bytes():
                data.extend(chunk)
                if len(data) > _MAX_PREVIEW_BYTES:
                    raise RuntimeError("preview image exceeds size limit")

        image_module = cast(Any, import_module("PIL.Image"))
        with image_module.open(io.BytesIO(bytes(data))) as image:
            rgb = image.convert("RGB")
            resized = rgb.resize((224, 224), image_module.Resampling.BICUBIC)
            pixels = np.asarray(resized, dtype=np.float32)
        normalized = (pixels / 127.5) - 1.0
        return np.transpose(normalized, (2, 0, 1))[None, ...]

    @staticmethod
    def _normalize_rows(matrix: Any, np: Any) -> Any:
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        return matrix / np.clip(norms, 1e-12, None)
