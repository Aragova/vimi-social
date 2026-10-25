from collections.abc import Callable
from types import SimpleNamespace
from typing import Any, cast

import pytest
from apps.local_ai import main as local_ai_main
from apps.local_ai import visual as local_ai_visual


class _FakeModelSource:
    def __init__(self, *, hf: str) -> None:
        self.hf = hf


class _FakeTextEmbedding:
    registration: dict[str, Any] | None = None

    @classmethod
    def list_supported_models(cls) -> list[dict[str, object]]:
        return []

    @classmethod
    def add_custom_model(cls, **kwargs: Any) -> None:
        cls.registration = dict(kwargs)

    def __init__(self, **kwargs: Any) -> None:
        assert self.registration is not None
        self.kwargs = dict(kwargs)


class _FakeSourceSentencePiece:
    def encode(self, text: str, *, out_type: type[str]) -> list[str]:
        assert text == "Найди видео про ночной Бангкок"
        assert out_type is str
        return ["▁Найди", "▁видео", "▁Бангкок"]


class _FakeTranslator:
    def __init__(self) -> None:
        self.batch: list[list[str]] | None = None

    def translate_batch(
        self,
        batch: list[list[str]],
        *,
        beam_size: int,
        max_decoding_length: int,
    ) -> list[SimpleNamespace]:
        self.batch = batch
        assert beam_size == 1
        assert max_decoding_length == 128
        return [SimpleNamespace(hypotheses=[["▁Bangkok", "▁at", "▁night"]])]


class _FakeTargetSentencePiece:
    def decode(self, tokens: list[str]) -> str:
        assert tokens == ["▁Bangkok", "▁at", "▁night"]
        return "Bangkok at night"


def test_local_translation_appends_source_eos_before_inference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    translator = _FakeTranslator()
    source_sp = _FakeSourceSentencePiece()
    target_sp = _FakeTargetSentencePiece()

    def fake_ensure_translation(
        self: local_ai_main.LocalModels,
    ) -> tuple[_FakeTranslator, _FakeSourceSentencePiece, _FakeTargetSentencePiece]:
        del self
        return translator, source_sp, target_sp

    monkeypatch.setattr(
        local_ai_main.LocalModels,
        "_ensure_translation",
        fake_ensure_translation,
    )

    models = local_ai_main.LocalModels()
    translated = models.translate_ru_to_en("Найди видео про ночной Бангкок")

    assert translated == "Bangkok at night"
    assert translator.batch == [["▁Найди", "▁видео", "▁Бангкок", "</s>"]]


def test_local_ai_routes_huggingface_cache_to_writable_model_cache(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    cache_dir = tmp_path / "ai-models"
    monkeypatch.setenv("VIMI_LOCAL_AI_CACHE", str(cache_dir))
    for variable in ("XDG_CACHE_HOME", "HF_HOME", "HF_HUB_CACHE", "HF_XET_CACHE"):
        monkeypatch.delenv(variable, raising=False)

    models = local_ai_main.LocalModels()
    configure_cache = cast(
        Callable[[local_ai_main.LocalModels], None],
        local_ai_main.LocalModels.__dict__["_configure_cache_environment"],
    )
    configure_cache(models)

    assert local_ai_main.os.environ["XDG_CACHE_HOME"] == str(cache_dir / "xdg")
    assert local_ai_main.os.environ["HF_HOME"] == str(cache_dir / "huggingface")
    assert local_ai_main.os.environ["HF_HUB_CACHE"] == str(
        cache_dir / "huggingface" / "hub"
    )
    assert local_ai_main.os.environ["HF_XET_CACHE"] == str(
        cache_dir / "huggingface" / "xet"
    )


def test_visual_ai_routes_huggingface_cache_to_writable_model_cache(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    cache_dir = tmp_path / "visual-models"
    for variable in ("XDG_CACHE_HOME", "HF_HOME", "HF_HUB_CACHE", "HF_XET_CACHE"):
        monkeypatch.delenv(variable, raising=False)

    scorer = local_ai_visual.SiglipPreviewScorer(cache_dir)
    configure_cache = cast(
        Callable[[local_ai_visual.SiglipPreviewScorer], None],
        local_ai_visual.SiglipPreviewScorer.__dict__["_configure_cache_environment"],
    )
    configure_cache(scorer)

    assert local_ai_visual.os.environ["XDG_CACHE_HOME"] == str(cache_dir / "xdg")
    assert local_ai_visual.os.environ["HF_HOME"] == str(cache_dir / "huggingface")
    assert local_ai_visual.os.environ["HF_HUB_CACHE"] == str(
        cache_dir / "huggingface" / "hub"
    )
    assert local_ai_visual.os.environ["HF_XET_CACHE"] == str(
        cache_dir / "huggingface" / "xet"
    )


def test_default_e5_model_is_registered_before_fastembed_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeTextEmbedding.registration = None
    modules: dict[str, SimpleNamespace] = {
        "fastembed": SimpleNamespace(TextEmbedding=_FakeTextEmbedding),
        "fastembed.common.model_description": SimpleNamespace(
            ModelSource=_FakeModelSource,
            PoolingType=SimpleNamespace(MEAN="mean"),
        ),
    }

    def fake_import_module(name: str) -> SimpleNamespace:
        return modules[name]

    monkeypatch.setattr(local_ai_main, "import_module", fake_import_module)

    models = local_ai_main.LocalModels()
    ensure_embedder = cast(
        Callable[[local_ai_main.LocalModels], Any],
        local_ai_main.LocalModels.__dict__["_ensure_embedder"],
    )
    embedder = ensure_embedder(models)

    registration = _FakeTextEmbedding.registration
    assert registration is not None
    assert registration["model"] == "intfloat/multilingual-e5-small"
    assert registration["pooling"] == "mean"
    assert registration["normalization"] is True
    assert registration["dim"] == 384
    assert registration["model_file"] == "onnx/model.onnx"
    source = cast(_FakeModelSource, registration["sources"])
    assert source.hf == "intfloat/multilingual-e5-small"
    assert embedder.kwargs["model_name"] == "intfloat/multilingual-e5-small"
