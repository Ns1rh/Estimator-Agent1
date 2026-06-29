from __future__ import annotations

import csv
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .livecount_tpx import documents_from_text, fixture_counts_by_page, points_from_text, read_text


PROJECT_NUMBER = re.compile(r"\b20\d{4}\b|\bEST\d+\b", re.IGNORECASE)
BAD_PATH_PARTS = {
    "billing",
    "coi",
    "contract",
    "tax exemption",
    "waivers",
    "payapps",
    "invoices",
}


@dataclass(frozen=True)
class ProjectScanResult:
    project_name: str
    project_path: str
    latest_tpx: str = ""
    tpx_count: int = 0
    pdf_count: int = 0
    accubid_count: int = 0
    fixture_sheets: int = 0
    fixture_points: int = 0
    fixture_types: int = 0
    document_count: int = 0
    likely_mismatch: bool = False
    grade: str = "missing_tpx"
    notes: str = ""


def is_noise_path(path: Path) -> bool:
    return any(part.lower() in BAD_PATH_PARTS for part in path.parts)


def project_tokens(project_name: str) -> set[str]:
    tokens = {token.lower() for token in re.findall(r"[A-Za-z0-9]+", project_name)}
    return {token for token in tokens if len(token) >= 4}


def document_mismatch(project_name: str, document_labels: list[str]) -> bool:
    project_numbers = {match.group(0).lower() for match in PROJECT_NUMBER.finditer(project_name)}
    document_numbers = {
        match.group(0).lower()
        for label in document_labels[:30]
        for match in PROJECT_NUMBER.finditer(label)
    }
    if project_numbers and document_numbers and document_numbers.isdisjoint(project_numbers):
        return True

    tokens = project_tokens(project_name)
    if not tokens or not document_labels:
        return False
    checked = 0
    mismatches = 0
    for label in document_labels[:20]:
        text = label.lower()
        if not text.strip():
            continue
        checked += 1
        if not any(token in text for token in tokens):
            mismatches += 1
    return checked >= 8 and mismatches / checked >= 0.90


def grade_project(
    has_tpx: bool,
    fixture_points: int,
    pdf_count: int,
    likely_mismatch: bool,
) -> tuple[str, str]:
    if not has_tpx:
        return "missing_tpx", "No LiveCount TPX export found."
    if likely_mismatch:
        return "mismatch", "TPX document names do not appear to match the project folder."
    if fixture_points >= 100 and pdf_count > 0:
        return "good_training_candidate", "Large enough TPX fixture dataset with PDFs present."
    if fixture_points >= 20:
        return "usable_small", "Usable TPX fixture data, but smaller than ideal."
    if fixture_points > 0:
        return "tiny_scope", "TPX has fixture data, but scope is too small for strong training."
    return "no_fixture_layer", "TPX found, but no FIXTURES layer points were detected."


def scan_project(project_dir: Path, max_files: int = 5000) -> ProjectScanResult:
    files: list[Path] = []
    try:
        for index, path in enumerate(project_dir.rglob("*")):
            if index >= max_files:
                break
            if path.is_file() and not is_noise_path(path):
                files.append(path)
    except OSError as exc:
        return ProjectScanResult(
            project_name=project_dir.name,
            project_path=str(project_dir),
            grade="scan_error",
            notes=f"Scan error: {exc}",
        )

    tpx_files = sorted(
        [path for path in files if path.suffix.lower() == ".tpx"],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    pdf_count = sum(1 for path in files if path.suffix.lower() == ".pdf")
    accubid_count = sum(1 for path in files if re.fullmatch(r"\.es\d+", path.suffix.lower()))

    if not tpx_files:
        grade, notes = grade_project(False, 0, pdf_count, False)
        return ProjectScanResult(
            project_name=project_dir.name,
            project_path=str(project_dir),
            pdf_count=pdf_count,
            accubid_count=accubid_count,
            grade=grade,
            notes=notes,
        )

    latest_tpx = tpx_files[0]
    try:
        text = read_text(latest_tpx)
        documents = documents_from_text(text)
        points = points_from_text(text)
        fixture_counts = fixture_counts_by_page(points)
        fixture_points = sum(sum(counter.values()) for counter in fixture_counts.values())
        fixture_types = len({name for counter in fixture_counts.values() for name in counter})
        likely_mismatch = document_mismatch(
            project_dir.name,
            [f"{document.description} {document.relative_path}" for document in documents],
        )
        grade, notes = grade_project(True, fixture_points, pdf_count, likely_mismatch)
        return ProjectScanResult(
            project_name=project_dir.name,
            project_path=str(project_dir),
            latest_tpx=str(latest_tpx),
            tpx_count=len(tpx_files),
            pdf_count=pdf_count,
            accubid_count=accubid_count,
            fixture_sheets=len(fixture_counts),
            fixture_points=fixture_points,
            fixture_types=fixture_types,
            document_count=len(documents),
            likely_mismatch=likely_mismatch,
            grade=grade,
            notes=notes,
        )
    except Exception as exc:  # noqa: BLE001 - scanner should continue through bad projects.
        return ProjectScanResult(
            project_name=project_dir.name,
            project_path=str(project_dir),
            latest_tpx=str(latest_tpx),
            tpx_count=len(tpx_files),
            pdf_count=pdf_count,
            accubid_count=accubid_count,
            grade="parse_error",
            notes=f"TPX parse error: {exc}",
        )


def project_dirs(root: Path, limit: int | None = None) -> list[Path]:
    dirs = []
    for path in sorted(root.iterdir(), key=lambda item: item.name.lower()):
        if path.is_dir():
            dirs.append(path)
            if limit is not None and len(dirs) >= limit:
                break
    return dirs


def write_scan_outputs(results: list[ProjectScanResult], out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "project_scan.csv"
    md_path = out_dir / "project_scan_summary.md"
    fieldnames = list(ProjectScanResult.__dataclass_fields__)
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for result in results:
            writer.writerow(result.__dict__)

    grade_counts = Counter(result.grade for result in results)
    ranked = sorted(
        results,
        key=lambda result: (
            result.grade != "good_training_candidate",
            -result.fixture_points,
            result.project_name,
        ),
    )
    with md_path.open("w", encoding="utf-8") as handle:
        handle.write("# Estimating agent project database scan\n\n")
        handle.write("## Summary\n\n")
        handle.write(f"- Projects scanned: {len(results)}\n")
        for grade, count in sorted(grade_counts.items()):
            handle.write(f"- {grade}: {count}\n")
        handle.write("\n## Best training candidates\n\n")
        handle.write("| Grade | Project | Fixture points | Fixture sheets | PDFs | TPX exports | Notes |\n")
        handle.write("|---|---|---:|---:|---:|---:|---|\n")
        for result in ranked[:30]:
            handle.write(
                f"| {result.grade} | {result.project_name} | {result.fixture_points} | "
                f"{result.fixture_sheets} | {result.pdf_count} | {result.tpx_count} | {result.notes} |\n"
            )
        handle.write("\n## Recommended next action\n\n")
        handle.write(
            "Use `good_training_candidate` projects first. Review `mismatch` projects as data-quality issues, "
            "not training data. Use `tiny_scope` projects only as smoke tests.\n"
        )
    return csv_path, md_path
