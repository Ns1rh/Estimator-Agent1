from __future__ import annotations

import csv
import re
from collections import Counter, defaultdict
from pathlib import Path

from .livecount_tpx import TpxDocument, TpxPoint, read_tpx


TAG_FROM_DETECTION_ITEM = re.compile(r"\b(?:TAG|TYPE)\s+([A-Z0-9.-]+)\b", re.IGNORECASE)
TAG_FROM_SYMBOL_TYPE = re.compile(r"^fixture_label_(.+)$", re.IGNORECASE)
TAG_IN_TPX_DESCRIPTION = re.compile(r"\b(?:[A-Z]\d{1,2}[A-Z]?|EM\d?[A-Z]?|EMS|EXIT|X\d+[A-Z]?)\b")
LIGHTING_WORDS = {
    "LIGHT",
    "LIGHTING",
    "FIXTURE",
    "FIXTURES",
    "LUMINAIRE",
    "LUMINAIRES",
    "EMERGENCY",
    "EXIT",
}


def _normalize_sheet(value: str) -> str:
    return value.strip().upper().replace(" ", "")


def _normalize_tag(value: str) -> str:
    return value.strip().upper().replace(" ", "")


def _tag_from_detection_row(row: dict[str, str]) -> str:
    item = row.get("item", "")
    symbol_type = row.get("symbol_type", "")
    match = TAG_FROM_DETECTION_ITEM.search(item)
    if match:
        return _normalize_tag(match.group(1))
    match = TAG_FROM_SYMBOL_TYPE.search(symbol_type)
    if match:
        return _normalize_tag(match.group(1))
    return _normalize_tag(item or symbol_type or "UNKNOWN")


def _detection_counts(path: Path) -> Counter[tuple[str, str]]:
    counts: Counter[tuple[str, str]] = Counter()
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            sheet = _normalize_sheet(row.get("sheet", ""))
            tag = _tag_from_detection_row(row)
            try:
                qty = int(float(row.get("quantity", "") or 1))
            except ValueError:
                qty = 1
            if sheet and tag:
                counts[(sheet, tag)] += qty
    return counts


def _doc_lookup(documents: list[TpxDocument]) -> dict[int, TpxDocument]:
    return {doc.page: doc for doc in documents}


def _sheet_for_point(point: TpxPoint, docs_by_page: dict[int, TpxDocument]) -> str:
    doc = docs_by_page.get(point.page)
    if not doc:
        return f"TPX_PAGE_{point.page}"
    return _normalize_sheet(doc.drawing_number or doc.description or f"TPX_PAGE_{point.page}")


def _looks_lighting_related(point: TpxPoint, doc: TpxDocument | None) -> bool:
    haystack = " ".join(
        [
            point.layer or "",
            point.description or "",
            doc.drawing_number if doc else "",
            doc.description if doc else "",
            doc.relative_path if doc else "",
        ]
    ).upper()
    return any(word in haystack for word in LIGHTING_WORDS)


def _tpx_lighting_counts(documents: list[TpxDocument], points: list[TpxPoint]) -> Counter[tuple[str, str]]:
    docs_by_page = _doc_lookup(documents)
    counts: Counter[tuple[str, str]] = Counter()
    for point in points:
        doc = docs_by_page.get(point.page)
        if not _looks_lighting_related(point, doc):
            continue
        tag_match = TAG_IN_TPX_DESCRIPTION.search(point.description.upper())
        tag = _normalize_tag(tag_match.group(0) if tag_match else point.description)
        sheet = _sheet_for_point(point, docs_by_page)
        counts[(sheet, tag)] += 1
    return counts


def _by_tag(counts: Counter[tuple[str, str]]) -> Counter[str]:
    totals: Counter[str] = Counter()
    for (_sheet, tag), qty in counts.items():
        totals[tag] += qty
    return totals


def validate_symbol_detections(detections_csv: Path, tpx: Path, out_dir: Path) -> tuple[Path, Path]:
    """Compare AI detections to a historical LiveCount TPX export.

    This validator is intentionally conservative. If the TPX does not appear to
    contain comparable lighting/fixture takeoff data, it reports that instead of
    manufacturing an accuracy score from unrelated feeders, panels, or markup.
    """

    out_dir.mkdir(parents=True, exist_ok=True)
    details_csv = out_dir / "symbol_detection_validation.csv"
    report_md = out_dir / "SYMBOL_DETECTION_VALIDATION.md"

    detection_sheet_tag = _detection_counts(detections_csv)
    documents, points = read_tpx(tpx)
    tpx_sheet_tag = _tpx_lighting_counts(documents, points)

    detection_tag = _by_tag(detection_sheet_tag)
    tpx_tag = _by_tag(tpx_sheet_tag)
    all_tags = sorted(set(detection_tag) | set(tpx_tag))

    with details_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "tag",
                "ai_detected_qty",
                "historical_tpx_qty",
                "delta",
                "status",
            ]
        )
        for tag in all_tags:
            ai_qty = detection_tag[tag]
            historical_qty = tpx_tag[tag]
            delta = ai_qty - historical_qty
            if ai_qty and historical_qty and delta == 0:
                status = "match"
            elif ai_qty and historical_qty:
                status = "quantity_differs"
            elif ai_qty:
                status = "ai_only"
            else:
                status = "historical_only"
            writer.writerow([tag, ai_qty, historical_qty, delta, status])

    total_ai = sum(detection_tag.values())
    total_historical = sum(tpx_tag.values())
    comparable = total_historical >= max(5, int(total_ai * 0.05))
    total_abs_error = sum(abs(detection_tag[tag] - tpx_tag[tag]) for tag in all_tags)
    matched_tags = sum(1 for tag in all_tags if detection_tag[tag] and detection_tag[tag] == tpx_tag[tag])

    tpx_layer_counts: Counter[str] = Counter(point.layer or "(blank)" for point in points)
    tpx_desc_samples = Counter(point.description for point in points).most_common(12)

    with report_md.open("w", encoding="utf-8") as handle:
        handle.write("# Symbol detection validation\n\n")
        handle.write("This compares the AI Phase 3 detection output to a historical LiveCount TPX export.\n\n")
        handle.write("## Inputs\n\n")
        handle.write(f"- AI detections: `{detections_csv}`\n")
        handle.write(f"- Historical TPX: `{tpx}`\n\n")
        handle.write("## Result\n\n")
        handle.write(f"- AI detected lighting/fixture quantity: {total_ai}\n")
        handle.write(f"- Comparable historical lighting/fixture quantity found in TPX: {total_historical}\n")
        handle.write(f"- Tags compared: {len(all_tags)}\n")
        handle.write(f"- Exact tag quantity matches: {matched_tags}\n")
        if comparable:
            denominator = max(1, total_historical)
            score = max(0.0, 1 - (total_abs_error / denominator))
            handle.write(f"- Conservative tag-count score: {score:.2%}\n")
        else:
            handle.write("- Conservative tag-count score: not available\n")
        handle.write("\n")

        if not comparable:
            handle.write("## Important finding\n\n")
            handle.write(
                "This TPX does not appear to contain comparable lighting fixture takeoff data. "
                "It mostly contains other takeoff layers/descriptions, so it cannot be used as "
                "the answer key for Phase 3 light-fixture accuracy.\n\n"
            )
            handle.write("That is not a detector failure. It means we need either the correct LiveCount lighting export, ")
            handle.write("a matching Accubid/LiveCount count report, or a human-reviewed sheet count for these rendered sheets.\n\n")

        handle.write("## TPX contents observed\n\n")
        handle.write("Layer counts:\n\n")
        for layer, qty in tpx_layer_counts.most_common():
            handle.write(f"- {layer}: {qty}\n")
        handle.write("\nCommon TPX descriptions:\n\n")
        for desc, qty in tpx_desc_samples:
            handle.write(f"- {qty} x {desc}\n")

        handle.write("\n## Output\n\n")
        handle.write(f"- Detail comparison CSV: `{details_csv.name}`\n")

    return details_csv, report_md
