# Scout evaluation benchmark

This directory defines the offline evaluation contract for Scout search/ranking work.
It must not call X or any other paid provider. Capture provider output separately, assign
manual relevance judgments, then evaluate the recorded snapshot.

## Metrics

The evaluator reports:

- `Precision@K`: relevant results in the first K divided by K. Missing results are treated
  as non-relevant so short result sets are comparable with full result sets.
- `Recall@K`: relevant results in the first K divided by all manually judged relevant items.
- `nDCG@K`: graded ranking quality using relevance grades 0-3.
- `paid_reads`: recorded provider reads for the search run.
- `relevant_per_paid_read`: all relevant retrieved items divided by paid reads.
- mean and p95 latency in milliseconds.

## Relevance grades

- `0` — irrelevant
- `1` — marginally relevant
- `2` — relevant
- `3` — highly relevant / ideal result

## Benchmark JSON v1

```json
{
  "version": 1,
  "k": 10,
  "cases": [
    {
      "id": "night-bangkok-ru",
      "intent": "Найди видео про ночной Бангкок",
      "ranked_candidate_ids": ["candidate-1", "candidate-2"],
      "judgments": {
        "candidate-1": 3,
        "candidate-2": 0,
        "candidate-3": 2
      },
      "paid_reads": 30,
      "latency_ms": 950.25
    }
  ]
}
```

Judgments may include relevant candidates that were not retrieved. That is required for
meaningful recall measurement.

Run locally with:

```bash
python scripts/evaluate_scout_benchmark.py benchmarks/scout/benchmark.example.json
```

`intents.v1.json` is the stable seed catalog for future recorded regression runs. Changing
that catalog should be deliberate because benchmark history only stays comparable when the
intent set remains stable.
