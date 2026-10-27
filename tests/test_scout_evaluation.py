import json
from pathlib import Path

import pytest

from vimi_social.source.evaluation import (
    ScoutBenchmark,
    ScoutEvalCase,
    ScoutJudgment,
    evaluate_benchmark,
    evaluate_case,
    load_benchmark,
    summary_as_dict,
)


def test_evaluate_case_reports_quality_cost_and_latency() -> None:
    case = ScoutEvalCase(
        case_id="night-bangkok",
        intent="Bangkok at night",
        ranked_candidate_ids=("a", "b", "c", "d"),
        judgments=(
            ScoutJudgment("a", 3),
            ScoutJudgment("b", 0),
            ScoutJudgment("c", 2),
            ScoutJudgment("e", 1),
        ),
        paid_reads=30,
        latency_ms=1250.5,
    )

    metrics = evaluate_case(case, k=3)

    assert metrics.precision_at_k == pytest.approx(2 / 3, abs=1e-6)
    assert metrics.recall_at_k == pytest.approx(2 / 3, abs=1e-6)
    assert metrics.ndcg_at_k == pytest.approx(0.9049495, abs=1e-6)
    assert metrics.relevant_retrieved == 2
    assert metrics.relevant_per_paid_read == pytest.approx(2 / 30, abs=1e-6)
    assert metrics.latency_ms == 1250.5
    assert metrics.retrieved_count == 4
    assert metrics.judged_relevant_count == 3


def test_precision_penalizes_short_result_lists() -> None:
    case = ScoutEvalCase(
        case_id="short",
        intent="short result set",
        ranked_candidate_ids=("a", "b"),
        judgments=(ScoutJudgment("a", 1), ScoutJudgment("b", 1)),
        paid_reads=10,
        latency_ms=100.0,
    )

    metrics = evaluate_case(case, k=10)

    assert metrics.precision_at_k == 0.2
    assert metrics.recall_at_k == 1.0
    assert metrics.ndcg_at_k == 1.0


def test_evaluate_benchmark_aggregates_cost_and_p95_latency() -> None:
    benchmark = ScoutBenchmark(
        k=2,
        cases=(
            ScoutEvalCase(
                case_id="one",
                intent="one",
                ranked_candidate_ids=("a", "b"),
                judgments=(ScoutJudgment("a", 1), ScoutJudgment("b", 0)),
                paid_reads=10,
                latency_ms=100.0,
            ),
            ScoutEvalCase(
                case_id="two",
                intent="two",
                ranked_candidate_ids=("c", "d"),
                judgments=(ScoutJudgment("c", 1), ScoutJudgment("d", 1)),
                paid_reads=20,
                latency_ms=300.0,
            ),
        ),
    )

    summary = evaluate_benchmark(benchmark)

    assert summary.case_count == 2
    assert summary.mean_precision_at_k == 0.75
    assert summary.mean_recall_at_k == 1.0
    assert summary.mean_ndcg_at_k == 1.0
    assert summary.total_paid_reads == 30
    assert summary.total_relevant_retrieved == 3
    assert summary.relevant_per_paid_read == 0.1
    assert summary.mean_latency_ms == 200.0
    assert summary.p95_latency_ms == 300.0


def test_load_benchmark_uses_versioned_offline_schema(tmp_path: Path) -> None:
    path = tmp_path / "benchmark.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "k": 10,
                "cases": [
                    {
                        "id": "night-bangkok-ru",
                        "intent": "Найди видео про ночной Бангкок",
                        "ranked_candidate_ids": ["x-1", "x-2"],
                        "judgments": {"x-1": 3, "x-2": 0, "x-3": 2},
                        "paid_reads": 30,
                        "latency_ms": 950.25,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    benchmark = load_benchmark(path)
    summary = evaluate_benchmark(benchmark)
    payload = summary_as_dict(summary)

    assert benchmark.k == 10
    assert benchmark.cases[0].intent == "Найди видео про ночной Бангкок"
    assert payload["case_count"] == 1
    assert payload["total_paid_reads"] == 30
    assert payload["cases"] == [
        {
            "case_id": "night-bangkok-ru",
            "precision_at_k": 0.1,
            "recall_at_k": 0.5,
            "ndcg_at_k": pytest.approx(0.787155, abs=1e-6),
            "paid_reads": 30,
            "relevant_retrieved": 1,
            "relevant_per_paid_read": pytest.approx(1 / 30, abs=1e-6),
            "latency_ms": 950.25,
            "retrieved_count": 2,
            "judged_relevant_count": 2,
        }
    ]


def test_benchmark_rejects_duplicate_ranked_ids() -> None:
    with pytest.raises(ValueError, match="ranked_candidate_ids must be unique"):
        ScoutEvalCase(
            case_id="duplicate",
            intent="duplicate",
            ranked_candidate_ids=("a", "a"),
            judgments=(ScoutJudgment("a", 1),),
            paid_reads=10,
            latency_ms=1.0,
        )


def test_judgments_use_bounded_graded_relevance() -> None:
    with pytest.raises(ValueError, match="between 0 and 3"):
        ScoutJudgment("a", 4)
