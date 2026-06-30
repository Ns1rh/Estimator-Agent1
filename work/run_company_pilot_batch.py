from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

from run_company_pilot import company_data_warnings, run_company_pilot


def _read_validation_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _project_dirs(projects_root: Path) -> list[Path]:
    if not projects_root.exists():
        return []
    return sorted(path for path in projects_root.iterdir() if path.is_dir() and (path / "input").exists())


def run_batch(projects_root: Path, out_dir: Path) -> tuple[bool, Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    projects = _project_dirs(projects_root)
    summary_csv = out_dir / "summary.csv"
    summary_md = out_dir / "summary.md"
    rows: list[dict[str, str]] = []
    status_totals: Counter[str] = Counter()
    category_totals: Counter[tuple[str, str]] = Counter()
    warnings = company_data_warnings(projects_root, out_dir)

    for project_dir in projects:
        project_out = out_dir / project_dir.name
        ok, pilot_summary, _messages = run_company_pilot(project_dir, project_out)
        validation_rows = _read_validation_rows(project_out / "validation" / "symbol_detection_validation.csv")
        status_counts: Counter[str] = Counter((row.get("status") or "").upper() for row in validation_rows)
        for status, qty in status_counts.items():
            status_totals[status] += qty
        for row in validation_rows:
            category = row.get("category") or "unknown"
            status = (row.get("status") or "UNKNOWN").upper()
            category_totals[(category, status)] += 1
        rows.append(
            {
                "project_id": project_dir.name,
                "completed": str(ok),
                "answer_key_found": str((project_dir / "answer_key" / "validation_answer_key.csv").exists()),
                "match_rows": str(status_counts.get("MATCH", 0)),
                "mismatch_rows": str(status_counts.get("MISMATCH", 0)),
                "missing_ai_rows": str(status_counts.get("AI_MISSING", 0)),
                "extra_ai_rows": str(status_counts.get("ESTIMATOR_MISSING", 0)),
                "output_dir": str(project_out),
                "pilot_summary": str(pilot_summary),
            }
        )

    with summary_csv.open("w", newline="", encoding="utf-8") as handle:
        fieldnames = ["project_id", "completed", "answer_key_found", "match_rows", "mismatch_rows", "missing_ai_rows", "extra_ai_rows", "output_dir", "pilot_summary"]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    with summary_md.open("w", encoding="utf-8") as handle:
        handle.write("# Company pilot batch summary\n\n")
        handle.write("This summary is for private local validation only. Do not commit company files or pilot outputs.\n\n")
        handle.write(f"- Projects root: `{projects_root}`\n")
        handle.write(f"- Projects with input folders found: {len(projects)}\n")
        handle.write(f"- Projects completed: {sum(1 for row in rows if row['completed'] == 'True')}\n\n")
        if warnings:
            handle.write("## Warnings\n\n")
            for warning in warnings:
                handle.write(f"- {warning}\n")
            handle.write("\n")
        handle.write("## Validation status totals\n\n")
        if status_totals:
            for status, qty in sorted(status_totals.items()):
                handle.write(f"- {status}: {qty}\n")
        else:
            handle.write("- No validation rows found. Add answer_key\\validation_answer_key.csv files to validate completed projects.\n")
        handle.write("\n## Category/status breakdown\n\n")
        if category_totals:
            for (category, status), qty in sorted(category_totals.items()):
                handle.write(f"- {category} / {status}: {qty}\n")
        else:
            handle.write("- No category validation rows found.\n")
        handle.write("\n## Project outputs\n\n")
        for row in rows:
            handle.write(f"- {row['project_id']}: completed={row['completed']}, output=`{row['output_dir']}`\n")
        handle.write("\n## Reminder\n\n")
        handle.write("Company pilot results are local validation aids. They are not final bid output, not pricing, and not a replacement for estimator review.\n")

    return bool(projects), summary_md, summary_csv


def main() -> int:
    parser = argparse.ArgumentParser(description="Run private company pilot validation across multiple completed projects.")
    parser.add_argument("--projects-root", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    found, summary_md, summary_csv = run_batch(args.projects_root, args.out_dir)
    print(summary_md)
    print(summary_csv)
    if not found:
        print(f"No project folders with input/ found under {args.projects_root}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
