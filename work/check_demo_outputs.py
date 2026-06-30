from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path


REQUIRED_FILES = [
    "project_dashboard.md",
    "takeoff_items.csv",
    "estimator_review.csv",
    "accubid_mapping.csv",
    "marked_up_drawings.pdf",
    "validation_answer_key_template.csv",
]

REQUIRED_NONEMPTY_CSVS = [
    "takeoff_items.csv",
    "estimator_review.csv",
    "accubid_mapping.csv",
]


def _csv_has_data(path: Path) -> bool:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.reader(handle))
    return len(rows) >= 2


def check_outputs(out_dir: Path) -> tuple[bool, list[str]]:
    messages: list[str] = []
    ok = True

    for name in REQUIRED_FILES:
        path = out_dir / name
        if path.exists() and path.is_file():
            messages.append(f"PASS required file exists: {name}")
        else:
            ok = False
            messages.append(f"FAIL missing required file: {name}")

    for name in REQUIRED_NONEMPTY_CSVS:
        path = out_dir / name
        if not path.exists():
            continue
        if _csv_has_data(path):
            messages.append(f"PASS CSV has data rows: {name}")
        else:
            ok = False
            messages.append(f"FAIL CSV has no data rows: {name}")

    marked_pdf = out_dir / "marked_up_drawings.pdf"
    if marked_pdf.exists() and marked_pdf.stat().st_size > 0:
        messages.append("PASS marked_up_drawings.pdf is present and non-empty")
    elif marked_pdf.exists():
        ok = False
        messages.append("FAIL marked_up_drawings.pdf exists but is empty")

    dashboard = out_dir / "project_dashboard.md"
    if dashboard.exists() and "first-pass estimator review" in dashboard.read_text(encoding="utf-8").lower():
        messages.append("PASS dashboard states first-pass estimator review purpose")
    elif dashboard.exists():
        ok = False
        messages.append("FAIL dashboard does not clearly state first-pass estimator review purpose")

    return ok, messages


def main() -> int:
    parser = argparse.ArgumentParser(description="Check that the demo estimator package has the expected presentation files.")
    parser.add_argument("--out-dir", type=Path, required=True, help="Estimator package output folder to check.")
    args = parser.parse_args()

    ok, messages = check_outputs(args.out_dir)
    for message in messages:
        print(message)
    print("PASS demo output health check" if ok else "FAIL demo output health check")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
