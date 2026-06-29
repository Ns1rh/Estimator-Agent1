from __future__ import annotations

import csv
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from .audit import audit_fixture_sheets, write_counts_csv, write_project_audit_report
from .livecount_tpx import read_tpx


SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True)
class TrainingProject:
    project_name: str
    project_path: str
    latest_tpx: str
    grade: str
    fixture_points: int
    fixture_sheets: int
    pdf_count: int
    tpx_count: int


def safe_folder_name(name: str) -> str:
    return SAFE_NAME.sub("_", name).strip("_")[:120]


def read_training_candidates(scan_csv: Path, grades: set[str], limit: int | None) -> list[TrainingProject]:
    rows: list[TrainingProject] = []
    with scan_csv.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            grade = row.get("grade", "")
            if grade not in grades:
                continue
            latest_tpx = row.get("latest_tpx", "")
            if not latest_tpx:
                continue
            rows.append(
                TrainingProject(
                    project_name=row.get("project_name", ""),
                    project_path=row.get("project_path", ""),
                    latest_tpx=latest_tpx,
                    grade=grade,
                    fixture_points=int(float(row.get("fixture_points") or 0)),
                    fixture_sheets=int(float(row.get("fixture_sheets") or 0)),
                    pdf_count=int(float(row.get("pdf_count") or 0)),
                    tpx_count=int(float(row.get("tpx_count") or 0)),
                )
            )
    rows.sort(key=lambda project: project.fixture_points, reverse=True)
    return rows[:limit] if limit is not None else rows


def build_training_set(
    scan_csv: Path,
    out_dir: Path,
    grades: set[str],
    limit: int | None = None,
) -> tuple[Path, Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    projects = read_training_candidates(scan_csv, grades, limit)
    manifest_path = out_dir / "training_manifest.csv"
    vocab_path = out_dir / "fixture_type_vocabulary.csv"
    summary_path = out_dir / "TRAINING_SET_SUMMARY.md"

    global_counts: Counter = Counter()
    project_type_presence: dict[str, set[str]] = defaultdict(set)
    manifest_rows = []

    for index, project in enumerate(projects, 1):
        project_dir = out_dir / f"{index:02d}_{safe_folder_name(project.project_name)}"
        project_dir.mkdir(parents=True, exist_ok=True)
        documents, points = read_tpx(Path(project.latest_tpx))
        sheet_audits = audit_fixture_sheets(documents, points)
        write_project_audit_report(project_dir / "agent_review.md", project.project_name, sheet_audits)

        project_counts = Counter()
        for sheet in sheet_audits:
            project_counts.update(sheet.counts)
        write_counts_csv(project_dir / "fixture_counts.csv", project_counts)

        for fixture_type, count in project_counts.items():
            global_counts[fixture_type] += count
            project_type_presence[fixture_type].add(project.project_name)

        manifest_rows.append(
            {
                "project_name": project.project_name,
                "grade": project.grade,
                "fixture_points": project.fixture_points,
                "fixture_sheets": project.fixture_sheets,
                "fixture_types": len(project_counts),
                "pdf_count": project.pdf_count,
                "tpx_count": project.tpx_count,
                "project_path": project.project_path,
                "latest_tpx": project.latest_tpx,
                "packet_dir": str(project_dir),
            }
        )

    with manifest_path.open("w", newline="", encoding="utf-8") as handle:
        fieldnames = [
            "project_name",
            "grade",
            "fixture_points",
            "fixture_sheets",
            "fixture_types",
            "pdf_count",
            "tpx_count",
            "project_path",
            "latest_tpx",
            "packet_dir",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(manifest_rows)

    with vocab_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["fixture_type", "total_count", "project_count"])
        for fixture_type, total in global_counts.most_common():
            writer.writerow([fixture_type, total, len(project_type_presence[fixture_type])])

    with summary_path.open("w", encoding="utf-8") as handle:
        handle.write("# Estimating agent training set\n\n")
        handle.write("This is the first internal training/evaluation set built from good project candidates.\n\n")
        handle.write("## Summary\n\n")
        handle.write(f"- Projects included: {len(projects)}\n")
        handle.write(f"- Total fixture points: {sum(row['fixture_points'] for row in manifest_rows)}\n")
        handle.write(f"- Unique fixture type labels: {len(global_counts)}\n\n")
        handle.write("## Included projects\n\n")
        handle.write("| Project | Fixture points | Fixture sheets | Fixture types | Packet |\n")
        handle.write("|---|---:|---:|---:|---|\n")
        for row in manifest_rows:
            handle.write(
                f"| {row['project_name']} | {row['fixture_points']} | {row['fixture_sheets']} | "
                f"{row['fixture_types']} | {row['packet_dir']} |\n"
            )
        handle.write("\n## Most common fixture labels\n\n")
        handle.write("| Fixture type | Count | Projects |\n")
        handle.write("|---|---:|---:|\n")
        for fixture_type, total in global_counts.most_common(40):
            handle.write(f"| {fixture_type} | {total} | {len(project_type_presence[fixture_type])} |\n")
        handle.write("\n## How this trains the agent\n\n")
        handle.write("- Builds a fixture-label vocabulary from real company LiveCount data.\n")
        handle.write("- Creates per-project review packets for evaluation.\n")
        handle.write("- Establishes which projects are strong examples before doing deeper drawing/schedule extraction.\n")

    return manifest_path, vocab_path, summary_path
