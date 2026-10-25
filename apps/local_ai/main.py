# pyright: reportMissingImports=false

import asyncio
import os
from pathlib import Path
from threading import Lock
from typing import Any, cast

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


class TranslateRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    source_language: str = "ru"
    target_language: str = "en"


class TranslateResponse(BaseModel):
    text: str
    provider: str
    model: str


class SemanticScoreRequest(BaseModel):
    query_variants: list[str] = Field(min_length=1, max_length=4)
    documents: list[str] = Field(min_length=1, max_length=100)


class SemanticScoreResponse(BaseModel):
    scores: list[float]
    provider: str
    model: str


class LocalModels:
    def __init__(self) -> None:
        self._cache_dir = Path(os.getenv("VIMI_LOCAL_AI_CACHE", "/var/lib/vimi/ai-models"))
        self._translation_repo = os.getenv(
            "VIMI_LOCAL_TRANSLATION_MODEL",
            "gaudi/opus-mt-ru-en-ctranslate2",
        )
        self._embedding_model_name = os.getenv(
            "VIMI_LOCAL_EMBEDDING_MODEL",
            "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        )
        self._translation_lock = Lock()
        self._embedding_lock = Lock()
        self._translator: Any | None = None
        self._source_sp: Any | None = None
        self._target_sp: Any | None = None
        self._embedder: Any | None = None

    @property
    def translation_model(self) -> str:
        return self._translation_repo

    @property
    def embedding_model(self) -> str:
        return self._embedding_model_name

    def translate_ru_to_en(self, text: str) -> str:
        translator, source_sp, target_sp = self._ensure_translation()
        source_tokens = source_sp.encode(text, out_type=str)
        results = translator.translate_batch(
            [source_tokens],
            beam_size=1,
            max_decoding_length=128,
        )
        output_tokens = results[0].hypotheses[0]
        translated = target_sp.decode(output_tokens)
        return " ".join(str(translated).split()).strip()

    def semantic_scores(
        self,
        query_variants: list[str],
        documents: list[str],
    ) -> list[float]:
        embedder = self._ensure_embedder()
        np = self._numpy()

        queries = [f"query: {query.strip()}" for query in query_variants]
        passages = [f"passage: {document.strip()}" for document in documents]
        query_vectors = np.asarray(list(embedder.embed(queries)), dtype=np.float32)
        document_vectors = np.asarray(list(embedder.embed(passages)), dtype=np.float32)
        query_vectors = self._normalize_rows(query_vectors, np)
        document_vectors = self._normalize_rows(document_vectors, np)
        similarities = document_vectors @ query_vectors.T
        best = similarities.max(axis=1)
        return [round(float(max(-1.0, min(1.0, score))), 6) for score in best.tolist()]

    def _ensure_translation(self) -> tuple[Any, Any, Any]:
        if self._translator is not None and self._source_sp is not None and self._target_sp is not None:
            return self._translator, self._source_sp, self._target_sp

        with self._translation_lock:
            if (
                self._translator is not None
                and self._source_sp is not None
                and self._target_sp is not None
            ):
                return self._translator, self._source_sp, self._target_sp

            from ctranslate2 import Translator
            from huggingface_hub import snapshot_download
            from sentencepiece import SentencePieceProcessor

            model_path = Path(
                snapshot_download(
                    repo_id=self._translation_repo,
                    cache_dir=str(self._cache_dir / "huggingface"),
                    allow_patterns=[
                        "config.json",
                        "model.bin",
                        "shared_vocabulary.json",
                        "source.spm",
                        "target.spm",
                    ],
                )
            )
            self._translator = Translator(
                str(model_path),
                device="cpu",
                compute_type="int8",
                inter_threads=1,
                intra_threads=max(1, min(2, os.cpu_count() or 1)),
            )
            self._source_sp = SentencePieceProcessor(model_file=str(model_path / "source.spm"))
            self._target_sp = SentencePieceProcessor(model_file=str(model_path / "target.spm"))
            return self._translator, self._source_sp, self._target_sp

    def _ensure_embedder(self) -> Any:
        if self._embedder is not None:
            return self._embedder

        with self._embedding_lock:
            if self._embedder is not None:
                return self._embedder

            from fastembed import TextEmbedding

            self._embedder = TextEmbedding(
                model_name=self._embedding_model_name,
                cache_dir=str(self._cache_dir / "fastembed"),
                threads=max(1, min(2, os.cpu_count() or 1)),
            )
            return self._embedder

    @staticmethod
    def _numpy() -> Any:
        import numpy

        return cast(Any, numpy)

    @staticmethod
    def _normalize_rows(matrix: Any, np: Any) -> Any:
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        return matrix / np.clip(norms, 1e-12, None)


models = LocalModels()
app = FastAPI(title="ViMi Local AI", docs_url=None, redoc_url=None)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/v1/models")
async def model_manifest() -> dict[str, object]:
    return {
        "translation": {
            "provider": "local-ctranslate2",
            "model": models.translation_model,
            "requires_paid_api": False,
        },
        "semantic_text": {
            "provider": "local-fastembed",
            "model": models.embedding_model,
            "requires_paid_api": False,
        },
    }


@app.post("/v1/translate", response_model=TranslateResponse)
async def translate(request: TranslateRequest) -> TranslateResponse:
    if request.source_language != "ru" or request.target_language != "en":
        raise HTTPException(status_code=422, detail="only ru->en is enabled in this slice")
    try:
        text = await asyncio.to_thread(models.translate_ru_to_en, request.text)
    except Exception as error:
        raise HTTPException(status_code=503, detail="local translation unavailable") from error
    if not text:
        raise HTTPException(status_code=503, detail="local translation returned empty output")
    return TranslateResponse(
        text=text,
        provider="local-ctranslate2",
        model=models.translation_model,
    )


@app.post("/v1/semantic-score", response_model=SemanticScoreResponse)
async def semantic_score(request: SemanticScoreRequest) -> SemanticScoreResponse:
    try:
        scores = await asyncio.to_thread(
            models.semantic_scores,
            request.query_variants,
            request.documents,
        )
    except Exception as error:
        raise HTTPException(status_code=503, detail="local semantic model unavailable") from error
    return SemanticScoreResponse(
        scores=scores,
        provider="local-fastembed",
        model=models.embedding_model,
    )
