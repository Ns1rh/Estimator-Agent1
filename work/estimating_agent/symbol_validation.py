from __future__ import annotations

import csv
import re
from collections import Counter
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
ALL_SHEETS = "__ALL_SHEETS__"
ALL_TAGS = "__ALL_TAGS__"


def _normalize_sheet(value: str) -> str:
    return value.strip().upper().replace(" ", "")


def _normalize_tag(value: str) -> str:
    return value.strip().upper().replace(" ", "")


def _tag_from_detection_row(row: dict[str, str]) -> str:
    if row.get("tag"):
        return _normalize_tag(row.get("tag", ""))
    item = row.get("item", "")
    symbol_type = row.get("symbol_type", "")
    match = TAG_FROM_DETECTION_ITEM.search(item)
    if match:
        return _normalize_tag(match.group(1))
    match = TAG_FROM_SYMBOL_TYPE.search(symbol_type)
    if match:
        return _normalize_tag(match.group(1))
    return _normalize_tag(item or symbol_type or "UNKNOWN")


def _normalize_category(value: str) -> str:
    return (value or "light_fixture").strip().lower().replace(" ", "_")


def _detection_counts(path: Path) -> Counter[tuple[str, str, str]]:
    counts: Counter[tuple[str, str, str]] = Counter()
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            sheet = _normalize_sheet(_first_present(row, ["sheet_number", "sheet", "drawing", "drawing_number"]))
            category = _normalize_category(_first_present(row, ["category", "item_category"]))
            tag = _tag_from_detection_row(row)
            try:
                qty = int(float(row.get("quantity", "") or 1))
            except ValueError:
                qty = 1
            if category and sheet and tag:
                counts[(category, sheet, tag)] += qty
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


def _tpx_lighting_counts(documents: list[TpxDocument], points: list[TpxPoint]) -> Counter[tuple[str, str, str]]:
    docs_by_page = _doc_lookup(documents)
    counts: Counter[tuple[str, str, str]] = Counter()
    for point in points:
        doc = docs_by_page.get(point.page)
        if not _looks_lighting_related(point, doc):
            continue
        tag_match = TAG_IN_TPX_DESCRIPTION.search(point.description.upper())
        tag = _normalize_tag(tag_match.group(0) if tag_match else point.description)
        sheet = _sheet_for_point(point, docs_by_page)
        counts[("light_fixture", sheet, tag)] += 1
    return counts


def _by_tag(counts: Counter[tuple[str, str, str]]) -> Counter[str]:
    totals: Counter[str] = Counter()
    for (category, _sheet, tag), qty in counts.items():
        totals[f"{category}:{tag}"] += qty
    return totals


def _first_present(row: dict[str, str], names: list[str]) -> str:
    lowered = {key.strip().lower(): value for key, value in row.items()}
    for name in names:
        value = lowered.get(name.lower())
        if value is not None and value.strip():
            return value
    return ""


def _answer_key_counts(path: Path) -> Counter[tuple[str, str, str]]:
    """Read a simple estimator answer-key CSV.

    Accepted columns are intentionally flexible:
    - sheet / drawing / sheet_number
    - tag / item / fixture / fixture_type / symbol / description
    - quantity / qty / count

    This lets the user export from LiveCount/Accubid or hand-enter a small
    reviewed count table without matching an exact internal schema.
    """

    counts: Counter[tuple[str, str, str]] = Counter()
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            sheet = _normalize_sheet(
                _first_present(row, ["sheet", "drawing", "sheet_number", "drawing_number"])
            ) or ALL_SHEETS
            category = _normalize_category(_first_present(row, ["category", "item_category"]))
            tag = _normalize_tag(
                _first_present(row, ["tag", "item", "fixture", "fixture_type", "symbol", "description"])
            ) or ALL_TAGS
            qty_text = _first_present(row, ["reviewed_quantity", "estimator_quantity", "quantity", "qty", "count", "answer_key_qty"])
            try:
                qty = int(float(qty_text or "1"))
            except ValueError:
                continue
            if category and sheet and tag:
                counts[(category, sheet, tag)] += qty
    return counts


def _detection_counts_for_answer_granularity(
    detection_counts: Counter[tuple[str, str, str]],
    answer_counts: Counter[tuple[str, str, str]],
) -> Counter[tuple[str, str, str]]:
    """Aggregate AI detections to match coarse answer-key rows when needed.

    Real reviewed exports are not always sheet/tag perfect. If an answer key
    supplies only category-level totals, compare AI at category level instead
    of crashing or inventing sheet/tag detail.
    """
    if not answer_counts:
        return detection_counts

    aligned: Counter[tuple[str, str, str]] = Counter()
    covered_detection_keys: set[tuple[str, str, str]] = set()

    for category, answer_sheet, answer_tag in answer_counts:
        if answer_sheet == ALL_SHEETS or answer_tag == ALL_TAGS:
            total = 0
            for det_key, qty in detection_counts.items():
                det_category, det_sheet, det_tag = det_key
                if det_category != category:
                    continue
                if answer_sheet != ALL_SHEETS and det_sheet != answer_sheet:
                    continue
                if answer_tag != ALL_TAGS and det_tag != answer_tag:
                    continue
                total += qty
                covered_detection_keys.add(det_key)
            aligned[(category, answer_sheet, answer_tag)] = total

    for det_key, qty in detection_counts.items():
        if det_key not in covered_detection_keys:
            aligned[det_key] += qty
    return aligned


def _write_comparison(
    detections_csv: Path,
    answer_key_path: Path,
    answer_key_label: str,
    detection_sheet_tag: Counter[tuple[str, str, str]],
    answer_sheet_tag: Counter[tuple[str, str, str]],
    out_dir: Path,
    extra_sections: list[tuple[str, list[str]]] | None = None,
) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    details_csv = out_dir / "symbol_detection_validation.csv"
    report_md = out_dir / "SYMBOL_DETECTION_VALIDATION.md"

    all_items = sorted(set(detection_sheet_tag) | set(answer_sheet_tag))
    with details_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "sheet",
                "category",
                "tag",
                "ai_detected_qty",
                "answer_key_qty",
                "delta",
                "percent_difference",
                "status",
            ]
        )
        for category, sheet, tag in all_items:
            ai_qty = detection_sheet_tag[(category, sheet, tag)]
            answer_qty = answer_sheet_tag[(category, sheet, tag)]
            delta = ai_qty - answer_qty
            if answer_qty:
                percent_difference = f"{(delta / answer_qty):.2%}"
            else:
                percent_difference = ""
            if ai_qty and answer_qty and delta == 0:
                status = "MATCH"
            elif ai_qty and answer_qty:
                status = "MISMATCH"
            elif ai_qty:
                status = "ESTIMATOR_MISSING"
            else:
                status = "AI_MISSING"
            if not ai_qty and not answer_qty:
                status = "NEEDS_REVIEW"
            sheet_label = "ALL_SHEETS" if sheet == ALL_SHEETS else sheet
            tag_label = "ALL_TAGS" if tag == ALL_TAGS else tag
            writer.writerow([sheet_label, category, tag_label, ai_qty, answer_qty, delta, percent_difference, status])

    detection_tag = _by_tag(detection_sheet_tag)
    answer_tag = _by_tag(answer_sheet_tag)
    all_tags = sorted(set(detection_tag) | set(answer_tag))
    total_ai = sum(detection_tag.values())
    total_answer = sum(answer_tag.values())
    comparable = total_answer >= max(5, int(total_ai * 0.05))
    total_abs_error = sum(abs(detection_sheet_tag[item] - answer_sheet_tag[item]) for item in all_items)
    matched_items = sum(1 for item in all_items if detection_sheet_tag[item] and detection_sheet_tag[item] == answer_sheet_tag[item])
    differing_items = sum(1 for item in all_items if detection_sheet_tag[item] != answer_sheet_tag[item])

    with report_md.open("w", encoding="utf-8") as handle:
        handle.write("# Symbol detection validation\n\n")
        handle.write("This compares the AI Phase 3 detection output to an estimator/native-takeoff answer key.\n\n")
        handle.write("## Inputs\n\n")
        handle.write(f"- AI detections: `{detections_csv}`\n")
        handle.write(f"- Answer key ({answer_key_label}): `{answer_key_path}`\n\n")
        handle.write("## Result\n\n")
        handle.write(f"- AI detected quantity: {total_ai}\n")
        handle.write(f"- Answer-key quantity: {total_answer}\n")
        handle.write(f"- Category/sheet/tag rows compared: {len(all_items)}\n")
        handle.write(f"- Exact category/sheet/tag quantity matches: {matched_items}\n")
        handle.write(f"- Category/sheet/tag rows needing review: {differing_items}\n")
        if comparable:
            denominator = max(1, total_answer)
            score = max(0.0, 1 - (total_abs_error / denominator))
            handle.write(f"- Conservative tag-count score: {score:.2%}\n")
        else:
            handle.write("- Conservative tag-count score: not available\n")
        handle.write("\n")

        if not comparable:
            handle.write("## Important finding\n\n")
            handle.write(
                "The answer key does not contain enough comparable symbol-count data for a meaningful accuracy score. "
                "Use a lighting/fixture-specific LiveCount export, Accubid count report, or human-reviewed sheet count.\n\n"
            )

        handle.write("## Biggest differences\n\n")
        differences = sorted(
            (
                (category, sheet, tag, detection_sheet_tag[(category, sheet, tag)], answer_sheet_tag[(category, sheet, tag)], detection_sheet_tag[(category, sheet, tag)] - answer_sheet_tag[(category, sheet, tag)])
                for category, sheet, tag in all_items
            ),
            key=lambda item: abs(item[5]),
            reverse=True,
        )
        for category, sheet, tag, ai_qty, answer_qty, delta in differences[:20]:
            if delta == 0:
                continue
            sheet_label = "ALL_SHEETS" if sheet == ALL_SHEETS else sheet
            tag_label = "ALL_TAGS" if tag == ALL_TAGS else tag
            handle.write(f"- {sheet_label} / {category} / {tag_label}: AI {ai_qty}, answer key {answer_qty}, delta {delta:+}\n")
        if not any(delta for _category, _sheet, _tag, _ai, _answer, delta in differences):
            handle.write("- No differences found.\n")

        if extra_sections:
            for title, lines in extra_sections:
                handle.write(f"\n## {title}\n\n")
                for line in lines:
                    handle.write(f"{line}\n")

        handle.write("\n## Output\n\n")
        handle.write(f"- Detail comparison CSV: `{details_csv.name}`\n")

    return details_csv, report_md


def validate_symbol_detections_against_counts_csv(detections_csv: Path, answer_key_csv: Path, out_dir: Path) -> tuple[Path, Path]:
    answer_sheet_tag = _answer_key_counts(answer_key_csv)
    detection_sheet_tag = _detection_counts_for_answer_granularity(
        _detection_counts(detections_csv),
        answer_sheet_tag,
    )
    return _write_comparison(
        detections_csv=detections_csv,
        answer_key_path=answer_key_csv,
        answer_key_label="CSV",
        detection_sheet_tag=detection_sheet_tag,
        answer_sheet_tag=answer_sheet_tag,
        out_dir=out_dir,
    )


def validate_symbol_detections(detections_csv: Path, tpx: Path, out_dir: Path) -> tuple[Path, Path]:
    """Compare AI detections to a historical LiveCount TPX export.

    This validator is intentionally conservative. If the TPX does not appear to
    contain comparable lighting/fixture takeoff data, it reports that instead of
    manufacturing an accuracy score from unrelated feeders, panels, or markup.
    """

    detection_sheet_tag = _detection_counts(detections_csv)
    documents, points = read_tpx(tpx)
    tpx_sheet_tag = _tpx_lighting_counts(documents, points)

    detection_tag = _by_tag(detection_sheet_tag)
    tpx_tag = _by_tag(tpx_sheet_tag)

    tpx_layer_counts: Counter[str] = Counter(point.layer or "(blank)" for point in points)
    tpx_desc_samples = Counter(point.description for point in points).most_common(12)
    extra_lines = ["Layer counts:", ""]
    extra_lines.extend(f"- {layer}: {qty}" for layer, qty in tpx_layer_counts.most_common())
    extra_lines.extend(["", "Common TPX descriptions:", ""])
    extra_lines.extend(f"- {qty} x {desc}" for desc, qty in tpx_desc_samples)

    return _write_comparison(
        detections_csv=detections_csv,
        answer_key_path=tpx,
        answer_key_label="LiveCount TPX",
        detection_sheet_tag=detection_sheet_tag,
        answer_sheet_tag=tpx_sheet_tag,
        out_dir=out_dir,
        extra_sections=[("TPX contents observed", extra_lines)],
    )
