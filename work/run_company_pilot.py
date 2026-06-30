from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_PACKAGE_FILES = [
    "project_dashboard.md",
    "takeoff_items.csv",
    "estimator_review.csv",
    "accubid_mapping.csv",
    "marked_up_drawings.pdf",
    "validation_answer_key_template.csv",
]


def _run(cmd: list[str]) -> tuple[bool, str]:
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), text=True, capture_output=True)
    output = "\n".join(part for part in [proc.stdout, proc.stderr] if part)
    return proc.returncode == 0, output.strip()


def _is_inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def company_data_warnings(project_dir: Path, out_dir: Path) -> list[str]:
    warnings: list[str] = []
    repo_root = REPO_ROOT.resolve()
    risky_parts = {"samples", "outputs"}
    for path, label in [(project_dir, "project-dir"), (out_dir, "out-dir")]:
        resolved = path.resolve()
        inside_repo = _is_inside(resolved, repo_root)
        if inside_repo:
            warnings.append(f"WARNING: {label} is inside the Git repo. Company pilot data should stay outside the Git repo.")
        if inside_repo and any(part.lower() in risky_parts for part in resolved.parts):
            warnings.append(f"WARNING: {label} appears to use a samples/outputs-style path. Company pilot data should stay outside public demo folders.")
    return warnings


def _read_validation_counts(validation_csv: Path) -> dict[str, int]:
    counts = {"MATCH": 0, "MISMATCH": 0, "AI_MISSING": 0, "ESTIMATOR_MISSING": 0}
    if not validation_csv.exists():
        return counts
    with validation_csv.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            status = (row.get("status") or "").upper()
            counts[status] = counts.get(status, 0) + 1
    return counts


def run_company_pilot(project_dir: Path, out_dir: Path) -> tuple[bool, Path, list[str]]:
    messages = company_data_warnings(project_dir, out_dir)
    input_dir = project_dir / "input"
    answer_key = project_dir / "answer_key" / "validation_answer_key.csv"
    summary = out_dir / "pilot_summary.md"

    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        messages.append(f"ERROR: could not create output folder {out_dir}: {exc}")
        return False, summary, messages
    if not input_dir.exists() or not input_dir.is_dir():
        messages.append(f"ERROR: missing input folder: {input_dir}")
        _write_summary(summary, project_dir, input_dir, answer_key, False, False, messages, {})
        return False, summary, messages

    estimate_ok, estimate_output = _run(
        [
            sys.executable,
            "work/estimating_agent_cli.py",
            "estimate-project",
            "--project-folder",
            str(input_dir),
            "--out-dir",
            str(out_dir),
            "--project-name",
            project_dir.name,
        ]
    )
    messages.append("estimate-project completed" if estimate_ok else "estimate-project failed")
    if estimate_output:
        messages.append(estimate_output[:1200])

    validation_ok = False
    validation_counts: dict[str, int] = {}
    if estimate_ok and answer_key.exists():
        validation_dir = out_dir / "validation"
        validation_ok, validation_output = _run(
            [
                sys.executable,
                "work/estimating_agent_cli.py",
                "validate-detections-csv",
                "--detections",
                str(out_dir / "takeoff_items.csv"),
                "--answer-key",
                str(answer_key),
                "--out-dir",
                str(validation_dir),
            ]
        )
        messages.append("validation completed" if validation_ok else "validation failed")
        if validation_output:
            messages.append(validation_output[:1200])
        validation_counts = _read_validation_counts(validation_dir / "symbol_detection_validation.csv")
    elif estimate_ok:
        messages.append(f"No answer key found at {answer_key}; validation skipped.")

    _write_summary(summary, project_dir, input_dir, answer_key, estimate_ok, validation_ok, messages, validation_counts)
    return estimate_ok, summary, messages


def _write_summary(
    summary: Path,
    project_dir: Path,
    input_dir: Path,
    answer_key: Path,
    estimate_ok: bool,
    validation_ok: bool,
    messages: list[str],
    validation_counts: dict[str, int],
) -> None:
    summary.parent.mkdir(parents=True, exist_ok=True)
    with summary.open("w", encoding="utf-8") as handle:
        handle.write("# Company pilot summary\n\n")
        handle.write("This is a private local pilot summary. Do not commit company drawings, exports, reviewed takeoffs, or real marked drawings.\n\n")
        handle.write("## Scope\n\n")
        handle.write(f"- Project folder: `{project_dir}`\n")
        handle.write(f"- Input folder used for estimate-project: `{input_dir}`\n")
        handle.write(f"- Answer key checked after estimate-project: `{answer_key}`\n")
        handle.write("- Reviewed files are for validation after the first-pass estimate is generated. They are not used during detection.\n\n")
        handle.write("## Status\n\n")
        handle.write(f"- estimate-project: {'passed' if estimate_ok else 'failed'}\n")
        handle.write(f"- validation: {'passed' if validation_ok else 'not run or failed'}\n\n")
        handle.write("## Expected estimator package files\n\n")
        for name in REQUIRED_PACKAGE_FILES:
            status = "exists" if (summary.parent / name).exists() else "missing"
            handle.write(f"- {name}: {status}\n")
        handle.write("\n")
        if validation_counts:
            handle.write("## Validation row status\n\n")
            for status, qty in sorted(validation_counts.items()):
                handle.write(f"- {status}: {qty}\n")
            handle.write("\n")
        handle.write("## Notes and warnings\n\n")
        for message in messages:
            handle.write(f"- {message}\n")
        handle.write("\n## Reminder\n\n")
        handle.write("This output is first-pass estimator review output, not final bid output and not pricing. Compare against reviewed takeoff before relying on quantities.\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a private company pilot project without committing company files.")
    parser.add_argument("--project-dir", type=Path, required=True, help="Private project folder containing input/ and optional answer_key/.")
    parser.add_argument("--out-dir", type=Path, required=True, help="Private output folder outside the Git repo.")
    args = parser.parse_args()

    ok, summary, messages = run_company_pilot(args.project_dir, args.out_dir)
    for message in messages:
        print(message)
    print(summary)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
