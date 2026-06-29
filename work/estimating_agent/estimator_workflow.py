from __future__ import annotations

import csv
import shutil
from dataclasses import dataclass
from pathlib import Path

from .drawing_intelligence import write_drawing_intelligence_outputs
from .project_intake import write_intake_outputs
from .symbol_detection import detect_light_fixtures


@dataclass(frozen=True)
class EstimatorWorkflowResult:
    project_dashboard: Path
    takeoff_items: Path
    estimator_review: Path
    accubid_mapping: Path
    marked_up_drawings: Path
    out_dir: Path


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _write_empty_takeoff(path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["item", "quantity", "sheet", "location", "confidence", "reason", "review_required"])


def _write_empty_review(path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["sheet", "item", "quantity", "confidence", "reason", "review_required", "review_note"])


def _write_accubid_mapping_template(takeoff_items: Path, out_path: Path) -> None:
    rows = _read_csv(takeoff_items)
    with out_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "sheet",
                "takeoff_item",
                "quantity",
                "suggested_accubid_item",
                "suggested_accubid_assembly",
                "mapping_status",
                "estimator_note",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row.get("sheet", ""),
                    row.get("item", ""),
                    row.get("quantity", ""),
                    "",
                    "",
                    "needs_estimator_mapping",
                    "",
                ]
            )


def _copy_if_exists(source: Path, destination: Path) -> bool:
    if source.exists():
        shutil.copy2(source, destination)
        return True
    return False


def run_estimator_workflow(
    project_folder: Path,
    out_dir: Path,
    *,
    project_name: str | None = None,
    max_sheets: int = 6,
    min_confidence: float = 0.55,
) -> EstimatorWorkflowResult:
    """Run the estimator-coworker workflow.

    This is the intended user-facing path. Lower-level commands may still exist
    as implementation tools, but this function owns the primary output contract:
    project dashboard, takeoff items, estimator review, Accubid mapping, and
    marked drawings.
    """

    out_dir.mkdir(parents=True, exist_ok=True)
    project_name = project_name or project_folder.name

    project_dashboard = out_dir / "project_dashboard.md"
    takeoff_items = out_dir / "takeoff_items.csv"
    estimator_review = out_dir / "estimator_review.csv"
    accubid_mapping = out_dir / "accubid_mapping.csv"
    marked_up_drawings = out_dir / "marked_up_drawings.pdf"
    run_manifest = out_dir / "workflow_manifest.csv"

    steps: list[tuple[str, str, str]] = []

    intake_dir = out_dir / "_internal" / "01_project_intake"
    try:
        intake_dashboard, project_files_csv, sheet_index_csv = write_intake_outputs(project_folder, intake_dir)
        steps.append(("project_intelligence", "done", str(intake_dashboard)))
    except Exception as exc:
        project_files_csv = sheet_index_csv = Path("")
        steps.append(("project_intelligence", f"failed: {exc}", ""))

    drawing_dir = out_dir / "_internal" / "02_drawing_intelligence"
    rendered_dir = drawing_dir / "rendered_sheets"
    try:
        if sheet_index_csv and sheet_index_csv.exists():
            drawing_dashboard, sheet_page_map, drawing_regions = write_drawing_intelligence_outputs(
                project_folder,
                sheet_index_csv,
                drawing_dir,
                max_pages=120,
                max_sheets=max_sheets,
            )
            steps.append(("drawing_intelligence", "done", str(drawing_dashboard)))
        else:
            sheet_page_map = drawing_regions = Path("")
            steps.append(("drawing_intelligence", "skipped: no electrical sheet index", ""))
    except Exception as exc:
        sheet_page_map = drawing_regions = Path("")
        steps.append(("drawing_intelligence", f"failed: {exc}", ""))

    symbol_dir = out_dir / "_internal" / "03_symbol_detection"
    try:
        if rendered_dir.exists() and any(rendered_dir.glob("*.png")):
            symbol_summary, detected_takeoff, detected_review = detect_light_fixtures(
                rendered_dir,
                symbol_dir,
                min_confidence=min_confidence,
            )
            _copy_if_exists(detected_takeoff, takeoff_items)
            _copy_if_exists(detected_review, estimator_review)
            _copy_if_exists(symbol_dir / "marked_up_drawings.pdf", marked_up_drawings)
            steps.append(("symbol_detection_light_fixtures", "done", str(symbol_summary)))
        else:
            _write_empty_takeoff(takeoff_items)
            _write_empty_review(estimator_review)
            steps.append(("symbol_detection_light_fixtures", "skipped: no rendered sheets", ""))
    except Exception as exc:
        _write_empty_takeoff(takeoff_items)
        _write_empty_review(estimator_review)
        steps.append(("symbol_detection_light_fixtures", f"failed: {exc}", ""))

    if not takeoff_items.exists():
        _write_empty_takeoff(takeoff_items)
    if not estimator_review.exists():
        _write_empty_review(estimator_review)
    _write_accubid_mapping_template(takeoff_items, accubid_mapping)

    with run_manifest.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["workflow_step", "status", "artifact"])
        writer.writerows(steps)

    sheet_rows = _read_csv(sheet_index_csv) if sheet_index_csv and sheet_index_csv.exists() else []
    page_rows = _read_csv(sheet_page_map) if sheet_page_map and sheet_page_map.exists() else []
    takeoff_rows = _read_csv(takeoff_items)
    review_required = sum(1 for row in takeoff_rows if (row.get("review_required") or "").lower() in {"yes", "true", "1"})

    with project_dashboard.open("w", encoding="utf-8") as handle:
        handle.write(f"# Estimator coworker dashboard - {project_name}\n\n")
        handle.write("This is the main estimator-agent workflow output. It is intentionally small: use this dashboard plus the four estimator files below.\n\n")
        handle.write("## Primary outputs\n\n")
        handle.write(f"- `takeoff_items.csv` - detected/countable items for estimator review\n")
        handle.write(f"- `estimator_review.csv` - item-level evidence and review flags\n")
        handle.write(f"- `accubid_mapping.csv` - placeholder mapping from takeoff items to Accubid items/assemblies\n")
        handle.write(f"- `marked_up_drawings.pdf` - visual markup when rendered sheets were available\n")
        handle.write(f"- `project_dashboard.md` - this dashboard\n\n")

        handle.write("## Current run status\n\n")
        for step, status, artifact in steps:
            if artifact:
                handle.write(f"- {step}: {status} (`{artifact}`)\n")
            else:
                handle.write(f"- {step}: {status}\n")
        handle.write("\n")

        handle.write("## What the agent found\n\n")
        handle.write(f"- Electrical sheet candidates from intake: {len(sheet_rows)}\n")
        handle.write(f"- Located/rendered sheets from drawing intelligence: {len(page_rows)}\n")
        handle.write(f"- Takeoff item rows produced: {len(takeoff_rows)}\n")
        handle.write(f"- Rows requiring estimator review: {review_required}\n\n")

        if sheet_rows:
            handle.write("### First electrical sheet candidates\n\n")
            for row in sheet_rows[:15]:
                handle.write(
                    f"- {row.get('sheet_number', '')} {row.get('sheet_title', '')} "
                    f"({row.get('discipline', '')}, confidence {row.get('confidence', '')})\n"
                )
            handle.write("\n")

        if takeoff_rows:
            handle.write("### First takeoff item candidates\n\n")
            for row in takeoff_rows[:15]:
                handle.write(
                    f"- {row.get('sheet', '')}: {row.get('item', '')} x {row.get('quantity', '')} "
                    f"(confidence {row.get('confidence', '')}, review {row.get('review_required', '')})\n"
                )
            handle.write("\n")

        handle.write("## Estimator next action\n\n")
        if takeoff_rows:
            handle.write("Review `takeoff_items.csv` and `marked_up_drawings.pdf`, then fill `accubid_mapping.csv` for the items that should become Accubid items/assemblies.\n")
        else:
            handle.write("Review the sheet index and drawing intelligence outputs under `_internal/`; this run did not produce symbol detections yet.\n")
        handle.write("\n## Product direction note\n\n")
        handle.write("Lower-level scan, audit, and validation commands are support tools. The primary estimator-facing workflow is this `estimate-project` run.\n")

    return EstimatorWorkflowResult(
        project_dashboard=project_dashboard,
        takeoff_items=takeoff_items,
        estimator_review=estimator_review,
        accubid_mapping=accubid_mapping,
        marked_up_drawings=marked_up_drawings,
        out_dir=out_dir,
    )
