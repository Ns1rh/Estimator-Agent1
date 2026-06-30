from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from create_demo_project import create_demo_project


@dataclass
class CaseResult:
    seed: int
    completed: bool
    project_dir: Path
    package_dir: Path
    expected_qty: int
    ai_qty: int
    exact_match_rows: int
    mismatched_rows: int
    ai_missing_rows: int
    estimator_missing_rows: int
    quantity_difference: int
    failure_reason: str


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _sum_qty(rows: list[dict[str, str]], names: list[str]) -> int:
    total = 0
    for row in rows:
        for name in names:
            if row.get(name):
                try:
                    total += int(float(row[name]))
                except ValueError:
                    pass
                break
    return total


def _run(cmd: list[str], cwd: Path) -> tuple[bool, str]:
    proc = subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True)
    output = "\n".join(part for part in [proc.stdout, proc.stderr] if part)
    return proc.returncode == 0, output.strip()


def run_case(repo_root: Path, out_dir: Path, seed: int) -> CaseResult:
    project_dir = out_dir / "projects" / f"case_{seed:03d}"
    package_dir = out_dir / "packages" / f"case_{seed:03d}"
    create_demo_project(project_dir, seed=seed)
    answer_key = project_dir / "answer_key" / "fixture_counts.csv"

    estimate_ok, estimate_output = _run(
        [
            sys.executable,
            "work/estimating_agent_cli.py",
            "estimate-project",
            "--project-folder",
            str(project_dir),
            "--out-dir",
            str(package_dir),
        ],
        repo_root,
    )
    if not estimate_ok:
        expected_rows = _read_csv(answer_key)
        return CaseResult(seed, False, project_dir, package_dir, _sum_qty(expected_rows, ["reviewed_quantity"]), 0, 0, 0, 0, 0, 0, estimate_output[:500])

    validation_dir = package_dir / "validation"
    validate_ok, validate_output = _run(
        [
            sys.executable,
            "work/estimating_agent_cli.py",
            "validate-detections-csv",
            "--detections",
            str(package_dir / "takeoff_items.csv"),
            "--answer-key",
            str(answer_key),
            "--out-dir",
            str(validation_dir),
        ],
        repo_root,
    )

    expected_rows = _read_csv(answer_key)
    ai_rows = _read_csv(package_dir / "takeoff_items.csv")
    validation_rows = _read_csv(validation_dir / "symbol_detection_validation.csv")
    exact = sum(1 for row in validation_rows if row.get("status") == "MATCH")
    mismatch = sum(1 for row in validation_rows if row.get("status") == "MISMATCH")
    ai_missing = sum(1 for row in validation_rows if row.get("status") == "AI_MISSING")
    estimator_missing = sum(1 for row in validation_rows if row.get("status") == "ESTIMATOR_MISSING")
    expected_qty = _sum_qty(expected_rows, ["reviewed_quantity"])
    ai_qty = _sum_qty(ai_rows, ["quantity"])
    failure = "" if validate_ok else validate_output[:500]
    return CaseResult(seed, validate_ok, project_dir, package_dir, expected_qty, ai_qty, exact, mismatch, ai_missing, estimator_missing, ai_qty - expected_qty, failure)


def write_summary(results: list[CaseResult], out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    summary_csv = out_dir / "summary.csv"
    summary_md = out_dir / "summary.md"

    with summary_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["seed", "completed", "expected_qty", "ai_qty", "quantity_difference", "exact_match_rows", "mismatched_rows", "ai_missing_rows", "estimator_missing_rows", "package_dir", "failure_reason"])
        for result in results:
            writer.writerow([result.seed, result.completed, result.expected_qty, result.ai_qty, result.quantity_difference, result.exact_match_rows, result.mismatched_rows, result.ai_missing_rows, result.estimator_missing_rows, result.package_dir, result.failure_reason])

    completed = sum(1 for result in results if result.completed)
    total_expected = sum(result.expected_qty for result in results)
    total_ai = sum(result.ai_qty for result in results)
    total_exact = sum(result.exact_match_rows for result in results)
    total_mismatch = sum(result.mismatched_rows for result in results)
    total_ai_missing = sum(result.ai_missing_rows for result in results)
    total_estimator_missing = sum(result.estimator_missing_rows for result in results)
    pct_diff = ((total_ai - total_expected) / total_expected) if total_expected else 0

    with summary_md.open("w", encoding="utf-8") as handle:
        handle.write("# Randomized light fixture capability check\n\n")
        handle.write("This is a development-only capability check using safe synthetic projects. It is not final bid output.\n\n")
        handle.write("## Summary\n\n")
        handle.write(f"- Cases run: {len(results)}\n")
        handle.write(f"- Cases completed without crashing: {completed}\n")
        handle.write(f"- Total expected fixture quantity: {total_expected}\n")
        handle.write(f"- Total AI fixture quantity: {total_ai}\n")
        handle.write(f"- Quantity difference: {total_ai - total_expected:+}\n")
        handle.write(f"- Percent difference: {pct_diff:.2%}\n")
        handle.write(f"- Exact match rows: {total_exact}\n")
        handle.write(f"- Mismatched rows: {total_mismatch}\n")
        handle.write(f"- Missing AI rows: {total_ai_missing}\n")
        handle.write(f"- Extra AI rows: {total_estimator_missing}\n\n")
        handle.write("## Cases\n\n")
        for result in results:
            status = "completed" if result.completed else "failed"
            handle.write(f"- Seed {result.seed}: {status}; expected {result.expected_qty}; AI {result.ai_qty}; diff {result.quantity_difference:+}; package `{result.package_dir}`\n")
            if result.failure_reason:
                handle.write(f"  - Failure: {result.failure_reason}\n")
        handle.write("\n## Reminder\n\n")
        handle.write("The normal estimator package still requires estimator review. Synthetic capability scores do not prove production accuracy on real drawings.\n")
    return summary_md, summary_csv


def main() -> None:
    parser = argparse.ArgumentParser(description="Run randomized safe synthetic estimator-agent capability checks.")
    parser.add_argument("--cases", type=int, default=5)
    parser.add_argument("--out-dir", type=Path, default=Path("outputs/capability-check"))
    parser.add_argument("--start-seed", type=int, default=1)
    args = parser.parse_args()

    repo_root = Path.cwd()
    results = [run_case(repo_root, args.out_dir, seed) for seed in range(args.start_seed, args.start_seed + args.cases)]
    summary_md, summary_csv = write_summary(results, args.out_dir)
    print(summary_md)
    print(summary_csv)


if __name__ == "__main__":
    main()
