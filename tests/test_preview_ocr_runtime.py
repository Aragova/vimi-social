from dataclasses import dataclass
from pathlib import Path

from apps.local_ai.visual import SiglipPreviewScorer


@dataclass(frozen=True)
class FakeOcrResult:
    txts: tuple[str, ...]
    scores: tuple[float, ...]


class FakeOcrEngine:
    def __call__(self, data: bytes, *, use_cls: bool) -> FakeOcrResult:
        assert data == b"preview-bytes"
        assert use_cls is False
        return FakeOcrResult(
            txts=(" BANGKOK   NIGHT MARKET ", "noise", "BANGKOK NIGHT MARKET"),
            scores=(0.96, 0.30, 0.91),
        )


class TestablePreviewOcrScorer(SiglipPreviewScorer):
    async def _download_preview(self, url: str) -> bytes:
        assert url == "https://pbs.twimg.com/media/example.jpg"
        return b"preview-bytes"

    def _ensure_ocr_engine(self) -> FakeOcrEngine:
        return FakeOcrEngine()

    def ocr_parameters(self, model_root: Path) -> dict[str, object]:
        return self._ocr_parameters(model_root)


def test_preview_ocr_normalizes_filters_and_deduplicates_lines(tmp_path: Path) -> None:
    scorer = TestablePreviewOcrScorer(tmp_path)

    texts = scorer.extract_texts(["https://pbs.twimg.com/media/example.jpg"])

    assert texts == ["BANGKOK NIGHT MARKET"]


def test_preview_ocr_models_use_writable_cache_directory(tmp_path: Path) -> None:
    scorer = TestablePreviewOcrScorer(tmp_path)
    model_root = tmp_path / "rapidocr"

    params = scorer.ocr_parameters(model_root)

    assert params["Global.model_root_dir"] == str(model_root)
    assert params["Global.use_cls"] is False
