#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

from vimi_social.source.evaluation import evaluate_benchmark, load_benchmark, summary_as_dict


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate a recorded ViMi Scout benchmark without provider calls."
    )
    parser.add_argument("benchmark", type=Path, help="Path to a version-1 Scout benchmark JSON file")
    args = parser.parse_args()

    benchmark = load_benchmark(args.benchmark)
    summary = evaluate_benchmark(benchmark)
    print(json.dumps(summary_as_dict(summary), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
