from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

from work.estimating_agent.audit import audit_fixture_sheets, write_project_audit_report
from work.estimating_agent.livecount_tpx import read_tpx
from work.estimating_agent.project_intake import write_intake_outputs
from work.estimating_agent.project_scan import scan_project
from work.estimating_agent.sheet_map import read_sheet_map


@dataclass(frozen=True)
class WorkerRunResult:
    dashboard: Path
    out_dir: Path


def _safe_name(name: str, fallback: str = "project") -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_")
    return safe or fallback


def _find_latest_file(project_folder: Path, suffix: str) -> Path | None:
    matches = []
    for path in project_folder.rglob(f"*{suffix}"):
        try:
            matches.append((path.stat().st_mtime, path))
        except OSError:
            continue
    if not matches:
        return None
    return sorted(matches, reverse=True)[0][1]


def _read_csv_rows(path: Path, limit: int = 12) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return [row for _, row in zip(range(limit), reader)]


def run_full_worker_mode(project_folder: Path, out_dir: Path, project_name: str | None = None) -> WorkerRunResult:
    out_dir.mkdir(parents=True, exist_ok=True)
    project_name = project_name or project_folder.name

    dashboard = out_dir / "WORKER_DASHBOARD.md"
    manifest = out_dir / "worker_manifest.csv"

    steps: list[tuple[str, str, str]] = []

    # 1) Project database-style scan.
    scan = scan_project(project_folder, max_files=4000)
    scan_report = out_dir / "project_scan_quick_summary.md"
    with scan_report.open("w", encoding="utf-8") as handle:
        handle.write(f"# Quick project scan - {project_name}\n\n")
        handle.write(f"- Folder: `{project_folder}`\n")
        handle.write(f"- Grade: {scan.grade}\n")
        handle.write(f"- TPX files: {scan.tpx_count}\n")
        handle.write(f"- PDF files: {scan.pdf_count}\n")
        handle.write(f"- Accubid-like files: {scan.accubid_count}\n")
        handle.write(f"- Fixture points found in TPX: {scan.fixture_points}\n")
        if scan.notes:
            handle.write(f"- Notes: {scan.notes}\n")
    steps.append(("project_scan", "done", str(scan_report)))

    # 2) Intake packet from project docs.
    intake_dir = out_dir / "01_project_intake"
    try:
        intake_md, project_files_csv, sheets_csv = write_intake_outputs(project_folder, intake_dir)
        steps.append(("project_intake", "done", str(intake_md)))
    except Exception as exc:  # keep dashboard alive even on messy folders
        steps.append(("project_intake", f"failed: {exc}", ""))
        intake_md = project_files_csv = sheets_csv = Path("")

    # 3) Fast drawing estimate starter from intake outputs.
    estimate_dir = out_dir / "02_drawing_estimate"
    estimate_dir.mkdir(parents=True, exist_ok=True)
    coworker_md = estimate_dir / "estimator_coworker_report.md"
    item_csv = project_files_csv
    page_csv = sheets_csv
    try:
        file_rows = _read_csv_rows(project_files_csv, limit=40) if project_files_csv else []
        sheet_rows_for_report = _read_csv_rows(sheets_csv, limit=30) if sheets_csv else []
        with coworker_md.open("w", encoding="utf-8") as handle:
            handle.write(f"# Fast estimator coworker report - {project_name}\n\n")
            handle.write("This report is generated from the Phase 1 project intake scan so Full Worker Mode stays aligned with the estimator-coworker workflow.\n\n")
            handle.write("## Candidate electrical sheets\n\n")
            if sheet_rows_for_report:
                for row in sheet_rows_for_report:
                    handle.write(
                        f"- {row.get('sheet_number', '')} {row.get('sheet_title', '')} "
                        f"({row.get('discipline', '')}, PDF page {row.get('pdf_page', '')})\n"
                    )
            else:
                handle.write("- No candidate electrical sheets found from searchable text.\n")
            handle.write("\n## Important project files\n\n")
            if file_rows:
                for row in file_rows:
                    handle.write(f"- {row.get('role', '')}: {row.get('path', '')}\n")
            else:
                handle.write("- No project file inventory was generated.\n")
            handle.write("\n## Worker note\n\n")
            handle.write("Use this as the first-pass job read. Next, Drawing Intelligence should inspect candidate electrical sheets visually. Final takeoff still needs trained symbol recognition or LiveCount marking automation.\n")
        steps.append(("drawing_estimate", "done", str(coworker_md)))
    except Exception as exc:
        steps.append(("drawing_estimate", f"failed: {exc}", ""))
        coworker_md = page_csv = item_csv = Path("")

    # 4) Audit latest TPX if one exists.
    tpx_audit = Path("")
    latest_tpx = _find_latest_file(project_folder, ".tpx")
    if latest_tpx:
        audit_dir = out_dir / "03_livecount_tpx_audit"
        audit_dir.mkdir(parents=True, exist_ok=True)
        tpx_audit = audit_dir / "latest_tpx_agent_review.md"
        try:
            documents, points = read_tpx(latest_tpx)
            sheet_audits = audit_fixture_sheets(documents, points, read_sheet_map(None))
            write_project_audit_report(tpx_audit, project_name, sheet_audits)
            steps.append(("latest_tpx_audit", "done", str(tpx_audit)))
        except Exception as exc:
            steps.append(("latest_tpx_audit", f"failed: {exc}", str(latest_tpx)))
    else:
        steps.append(("latest_tpx_audit", "skipped: no TPX export found", ""))

    with manifest.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["step", "status", "artifact"])
        writer.writerows(steps)

    item_rows = _read_csv_rows(item_csv, limit=20) if item_csv else []
    sheet_rows = _read_csv_rows(sheets_csv, limit=20) if sheets_csv else []

    with dashboard.open("w", encoding="utf-8") as handle:
        handle.write(f"# Worker dashboard - {project_name}\n\n")
        handle.write("This is the agent's one-stop job packet. It ran the project like an estimating coworker as far as the current local worker can go.\n\n")
        handle.write("## Current capability status\n\n")
        handle.write("- Done automatically: folder scan, drawing/spec intake, likely sheet list, candidate item/tag list, and TPX audit when a LiveCount export exists.\n")
        handle.write("- Needs estimator/LiveCount work: final visual symbol counts, takeoff markings, assembly mapping, and pricing in Accubid.\n")
        handle.write("- Next integration target: teach the agent the exact LiveCount-online workflow for importing drawings and exporting takeoff data.\n\n")

        handle.write("## Run summary\n\n")
        handle.write(f"- Project folder: `{project_folder}`\n")
        handle.write(f"- Output folder: `{out_dir}`\n")
        handle.write(f"- Quick project grade: {scan.grade}\n")
        handle.write(f"- PDFs found: {scan.pdf_count}\n")
        handle.write(f"- TPX files found: {scan.tpx_count}\n")
        handle.write(f"- Accubid-like files found: {scan.accubid_count}\n")
        handle.write(f"- Fixture points in TPX exports: {scan.fixture_points}\n")
        if latest_tpx:
            handle.write(f"- Latest TPX audited: `{latest_tpx}`\n")
        handle.write("\n")

        handle.write("## What I found first\n\n")
        if item_rows:
            handle.write("Top project files from Phase 1:\n\n")
            for row in item_rows:
                handle.write(f"- {row.get('role', '')}: {row.get('path', '')}\n")
        else:
            handle.write("- No project file inventory was generated.\n")
        handle.write("\n")

        if sheet_rows:
            handle.write("Candidate electrical sheets:\n\n")
            for row in sheet_rows[:12]:
                handle.write(
                    f"- {row.get('sheet_number', '')} "
                    f"{row.get('sheet_title', '')} "
                    f"(page {row.get('pdf_page', row.get('page', ''))})\n"
                )
        else:
            handle.write("- No candidate electrical sheet list was generated.\n")
        handle.write("\n")

        handle.write("## Worker artifacts\n\n")
        for step, status, artifact in steps:
            if artifact:
                handle.write(f"- {step}: {status} - `{artifact}`\n")
            else:
                handle.write(f"- {step}: {status}\n")
        handle.write(f"- Manifest: `{manifest}`\n\n")

        handle.write("## What I would do next as the estimator coworker\n\n")
        handle.write("1. Review the candidate electrical sheet list and remove false positives.\n")
        handle.write("2. Open the drawing estimate report and decide which candidate tags are real takeoff items.\n")
        handle.write("3. In LiveCount, create or open the job and mark/count real symbols on the electrical sheets.\n")
        handle.write("4. Export TPX from LiveCount, then rerun the TPX audit to compare counts and catch missing scope.\n")
        handle.write("5. Map confirmed item types to Accubid assemblies/items and price the job.\n\n")

        handle.write("## Why this is not fully autonomous yet\n\n")
        handle.write("The current worker can read files and audit exports, but final electrical takeoff still requires either LiveCount marking automation or trained visual symbol recognition. That is the next build step.\n")

    return WorkerRunResult(dashboard=dashboard, out_dir=out_dir)
