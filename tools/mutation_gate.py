"""Fail CI when mutmut's conservative mutation score is below policy."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def mutation_score(stats: dict[str, int]) -> float:
    total = int(stats.get("total", 0)) - int(stats.get("skipped", 0))
    return 100.0 if total <= 0 else 100.0 * int(stats.get("killed", 0)) / total


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", nargs="?", type=Path, default=Path("mutants/mutmut-cicd-stats.json"))
    parser.add_argument("--minimum", type=float, default=80.0)
    arguments = parser.parse_args()
    stats = json.loads(arguments.report.read_text(encoding="utf-8"))
    score = mutation_score(stats)
    print(f"Mutation score: {score:.1f}% ({stats})")
    if score + 1e-9 < arguments.minimum:
        raise SystemExit(f"Mutation score {score:.1f}% is below {arguments.minimum:.1f}%")


if __name__ == "__main__":
    main()
