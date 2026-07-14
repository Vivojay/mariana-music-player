"""Enforce branch-coverage thresholds for release-critical modules.

Coverage.py's aggregate percentage combines statements and branches.  Mariana's
release policy is stricter: every listed critical module must independently
meet the configured *branch* threshold.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

DEFAULT_MODULES = (
    "mariana/albums.py",
    "mariana/broadcast.py",
    "mariana/credentials.py",
    "mariana/database.py",
    "mariana/download_jobs.py",
    "mariana/library.py",
    "mariana/library_service.py",
    "mariana/loudness.py",
    "mariana/media_removal.py",
    "mariana/output_devices.py",
    "mariana/paths.py",
    "mariana/playback.py",
    "mariana/playlists.py",
    "mariana/preferences.py",
    "mariana/queueing.py",
    "mariana/setup.py",
    "mariana/sleep_timer.py",
    "mariana/sources.py",
    "mariana/station.py",
    "mariana/station_discovery.py",
    "mariana/supervisor.py",
    "mariana/user_state.py",
)


def branch_percentage(summary: dict[str, int]) -> float:
    """Return branch coverage, treating branch-free modules as fully covered."""
    branches = int(summary.get("num_branches", 0))
    if branches == 0:
        return 100.0
    return 100.0 * int(summary.get("covered_branches", 0)) / branches


def evaluate(
    report: dict,
    modules: tuple[str, ...],
    minimum: float,
) -> tuple[list[str], list[str]]:
    """Return human-readable result lines and failures."""
    files = {name.replace("\\", "/"): value for name, value in report.get("files", {}).items()}
    lines: list[str] = []
    failures: list[str] = []
    for module in modules:
        normalized = module.replace("\\", "/")
        entry = files.get(normalized)
        if entry is None:
            message = f"{normalized}: absent from coverage report"
            lines.append(message)
            failures.append(message)
            continue
        percentage = branch_percentage(entry.get("summary", {}))
        message = f"{normalized}: {percentage:.1f}% branch coverage"
        lines.append(message)
        if percentage + 1e-9 < minimum:
            failures.append(f"{message} (requires {minimum:.1f}%)")
    return lines, failures


def evaluate_repository(report: dict, minimum: float) -> tuple[str, str | None]:
    """Evaluate the repository-wide branch total independently of statements."""
    percentage = branch_percentage(report.get("totals", {}))
    message = f"repository: {percentage:.1f}% branch coverage"
    if percentage + 1e-9 < minimum:
        return message, f"{message} (requires {minimum:.1f}%)"
    return message, None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", nargs="?", type=Path, default=Path("coverage.json"))
    parser.add_argument("--minimum", type=float, default=95.0)
    parser.add_argument("--repository-minimum", type=float)
    parser.add_argument("--module", action="append", dest="modules")
    arguments = parser.parse_args()
    report = json.loads(arguments.report.read_text(encoding="utf-8"))
    modules = tuple(arguments.modules or DEFAULT_MODULES)
    lines, failures = evaluate(report, modules, arguments.minimum)
    if arguments.repository_minimum is not None:
        repository_line, repository_failure = evaluate_repository(report, arguments.repository_minimum)
        lines.insert(0, repository_line)
        if repository_failure:
            failures.insert(0, repository_failure)
    print("\n".join(lines))
    if failures:
        raise SystemExit("Critical branch-coverage gate failed:\n- " + "\n- ".join(failures))


if __name__ == "__main__":
    main()
