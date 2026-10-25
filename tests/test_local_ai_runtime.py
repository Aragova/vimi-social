from collections.abc import Callable
from types import SimpleNamespace
from typing import Any, cast

import pytest
from apps.local_ai import main as local_ai_main


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
