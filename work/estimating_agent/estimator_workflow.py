from __future__ import annotations

import csv
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from reportlab.pdfgen import canvas

from .drawing_intelligence import write_drawing_intelligence_outputs
from .project_intake import write_intake_outputs
from .schedule_understanding import write_fixture_schedule_outputs
from .symbol_detection import detect_light_fixtures


@dataclass(frozen=True)
class EstimatorWorkflowResult:
    project_dashboard: Path
    takeoff_items: Path
    estimator_review: Path
    accubid_mapping: Path
    marked_up_drawings: Path
    validation_answer_key: Path
    out_dir: Path


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path or not str(path) or path.is_dir() or not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _write_empty_takeoff(path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "project_name",
                "source_file",
                "sheet_number",
                "sheet_name",
                "category",
                "tag",
                "schedule_description",
                "quantity",
                "confidence",
                "review_status",
                "evidence",
                "notes",
            ]
        )


def _write_empty_review(path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["sheet_number", "sheet_name", "category", "tag", "detected_quantity", "schedule_description", "review_status", "evidence", "notes"])


def _write_csv_rows(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_accubid_mapping_template(takeoff_items: Path, out_path: Path) -> None:
    rows = _read_csv(takeoff_items)
    with out_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "category",
                "tag",
                "schedule_description",
                "quantity",
                "accubid_item_placeholder",
                "accubid_assembly_placeholder",
                "estimator_notes",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row.get("category", "LIGHT FIXTURE"),
                    row.get("tag", _tag_from_takeoff_item(row.get("item", ""))),
                    row.get("schedule_description", ""),
                    row.get("quantity", ""),
                    "",
                    "",
                    "",
                ]
            )


def _tag_from_takeoff_item(item: str) -> str:
    marker = "LIGHT FIXTURE TAG "
    upper = item.upper()
    if upper.startswith(marker):
        return item[len(marker):].strip().upper()
    return item.strip().upper()


def _enrich_takeoff_with_fixture_schedule(takeoff_items: Path, schedule_entries_csv: Path) -> int:
    rows = _read_csv(takeoff_items)
    entries = {
        (row.get("tag") or "").upper(): row
        for row in _read_csv(schedule_entries_csv)
        if row.get("tag")
    }
    if not rows:
        _write_empty_takeoff(takeoff_items)
        return 0

    preferred_fields = [
        "item",
        "quantity",
        "sheet",
        "location",
        "confidence",
        "reason",
        "review_category",
        "schedule_description",
        "schedule_confidence",
        "schedule_source",
        "review_required",
    ]
    fieldnames = []
    for field in [*preferred_fields, *rows[0].keys()]:
        if field not in fieldnames:
            fieldnames.append(field)

    matched = 0
    for row in rows:
        tag = _tag_from_takeoff_item(row.get("item", ""))
        entry = entries.get(tag)
        if entry:
            row["schedule_description"] = entry.get("schedule_description", "")
            row["schedule_confidence"] = entry.get("schedule_confidence", "")
            source_pdf = entry.get("schedule_source_pdf", "")
            source_page = entry.get("schedule_source_page", "")
            row["schedule_source"] = f"{source_pdf}#page={source_page}" if source_pdf and source_page else source_pdf
            matched += 1
        else:
            row.setdefault("schedule_description", "")
            row.setdefault("schedule_confidence", "")
            row.setdefault("schedule_source", "")
    _write_csv_rows(takeoff_items, rows, fieldnames)
    return matched


def _write_validation_answer_key_template(takeoff_items: Path, out_path: Path) -> None:
    rows = _read_csv(takeoff_items)
    with out_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "project_name",
                "source_file",
                "sheet_number",
                "sheet_name",
                "category",
                "tag",
                "reviewed_quantity",
                "notes",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row.get("project_name", ""),
                    row.get("source_file", ""),
                    row.get("sheet_number", row.get("sheet", "")),
                    row.get("sheet_name", ""),
                    row.get("category", "LIGHT FIXTURE"),
                    row.get("tag", _tag_from_takeoff_item(row.get("item", ""))),
                    "",
                    f"AI quantity: {row.get('quantity', '')}. Enter reviewed quantity only after estimator review.",
                ]
            )


def _sheet_lookup(selected_sheet_rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {(row.get("sheet_number") or "").upper(): row for row in selected_sheet_rows}


def _normalize_estimator_outputs(
    *,
    project_name: str,
    takeoff_items: Path,
    estimator_review: Path,
    selected_sheet_rows: list[dict[str, str]],
) -> None:
    rows = _read_csv(takeoff_items)
    if not rows:
        _write_empty_takeoff(takeoff_items)
        _write_empty_review(estimator_review)
        return

    sheets = _sheet_lookup(selected_sheet_rows)
    normalized: list[dict[str, str]] = []
    review_rows: list[dict[str, str]] = []
    for row in rows:
        sheet_number = row.get("sheet_number") or row.get("sheet") or ""
        sheet_info = sheets.get(sheet_number.upper(), {})
        tag = row.get("tag") or _tag_from_takeoff_item(row.get("item", ""))
        category = row.get("category") or "LIGHT FIXTURE"
        schedule_description = row.get("schedule_description", "")
        evidence_bits = [
            row.get("reason", ""),
            row.get("location", ""),
            row.get("schedule_source", ""),
        ]
        evidence = "; ".join(bit for bit in evidence_bits if bit)
        notes = "First-pass AI quantity; estimator must review."
        if not schedule_description and tag:
            notes += " Fixture tag not matched to schedule."
        normalized_row = {
            "project_name": project_name,
            "source_file": row.get("source_file") or sheet_info.get("pdf", ""),
            "sheet_number": sheet_number,
            "sheet_name": row.get("sheet_name") or sheet_info.get("sheet_title", ""),
            "category": category,
            "tag": tag,
            "schedule_description": schedule_description,
            "quantity": row.get("quantity", ""),
            "confidence": row.get("confidence", ""),
            "review_status": "NEEDS_REVIEW",
            "evidence": evidence,
            "notes": notes,
        }
        normalized.append(normalized_row)
        review_rows.append(
            {
                "sheet_number": normalized_row["sheet_number"],
                "sheet_name": normalized_row["sheet_name"],
                "category": category,
                "tag": tag,
                "detected_quantity": normalized_row["quantity"],
                "schedule_description": schedule_description,
                "review_status": "NEEDS_REVIEW",
                "evidence": evidence,
                "notes": notes,
            }
        )

    takeoff_fields = ["project_name", "source_file", "sheet_number", "sheet_name", "category", "tag", "schedule_description", "quantity", "confidence", "review_status", "evidence", "notes"]
    review_fields = ["sheet_number", "sheet_name", "category", "tag", "detected_quantity", "schedule_description", "review_status", "evidence", "notes"]
    _write_csv_rows(takeoff_items, normalized, takeoff_fields)
    _write_csv_rows(estimator_review, review_rows, review_fields)


PLAN_WORDS = ("PLAN", "LIGHTING", "POWER", "ELECTRICAL", "FLOOR", "LEVEL")
NON_PLAN_WORDS = (
    "DETAIL",
    "DETAILS",
    "SCHEDULE",
    "SCHEDULES",
    "RISER",
    "ONE-LINE",
    "ONE LINE",
    "DIAGRAM",
    "LEGEND",
    "NOTES",
    "TITLE",
    "INDEX",
)


def _sheet_priority(row: dict[str, str]) -> tuple[int, int, float, str]:
    discipline = (row.get("discipline") or "").lower()
    title = (row.get("sheet_title") or "").upper()
    sheet = (row.get("sheet_number") or "").upper()
    try:
        confidence = float(row.get("confidence") or 0)
    except ValueError:
        confidence = 0.0

    is_plan = any(word in title for word in PLAN_WORDS)
    is_non_plan = any(word in title for word in NON_PLAN_WORDS)

    if discipline == "lighting" and is_plan and not is_non_plan:
        bucket = 0
    elif discipline == "lighting" and not is_non_plan:
        bucket = 1
    elif discipline in {"electrical", "power"} and is_plan and not is_non_plan:
        bucket = 2
    elif discipline in {"electrical", "power"} and not is_non_plan:
        bucket = 3
    elif discipline in {"fire_alarm", "low_voltage", "electrical_demo"} and is_plan and not is_non_plan:
        bucket = 4
    else:
        bucket = 9
    return bucket, 0 if is_plan else 1, -confidence, sheet


def _write_focused_sheet_index(sheet_index_csv: Path, out_path: Path, limit: int) -> tuple[Path, list[dict[str, str]]]:
    rows = _read_csv(sheet_index_csv)
    if not rows:
        return sheet_index_csv, []

    focused = sorted(rows, key=_sheet_priority)
    useful = [row for row in focused if _sheet_priority(row)[0] < 9]
    if useful:
        focused = useful
    focused = focused[: max(1, limit)]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(focused)
    return out_path, focused


def _copy_if_exists(source: Path, destination: Path) -> bool:
    if source.exists():
        shutil.copy2(source, destination)
        return True
    return False


def _write_no_markups_pdf(path: Path, reason: str) -> None:
    c = canvas.Canvas(str(path), pagesize=(792, 612))
    c.setFont("Helvetica-Bold", 16)
    c.drawString(72, 540, "No marked-up drawings generated")
    c.setFont("Helvetica", 11)
    c.drawString(72, 510, "The estimator package was created, but no drawing markup PDF was available for this run.")
    c.drawString(72, 490, f"Reason: {reason[:120]}")
    c.drawString(72, 460, "Check project_dashboard.md for the next estimator action.")
    c.save()


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
    validation_answer_key = out_dir / "validation_answer_key_template.csv"
    internal_dir = out_dir / "_internal"
    run_manifest = internal_dir / "workflow_manifest.csv"
    render_debug = internal_dir / "render_debug.md"

    if internal_dir.exists():
        shutil.rmtree(internal_dir)
    stale_validation_dir = out_dir / "validation"
    if stale_validation_dir.exists():
        shutil.rmtree(stale_validation_dir)
    for stale_file in [project_dashboard, takeoff_items, estimator_review, accubid_mapping, marked_up_drawings, validation_answer_key]:
        if stale_file.exists():
            stale_file.unlink()

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
    render_problem = ""
    try:
        if sheet_index_csv and sheet_index_csv.exists():
            focused_sheet_index_csv, selected_sheet_rows = _write_focused_sheet_index(
                sheet_index_csv,
                drawing_dir / "focused_sheet_index.csv",
                max_sheets,
            )
            drawing_dashboard, sheet_page_map, drawing_regions = write_drawing_intelligence_outputs(
                project_folder,
                focused_sheet_index_csv,
                drawing_dir,
                max_pages=120,
                max_sheets=max_sheets,
            )
            _copy_if_exists(drawing_dir / "render_debug.md", render_debug)
            steps.append(("drawing_intelligence", f"done: selected {len(selected_sheet_rows)} likely plan sheets", str(drawing_dashboard)))
            if not rendered_dir.exists() or not any(rendered_dir.glob("*.png")):
                render_problem = "Drawing intelligence selected sheets/pages, but no rendered PNG images were created. See `_internal/render_debug.md`."
        else:
            selected_sheet_rows = []
            sheet_page_map = drawing_regions = Path("")
            steps.append(("drawing_intelligence", "skipped: no electrical sheet index", ""))
            render_problem = "No electrical sheet index was available for drawing rendering."
    except Exception as exc:
        selected_sheet_rows = []
        sheet_page_map = drawing_regions = Path("")
        steps.append(("drawing_intelligence", f"failed: {exc}", ""))
        render_problem = f"Drawing intelligence failed before rendering: {exc}"

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
            steps.append(("symbol_detection_supported_categories", "done", str(symbol_summary)))
        else:
            _write_empty_takeoff(takeoff_items)
            _write_empty_review(estimator_review)
            reason = render_problem or "No rendered sheet images were available for symbol detection."
            steps.append(("symbol_detection_supported_categories", f"skipped: {reason}", ""))
    except Exception as exc:
        _write_empty_takeoff(takeoff_items)
        _write_empty_review(estimator_review)
        steps.append(("symbol_detection_supported_categories", f"failed: {exc}", ""))

    if not takeoff_items.exists():
        _write_empty_takeoff(takeoff_items)
    if not estimator_review.exists():
        _write_empty_review(estimator_review)
    if not marked_up_drawings.exists():
        last_status = steps[-1][1] if steps else "no symbol detection step ran"
        placeholder_reason = render_problem or last_status
        _write_no_markups_pdf(marked_up_drawings, placeholder_reason)

    schedule_dir = out_dir / "_internal" / "04_schedule_understanding"
    schedule_matches = 0
    try:
        if takeoff_items.exists() and _read_csv(takeoff_items):
            schedule_summary, schedule_entries = write_fixture_schedule_outputs(project_folder, takeoff_items, schedule_dir)
            schedule_matches = _enrich_takeoff_with_fixture_schedule(takeoff_items, schedule_entries)
            steps.append(("schedule_understanding", f"done: matched {schedule_matches} takeoff rows to schedule entries", str(schedule_summary)))
        else:
            steps.append(("schedule_understanding", "skipped: no takeoff items", ""))
    except Exception as exc:
        steps.append(("schedule_understanding", f"failed: {exc}", ""))

    selected_sheet_rows = selected_sheet_rows if "selected_sheet_rows" in locals() else []
    _normalize_estimator_outputs(
        project_name=project_name,
        takeoff_items=takeoff_items,
        estimator_review=estimator_review,
        selected_sheet_rows=selected_sheet_rows,
    )
    _write_accubid_mapping_template(takeoff_items, accubid_mapping)
    _write_validation_answer_key_template(takeoff_items, validation_answer_key)

    run_manifest.parent.mkdir(parents=True, exist_ok=True)
    with run_manifest.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["workflow_step", "status", "artifact"])
        writer.writerows(steps)

    sheet_rows = _read_csv(sheet_index_csv) if sheet_index_csv and sheet_index_csv.exists() else []
    page_rows = _read_csv(sheet_page_map) if sheet_page_map and sheet_page_map.exists() else []
    project_file_rows = _read_csv(project_files_csv) if project_files_csv and project_files_csv.exists() else []
    pdf_file_count = sum(1 for row in project_file_rows if (row.get("extension") or "").lower() == ".pdf")
    takeoff_rows = _read_csv(takeoff_items)
    review_required = sum(1 for row in takeoff_rows if (row.get("review_status") or "").upper() in {"NEEDS_REVIEW", "MISMATCH", ""})
    schedule_matched_rows = sum(1 for row in takeoff_rows if row.get("schedule_description"))
    review_category_counts: dict[str, int] = {}
    category_quantities: dict[str, int] = {}
    for row in takeoff_rows:
        category = row.get("category") or "LIGHT FIXTURE"
        review_category_counts[category] = review_category_counts.get(category, 0) + 1
        try:
            category_quantities[category] = category_quantities.get(category, 0) + int(float(row.get("quantity") or 0))
        except ValueError:
            category_quantities[category] = category_quantities.get(category, 0)
    total_fixture_qty = 0
    for row in takeoff_rows:
        try:
            total_fixture_qty += int(float(row.get("quantity") or 0))
        except ValueError:
            pass
    plan_tags = {row.get("tag", "") for row in takeoff_rows if row.get("tag")}
    schedule_entries_path = out_dir / "_internal" / "04_schedule_understanding" / "fixture_schedule_entries.csv"
    schedule_entries = _read_csv(schedule_entries_path)
    schedule_tags = {row.get("tag", "") for row in schedule_entries if row.get("tag")}
    tags_missing_schedule = sorted(tag for tag in plan_tags if tag and tag not in schedule_tags)
    schedule_tags_not_on_plans = sorted(tag for tag in schedule_tags if tag and tag not in plan_tags)
    lighting_sheets = [row for row in selected_sheet_rows if (row.get("discipline") or "").lower() == "lighting"]
    fire_alarm_sheets = [row for row in selected_sheet_rows if (row.get("discipline") or "").lower() == "fire_alarm"]
    other_selected_sheets = [row for row in selected_sheet_rows if row not in lighting_sheets and row not in fire_alarm_sheets]
    marked_status = "created" if marked_up_drawings.exists() else "not created"
    marked_is_placeholder = False
    try:
        from pypdf import PdfReader

        marked_text = "\n".join(page.extract_text() or "" for page in PdfReader(str(marked_up_drawings)).pages[:1]) if marked_up_drawings.exists() else ""
        marked_is_placeholder = "No marked-up drawings generated" in marked_text
    except Exception:
        marked_is_placeholder = False
    validation_dir = out_dir / "validation"
    validation_status = "not run yet; use the validation answer key after estimator review"
    if (validation_dir / "SYMBOL_DETECTION_VALIDATION.md").exists():
        validation_status = f"available in `{validation_dir}`"

    with project_dashboard.open("w", encoding="utf-8") as handle:
        handle.write(f"# Estimator coworker dashboard - {project_name}\n\n")
        handle.write("This is first-pass estimator review output, not final bid output.\n\n")
        handle.write("The agent scanned a project folder, selected likely electrical plan sheets, produced candidate counts, marked the drawings, and prepared review CSVs for an estimator to check.\n\n")
        handle.write("## Supported first-pass categories\n\n")
        handle.write("- light_fixture\n")
        handle.write("- exit_sign\n")
        handle.write("- emergency_light\n")
        handle.write("- fire_alarm_device\n\n")
        handle.write("## Primary outputs\n\n")
        handle.write(f"- `takeoff_items.csv` - detected/countable items for estimator review\n")
        handle.write(f"- `estimator_review.csv` - item-level evidence and review flags\n")
        handle.write(f"- `accubid_mapping.csv` - mapping template only; it does not price work\n")
        handle.write(f"- `marked_up_drawings.pdf` - visual markup when rendered sheets were available\n")
        handle.write(f"- `validation_answer_key_template.csv` - fill/export reviewed quantities here to score the agent\n")
        handle.write(f"- `project_dashboard.md` - this dashboard\n\n")

        handle.write("## Current run status\n\n")
        for step, status, artifact in steps:
            if artifact:
                handle.write(f"- {step}: {status} (`{artifact}`)\n")
            else:
                handle.write(f"- {step}: {status}\n")
        handle.write("\n")

        handle.write("## What the agent found\n\n")
        handle.write(f"- Project scanned: `{project_folder}`\n")
        handle.write(f"- Run timestamp: {datetime.now().isoformat(timespec='seconds')}\n")
        handle.write(f"- Project files classified: {len(project_file_rows)}\n")
        handle.write(f"- PDFs scanned/classified: {pdf_file_count}\n")
        handle.write(f"- Electrical sheet candidates from intake: {len(sheet_rows)}\n")
        handle.write(f"- Likely plan sheets selected for takeoff: {len(selected_sheet_rows)}\n")
        handle.write(f"- Located/rendered sheets from drawing intelligence: {len(page_rows)}\n")
        handle.write(f"- Takeoff item rows produced: {len(takeoff_rows)}\n")
        handle.write(f"- Total first-pass detected quantity: {total_fixture_qty}\n")
        handle.write(f"- Takeoff rows matched to schedule descriptions: {schedule_matched_rows}\n")
        handle.write(f"- Rows requiring estimator review: {review_required}\n\n")
        handle.write("## Markup and validation status\n\n")
        if marked_is_placeholder:
            handle.write(f"- Marked drawing PDF: placeholder only (`marked_up_drawings.pdf`)\n")
            handle.write(f"- Render problem: {render_problem or 'see `_internal/render_debug.md` for rendering diagnostics'}\n")
        else:
            handle.write(f"- Marked drawing PDF: {marked_status} (`marked_up_drawings.pdf`)\n")
        if render_debug.exists():
            handle.write(f"- Render diagnostics: `{render_debug}`\n")
        handle.write(f"- Validation status: {validation_status}\n\n")

        if review_category_counts:
            handle.write("## Quantities by category\n\n")
            for category, count in sorted(review_category_counts.items()):
                handle.write(f"- {category}: {category_quantities.get(category, 0)} detected quantity across {count} takeoff row(s)\n")
            handle.write("\n")

        if selected_sheet_rows:
            handle.write("## Sheets used for this run\n\n")
            if lighting_sheets:
                handle.write("### Selected lighting sheets\n\n")
                for row in lighting_sheets:
                    handle.write(
                        f"- {row.get('sheet_number', '')} {row.get('sheet_title', '')} "
                        f"(confidence {row.get('confidence', '')})\n"
                    )
                handle.write("\n")
            if fire_alarm_sheets:
                handle.write("### Selected fire alarm sheets\n\n")
                for row in fire_alarm_sheets:
                    handle.write(
                        f"- {row.get('sheet_number', '')} {row.get('sheet_title', '')} "
                        f"(confidence {row.get('confidence', '')})\n"
                    )
                handle.write("\n")
            if other_selected_sheets:
                handle.write("### Other selected electrical sheets\n\n")
                for row in other_selected_sheets:
                    handle.write(
                        f"- {row.get('sheet_number', '')} {row.get('sheet_title', '')} "
                        f"({row.get('discipline', '')}, confidence {row.get('confidence', '')})\n"
                    )
                handle.write("\n")
            handle.write("\n")
        elif sheet_rows:
            handle.write("### First electrical sheet candidates\n\n")
            for row in sheet_rows[:15]:
                handle.write(
                    f"- {row.get('sheet_number', '')} {row.get('sheet_title', '')} "
                    f"({row.get('discipline', '')}, confidence {row.get('confidence', '')})\n"
                )
            handle.write("\n")

        if takeoff_rows:
            handle.write("## Tag counts by category\n\n")
            tag_counts: dict[tuple[str, str], int] = {}
            for row in takeoff_rows:
                try:
                    key = (row.get("category", ""), row.get("tag", ""))
                    tag_counts[key] = tag_counts.get(key, 0) + int(float(row.get("quantity") or 0))
                except ValueError:
                    key = (row.get("category", ""), row.get("tag", ""))
                    tag_counts[key] = tag_counts.get(key, 0)
            for (category, tag), qty in sorted(tag_counts.items()):
                if tag:
                    handle.write(f"- {category} / {tag}: {qty}\n")
            handle.write("\n## First takeoff item candidates\n\n")
            for row in takeoff_rows[:15]:
                handle.write(
                    f"- {row.get('sheet_number', '')}: {row.get('tag', '')} x {row.get('quantity', '')} "
                    f"(confidence {row.get('confidence', '')}, review {row.get('review_status', '')})\n"
                )
                if row.get("schedule_description"):
                    handle.write(f"  - Schedule: {row.get('schedule_description', '')[:180]}\n")
            handle.write("\nThese are candidate counts for estimator review, not final bid quantities.\n")
            handle.write("\n")

            handle.write("## Schedule or legend matches\n\n")
            handle.write(f"- Rows with schedule/legend description matches: {schedule_matched_rows}\n")
            if tags_missing_schedule:
                handle.write("Plan tags missing from schedule match:\n")
                for tag in tags_missing_schedule[:30]:
                    handle.write(f"- {tag}\n")
            else:
                handle.write("- No detected plan tags are missing from the matched schedule.\n")
            if schedule_tags_not_on_plans:
                handle.write("\nSchedule tags not found on selected plan sheets:\n")
                for tag in schedule_tags_not_on_plans[:30]:
                    handle.write(f"- {tag}\n")
            handle.write("\n")

        handle.write("## Limitations\n\n")
        handle.write("- Real drawings may be harder than the safe synthetic demo drawings.\n")
        handle.write("- Scanned PDFs may require OCR before the agent can read labels reliably.\n")
        handle.write("- Unusual title blocks, dense legends, or crowded notes can still cause missed counts.\n")
        handle.write("- Quantities require estimator review before they are used for a bid.\n")
        handle.write("- Current scope does not include receptacles, switches, panels, feeders, conduit, or pricing.\n\n")

        handle.write("## Recommended estimator review steps\n\n")
        if takeoff_rows:
            handle.write("1. Review `takeoff_items.csv` and `marked_up_drawings.pdf`.\n")
            handle.write("2. Confirm any schedule descriptions that were automatically attached.\n")
            handle.write("3. Fill `validation_answer_key_template.csv` with reviewed quantities from LiveCount, Accubid, or manual check.\n")
            handle.write("4. Fill `accubid_mapping.csv` for items that should become Accubid items/assemblies. This is a mapping template, not pricing.\n")
        else:
            handle.write("This run did not produce symbol detections. Check whether the project folder contains searchable drawing PDFs and whether lighting/electrical plan sheets were selected under `_internal/02_drawing_intelligence/focused_sheet_index.csv`.\n")
        handle.write("\n## How to validate this run\n\n")
        handle.write("After reviewed quantities are entered in `validation_answer_key_template.csv`, run:\n\n")
        handle.write("```powershell\n")
        handle.write("python work\\estimating_agent_cli.py validate-detections-csv --detections takeoff_items.csv --answer-key validation_answer_key_template.csv --out-dir validation\n")
        handle.write("```\n")
        handle.write("\n## Product direction note\n\n")
        handle.write("Lower-level scan, audit, and validation commands are support tools. The primary estimator-facing workflow is this `estimate-project` run.\n")

    return EstimatorWorkflowResult(
        project_dashboard=project_dashboard,
        takeoff_items=takeoff_items,
        estimator_review=estimator_review,
        accubid_mapping=accubid_mapping,
        marked_up_drawings=marked_up_drawings,
        validation_answer_key=validation_answer_key,
        out_dir=out_dir,
    )
