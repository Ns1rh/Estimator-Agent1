from __future__ import annotations

import csv
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from work.estimating_agent.drawing_estimator import PageScan, scan_drawing


@dataclass(frozen=True)
class PrepItem:
    item_type: str
    text_hits: int
    likely_accubid_item: str
    accubid_category: str
    takeoff_method: str
    confidence: str
    notes: str


def _safe_name(value: str, fallback: str = "project") -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_")
    return safe or fallback


def _classify_item(tag: str) -> tuple[str, str, str, str, str]:
    t = tag.upper().strip()
    if t in {"EXIT", "EX"} or "EXIT" in t:
        return (
            "EXIT SIGN / EMERGENCY EGRESS DEVICE",
            "LIGHTING / LIFE SAFETY",
            "point-count",
            "medium",
            "Confirm fixture schedule type, emergency circuiting, arrows/faces, and mounting.",
        )
    if t in {"EM", "EMER", "EBU", "BATTERY"} or "EM" == t[:2]:
        return (
            "EMERGENCY LIGHT / BATTERY UNIT",
            "LIGHTING / LIFE SAFETY",
            "point-count",
            "medium",
            "Confirm whether tag is fixture type, emergency designation, or note text.",
        )
    if re.fullmatch(r"F\d+[A-Z]?(?: V\d+)?", t):
        return (
            f"LUMINAIRE TYPE {t}",
            "LIGHTING",
            "point-count",
            "medium",
            "Map to luminaire schedule, then count symbols visually in LiveCount web.",
        )
    if re.fullmatch(r"[A-Z]{1,3}\d+[A-Z]?", t):
        prefix = re.match(r"[A-Z]+", t).group(0)
        if prefix in {"R", "REC", "GFI", "GF"}:
            return (
                "RECEPTACLE / DEVICE",
                "POWER DEVICES",
                "point-count",
                "low",
                "Text tag alone is ambiguous; verify symbol legend and device type.",
            )
        if prefix in {"S", "SW"}:
            return (
                "SWITCH / CONTROL DEVICE",
                "SWITCHES",
                "point-count",
                "low",
                "Text tag alone is ambiguous; verify switch symbol and gang/type.",
            )
        if prefix in {"FA", "SD", "HD", "SP"}:
            return (
                "FIRE ALARM / LOW VOLTAGE DEVICE",
                "SYSTEMS",
                "point-count",
                "medium",
                "Confirm device type on fire alarm/low-voltage symbol legend.",
            )
        return (
            f"TAGGED DEVICE / EQUIPMENT {t}",
            "UNMAPPED",
            "review",
            "low",
            "Needs estimator mapping to Accubid item or assembly.",
        )
    if t.startswith("LP-"):
        return (
            "PANEL / LIGHTING PANEL REFERENCE",
            "DISTRIBUTION",
            "review",
            "low",
            "Usually a circuit/panel reference, not a count item by itself.",
        )
    return (
        t,
        "UNMAPPED",
        "review",
        "low",
        "Needs estimator review.",
    )


def _item_totals(scans: list[PageScan]) -> Counter:
    totals: Counter = Counter()
    for scan in scans:
        totals.update(scan.item_counts)
    return totals


def _pages_for_item(scans: list[PageScan]) -> dict[str, list[PageScan]]:
    pages: dict[str, list[PageScan]] = defaultdict(list)
    for scan in scans:
        for item in scan.item_counts:
            pages[item].append(scan)
    return pages


def build_prep_items(scans: list[PageScan], limit: int = 80) -> list[PrepItem]:
    items: list[PrepItem] = []
    for item_type, count in _item_totals(scans).most_common(limit):
        likely, category, method, confidence, notes = _classify_item(item_type)
        items.append(
            PrepItem(
                item_type=item_type,
                text_hits=count,
                likely_accubid_item=likely,
                accubid_category=category,
                takeoff_method=method,
                confidence=confidence,
                notes=notes,
            )
        )
    return items


def write_web_accubid_prep(
    input_path: Path,
    out_dir: Path,
    *,
    project_name: str | None = None,
    max_pages: int | None = None,
    item_limit: int = 80,
) -> tuple[Path, Path, Path, Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    project = project_name or input_path.name
    scans = scan_drawing(input_path, max_pages=max_pages)
    prep_items = build_prep_items(scans, item_limit)
    pages_by_item = _pages_for_item(scans)

    report_md = out_dir / "website_accubid_prep_report.md"
    task_csv = out_dir / "takeoff_tasks_for_livecount_web.csv"
    mapping_csv = out_dir / "accubid_item_mapping_template.csv"
    page_csv = out_dir / "candidate_electrical_pages.csv"
    workflow_md = out_dir / "LIVECOUNT_WEB_WORKFLOW.md"

    with page_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["pdf", "page", "sheet_number", "sheet_title", "discipline", "text_chars", "top_item_hits"])
        for scan in scans:
            top = "; ".join(f"{tag}:{count}" for tag, count in scan.item_counts.most_common(12))
            writer.writerow([scan.pdf, scan.page, scan.sheet_number, scan.sheet_title, scan.discipline, scan.text_chars, top])

    with mapping_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "drawing_tag_or_item",
                "text_hits",
                "suggested_accubid_item_or_assembly",
                "accubid_category",
                "estimator_confirmed_accubid_item",
                "confirmed_unit",
                "confidence",
                "notes",
            ]
        )
        for item in prep_items:
            writer.writerow(
                [
                    item.item_type,
                    item.text_hits,
                    item.likely_accubid_item,
                    item.accubid_category,
                    "",
                    "",
                    item.confidence,
                    item.notes,
                ]
            )

    with task_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "priority",
                "drawing_tag_or_item",
                "suggested_accubid_item_or_assembly",
                "takeoff_method",
                "text_hits",
                "candidate_pages",
                "livecount_web_action",
                "estimator_status",
            ]
        )
        for idx, item in enumerate(prep_items, 1):
            page_refs = []
            for scan in pages_by_item.get(item.item_type, [])[:12]:
                sheet = scan.sheet_number or f"page {scan.page}"
                page_refs.append(f"{sheet} p{scan.page}")
            action = (
                "Create/select matching item in Accubid, then mark/count visually in LiveCount web. "
                "Use this row as the manual bridge until web quantity API/import is available."
            )
            writer.writerow(
                [
                    idx,
                    item.item_type,
                    item.likely_accubid_item,
                    item.takeoff_method,
                    item.text_hits,
                    "; ".join(page_refs),
                    action,
                    "not_started",
                ]
            )

    searchable_pages = sum(1 for scan in scans if scan.text_chars)
    disciplines = Counter(scan.discipline for scan in scans)

    with workflow_md.open("w", encoding="utf-8") as handle:
        handle.write("# LiveCount web + Accubid workflow\n\n")
        handle.write("Use this when you only have access to LiveCount in the browser, not LiveCount Desktop.\n\n")
        handle.write("## What the agent can do now\n\n")
        handle.write("- Pre-read drawings/spec PDFs.\n")
        handle.write("- Identify likely electrical sheets and candidate tags/items.\n")
        handle.write("- Suggest Accubid item/assembly mappings.\n")
        handle.write("- Produce a takeoff task list for LiveCount web/manual marking.\n\n")
        handle.write("## What the agent cannot honestly do yet\n\n")
        handle.write("- It cannot currently create real LiveCount web quantity/count items unless the web account exposes Quantity Takeoff Manager or a supported import/API.\n")
        handle.write("- It cannot turn generic LiveCount web annotations into Accubid quantities by itself.\n\n")
        handle.write("## Recommended daily workflow\n\n")
        handle.write("1. Run this prep package on the new project folder or drawing PDF.\n")
        handle.write("2. Open `accubid_item_mapping_template.csv` and confirm/adjust the Accubid item or assembly for each real item.\n")
        handle.write("3. Open `takeoff_tasks_for_livecount_web.csv` and work down the list in LiveCount web.\n")
        handle.write("4. Use LiveCount web to visually mark/count the matching symbols.\n")
        handle.write("5. Enter/sync the confirmed quantities into Accubid using the confirmed mapping.\n")
        handle.write("6. Keep the completed CSVs as training/validation data for the next version of the agent.\n\n")
        handle.write("## Upgrade path\n\n")
        handle.write("- If LiveCount web exposes Quantity Takeoff Manager later, connect this task list directly to that item list.\n")
        handle.write("- If a supported import/export format is discovered, generate that format from `takeoff_tasks_for_livecount_web.csv`.\n")
        handle.write("- If your company permits Accubid exports, use completed estimates as ground truth for learning better mappings.\n")

    with report_md.open("w", encoding="utf-8") as handle:
        handle.write(f"# Website-only Accubid prep package - {project}\n\n")
        handle.write("This package is built for your current access constraint: LiveCount website only, with Accubid as the real estimating system.\n\n")
        handle.write("## Summary\n\n")
        handle.write(f"- Input: `{input_path}`\n")
        handle.write(f"- Candidate electrical pages scanned: {len(scans)}\n")
        handle.write(f"- Pages with searchable text: {searchable_pages}\n")
        handle.write(f"- Candidate item/tag rows: {len(prep_items)}\n\n")
        if scans and searchable_pages == 0:
            handle.write("Warning: these drawings look image-only/scanned. The current package can still make a checklist, but final counts need OCR/visual review.\n\n")
        handle.write("## Disciplines/sheet groups found\n\n")
        for discipline, count in disciplines.most_common():
            handle.write(f"- {discipline}: {count} pages\n")
        if not disciplines:
            handle.write("- No likely electrical pages found.\n")
        handle.write("\n## Top prep items\n\n")
        handle.write("| Tag/item | Text hits | Suggested Accubid mapping | Method | Confidence |\n")
        handle.write("|---|---:|---|---|---|\n")
        for item in prep_items[:40]:
            handle.write(
                f"| {item.item_type} | {item.text_hits} | {item.likely_accubid_item} | {item.takeoff_method} | {item.confidence} |\n"
            )
        handle.write("\n## Output files\n\n")
        handle.write(f"- LiveCount web workflow: `{workflow_md}`\n")
        handle.write(f"- Takeoff task list: `{task_csv}`\n")
        handle.write(f"- Accubid mapping template: `{mapping_csv}`\n")
        handle.write(f"- Candidate page list: `{page_csv}`\n")
        handle.write("\n## Next estimator action\n\n")
        handle.write("Open the mapping template first. Confirm the Accubid item/assembly names for the real items, then use the task CSV as the LiveCount web marking checklist.\n")

    return report_md, task_csv, mapping_csv, page_csv, workflow_md
