import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast


@dataclass(frozen=True, slots=True)
class ScoutJudgment:
    candidate_id: str
    relevance: int

    def __post_init__(self) -> None:
        if not self.candidate_id.strip():
            raise ValueError("candidate_id must not be empty")
        if isinstance(self.relevance, bool) or not 0 <= self.relevance <= 3:
            raise ValueError("relevance must be an integer between 0 and 3")


@dataclass(frozen=True, slots=True)
class ScoutEvalCase:
    case_id: str
    intent: str
    ranked_candidate_ids: tuple[str, ...]
    judgments: tuple[ScoutJudgment, ...]
    paid_reads: int
    latency_ms: float

    def __post_init__(self) -> None:
        if not self.case_id.strip():
            raise ValueError("case_id must not be empty")
        if not self.intent.strip():
            raise ValueError("intent must not be empty")
        if len(set(self.ranked_candidate_ids)) != len(self.ranked_candidate_ids):
            raise ValueError("ranked_candidate_ids must be unique")
        if any(not candidate_id.strip() for candidate_id in self.ranked_candidate_ids):
            raise ValueError("ranked_candidate_ids must not contain empty ids")
        judgment_ids = tuple(judgment.candidate_id for judgment in self.judgments)
        if len(set(judgment_ids)) != len(judgment_ids):
            raise ValueError("judgment candidate ids must be unique")
        if isinstance(self.paid_reads, bool) or self.paid_reads < 0:
            raise ValueError("paid_reads must be a non-negative integer")
        if self.latency_ms < 0:
            raise ValueError("latency_ms must be non-negative")


@dataclass(frozen=True, slots=True)
class ScoutBenchmark:
    k: int
    cases: tuple[ScoutEvalCase, ...]

    def __post_init__(self) -> None:
        if isinstance(self.k, bool) or self.k < 1:
            raise ValueError("k must be a positive integer")
        case_ids = tuple(case.case_id for case in self.cases)
        if len(set(case_ids)) != len(case_ids):
            raise ValueError("benchmark case ids must be unique")


@dataclass(frozen=True, slots=True)
class ScoutEvalMetrics:
    case_id: str
    precision_at_k: float
    recall_at_k: float
    ndcg_at_k: float
    paid_reads: int
    relevant_retrieved: int
    relevant_per_paid_read: float
    latency_ms: float
    retrieved_count: int
    judged_relevant_count: int


@dataclass(frozen=True, slots=True)
class ScoutEvalSummary:
    k: int
    case_count: int
    mean_precision_at_k: float
    mean_recall_at_k: float
    mean_ndcg_at_k: float
    total_paid_reads: int
    total_relevant_retrieved: int
    relevant_per_paid_read: float
    mean_latency_ms: float
    p95_latency_ms: float
    cases: tuple[ScoutEvalMetrics, ...]


def evaluate_case(case: ScoutEvalCase, *, k: int) -> ScoutEvalMetrics:
    if isinstance(k, bool) or k < 1:
        raise ValueError("k must be a positive integer")

    judgments = {judgment.candidate_id: judgment.relevance for judgment in case.judgments}
    top_k = case.ranked_candidate_ids[:k]
    relevant_at_k = sum(1 for candidate_id in top_k if judgments.get(candidate_id, 0) > 0)
    total_relevant = sum(1 for relevance in judgments.values() if relevance > 0)
    relevant_retrieved = sum(
        1 for candidate_id in case.ranked_candidate_ids if judgments.get(candidate_id, 0) > 0
    )

    precision = relevant_at_k / k
    recall = relevant_at_k / total_relevant if total_relevant else 0.0
    ndcg = _ndcg_at_k(case.ranked_candidate_ids, judgments, k)
    relevant_per_paid_read = relevant_retrieved / case.paid_reads if case.paid_reads else 0.0

    return ScoutEvalMetrics(
        case_id=case.case_id,
        precision_at_k=round(precision, 6),
        recall_at_k=round(recall, 6),
        ndcg_at_k=round(ndcg, 6),
        paid_reads=case.paid_reads,
        relevant_retrieved=relevant_retrieved,
        relevant_per_paid_read=round(relevant_per_paid_read, 6),
        latency_ms=round(case.latency_ms, 3),
        retrieved_count=len(case.ranked_candidate_ids),
        judged_relevant_count=total_relevant,
    )


def evaluate_benchmark(benchmark: ScoutBenchmark) -> ScoutEvalSummary:
    metrics = tuple(evaluate_case(case, k=benchmark.k) for case in benchmark.cases)
    case_count = len(metrics)
    if not metrics:
        return ScoutEvalSummary(
            k=benchmark.k,
            case_count=0,
            mean_precision_at_k=0.0,
            mean_recall_at_k=0.0,
            mean_ndcg_at_k=0.0,
            total_paid_reads=0,
            total_relevant_retrieved=0,
            relevant_per_paid_read=0.0,
            mean_latency_ms=0.0,
            p95_latency_ms=0.0,
            cases=(),
        )

    total_paid_reads = sum(metric.paid_reads for metric in metrics)
    total_relevant_retrieved = sum(metric.relevant_retrieved for metric in metrics)
    latencies = tuple(sorted(metric.latency_ms for metric in metrics))

    return ScoutEvalSummary(
        k=benchmark.k,
        case_count=case_count,
        mean_precision_at_k=round(
            sum(metric.precision_at_k for metric in metrics) / case_count,
            6,
        ),
        mean_recall_at_k=round(
            sum(metric.recall_at_k for metric in metrics) / case_count,
            6,
        ),
        mean_ndcg_at_k=round(
            sum(metric.ndcg_at_k for metric in metrics) / case_count,
            6,
        ),
        total_paid_reads=total_paid_reads,
        total_relevant_retrieved=total_relevant_retrieved,
        relevant_per_paid_read=round(
            total_relevant_retrieved / total_paid_reads if total_paid_reads else 0.0,
            6,
        ),
        mean_latency_ms=round(sum(latencies) / case_count, 3),
        p95_latency_ms=round(_nearest_rank_percentile(latencies, 0.95), 3),
        cases=metrics,
    )


def load_benchmark(path: str | Path) -> ScoutBenchmark:
    with Path(path).open(encoding="utf-8") as handle:
        payload: object = json.load(handle)
    root = _require_mapping(payload, "benchmark")

    version = root.get("version")
    if version != 1:
        raise ValueError("benchmark version must be 1")
    k = _require_int(root.get("k"), "k", minimum=1)
    raw_cases = root.get("cases")
    if not isinstance(raw_cases, list):
        raise ValueError("cases must be a list")

    cases = tuple(_parse_case(raw_case) for raw_case in cast(list[object], raw_cases))
    return ScoutBenchmark(k=k, cases=cases)


def summary_as_dict(summary: ScoutEvalSummary) -> dict[str, object]:
    return {
        "k": summary.k,
        "case_count": summary.case_count,
        "mean_precision_at_k": summary.mean_precision_at_k,
        "mean_recall_at_k": summary.mean_recall_at_k,
        "mean_ndcg_at_k": summary.mean_ndcg_at_k,
        "total_paid_reads": summary.total_paid_reads,
        "total_relevant_retrieved": summary.total_relevant_retrieved,
        "relevant_per_paid_read": summary.relevant_per_paid_read,
        "mean_latency_ms": summary.mean_latency_ms,
        "p95_latency_ms": summary.p95_latency_ms,
        "cases": [
            {
                "case_id": metric.case_id,
                "precision_at_k": metric.precision_at_k,
                "recall_at_k": metric.recall_at_k,
                "ndcg_at_k": metric.ndcg_at_k,
                "paid_reads": metric.paid_reads,
                "relevant_retrieved": metric.relevant_retrieved,
                "relevant_per_paid_read": metric.relevant_per_paid_read,
                "latency_ms": metric.latency_ms,
                "retrieved_count": metric.retrieved_count,
                "judged_relevant_count": metric.judged_relevant_count,
            }
            for metric in summary.cases
        ],
    }


def _ndcg_at_k(
    ranked_candidate_ids: tuple[str, ...],
    judgments: Mapping[str, int],
    k: int,
) -> float:
    observed = tuple(judgments.get(candidate_id, 0) for candidate_id in ranked_candidate_ids[:k])
    ideal = tuple(sorted(judgments.values(), reverse=True)[:k])
    ideal_dcg = _dcg(ideal)
    if ideal_dcg == 0.0:
        return 0.0
    return _dcg(observed) / ideal_dcg


def _dcg(relevances: tuple[int, ...]) -> float:
    return sum(
        ((2**relevance) - 1) / math.log2(rank + 1)
        for rank, relevance in enumerate(relevances, start=1)
    )


def _nearest_rank_percentile(values: tuple[float, ...], percentile: float) -> float:
    if not values:
        return 0.0
    rank = max(1, math.ceil(percentile * len(values)))
    return values[rank - 1]


def _parse_case(value: object) -> ScoutEvalCase:
    raw = _require_mapping(value, "case")
    case_id = _require_str(raw.get("id"), "case.id")
    intent = _require_str(raw.get("intent"), "case.intent")
    ranked_candidate_ids = _require_string_tuple(
        raw.get("ranked_candidate_ids"),
        "case.ranked_candidate_ids",
    )
    paid_reads = _require_int(raw.get("paid_reads"), "case.paid_reads", minimum=0)
    latency_ms = _require_number(raw.get("latency_ms"), "case.latency_ms", minimum=0.0)

    raw_judgments = raw.get("judgments")
    if not isinstance(raw_judgments, dict):
        raise ValueError("case.judgments must be an object")
    judgments: list[ScoutJudgment] = []
    for raw_candidate_id, raw_relevance in cast(dict[object, object], raw_judgments).items():
        if not isinstance(raw_candidate_id, str) or not raw_candidate_id.strip():
            raise ValueError("case.judgments keys must be non-empty strings")
        relevance = _require_int(raw_relevance, "case.judgments relevance", minimum=0, maximum=3)
        judgments.append(ScoutJudgment(candidate_id=raw_candidate_id, relevance=relevance))

    return ScoutEvalCase(
        case_id=case_id,
        intent=intent,
        ranked_candidate_ids=ranked_candidate_ids,
        judgments=tuple(judgments),
        paid_reads=paid_reads,
        latency_ms=latency_ms,
    )


def _require_mapping(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    raw = cast(dict[object, object], value)
    result: dict[str, object] = {}
    for key, item in raw.items():
        if not isinstance(key, str):
            raise ValueError(f"{name} keys must be strings")
        result[key] = item
    return result


def _require_str(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _require_int(
    value: object,
    name: str,
    *,
    minimum: int,
    maximum: int | None = None,
) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    if value < minimum or (maximum is not None and value > maximum):
        if maximum is None:
            raise ValueError(f"{name} must be >= {minimum}")
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _require_number(value: object, name: str, *, minimum: float) -> float:
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise ValueError(f"{name} must be a number")
    result = float(value)
    if result < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return result


def _require_string_tuple(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a list")
    result: list[str] = []
    for item in cast(list[object], value):
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{name} must contain non-empty strings")
        result.append(item.strip())
    return tuple(result)
