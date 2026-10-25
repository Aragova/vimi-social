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
