from __future__ import annotations

import csv
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

from work.estimating_agent.project_intake import (
    PdfCandidate,
    SheetHit,
    discipline_for,
    find_pdf_candidates,
    infer_title,
)


SHEET_NUMBER = re.compile(r"\b(?:E|ED|EL|EP|FA|LV|AV)\d{1,2}\.\d{1,2}[A-Z]?\b", re.I)
LIGHTING_HINTS = ("LIGHTING", "LUMINAIRE", "FIXTURE", "CEILING", "EXIT", "EMERGENCY")
POWER_HINTS = ("POWER", "RECEPTACLE", "PANEL", "EQUIPMENT", "FEEDER", "DISCONNECT")
TAKEOFF_TAG = re.compile(
    r"\b("
    r"EXIT|EM|EBU|BATTERY|"
    r"[A-Z]{1,3}\d{0,3}(?:[- ][A-Z0-9]{1,4})?|"
    r"F\d+[A-Z]?(?:\s+V\d+)?|"
    r"LP-[A-Z0-9-]+"
    r")\b",
    re.I,
)
NOISE_TAGS = {
    "A",
    "B",
    "C",
    "D",
    "E",
    "F",
    "G",
    "H",
    "I",
    "J",
    "K",
    "L",
    "N",
    "S",
    "T",
    "V",
    "W",
    "X",
    "AC",
    "DC",
    "NO",
    "ON",
    "OF",
    "TO",
    "IN",
    "AT",
    "BY",
    "OR",
    "IF",
    "AS",
    "IS",
    "IT",
    "THE",
    "AND",
    "FOR",
    "WITH",
    "NOTE",
    "NOTES",
    "SHEET",
    "DETAIL",
    "PLAN",
    "ELECTRICAL",
    "LIGHTING",
    "POWER",
}


@dataclass(frozen=True)
class PageScan:
    pdf: Path
    page: int
    sheet_number: str
    sheet_title: str
    discipline: str
    text_chars: int
    item_counts: Counter


def _read_page_texts(pdf_path: Path, max_pages: int | None = None) -> list[str]:
    reader = PdfReader(str(pdf_path))
    pages = reader.pages if max_pages is None else reader.pages[:max_pages]
    return [(page.extract_text() or "") for page in pages]


def _candidate_pdfs(input_path: Path) -> list[PdfCandidate]:
    if input_path.is_file() and input_path.suffix.lower() == ".pdf":
        return [PdfCandidate(path=input_path, kind="drawings", size=input_path.stat().st_size, score=100)]
    if input_path.is_dir():
        return find_pdf_candidates(input_path, limit=30)
    raise FileNotFoundError(f"Input is not a PDF or folder: {input_path}")


def _normalize_tag(tag: str) -> str:
    return re.sub(r"\s+", " ", tag.upper().strip())


def _looks_like_takeoff_tag(tag: str) -> bool:
    tag = _normalize_tag(tag)
    if tag in NOISE_TAGS:
        return False
    if len(tag) == 1:
        return False
    if tag.isdigit():
        return False
    if tag.startswith("E") and re.fullmatch(r"E\d{1,2}\.\d{1,2}[A-Z]?", tag):
        return False
    return bool(
        re.fullmatch(r"[A-Z]{1,3}\d+[A-Z]?(?: V\d+)?", tag)
        or tag in {"EXIT", "EM", "EBU", "BATTERY"}
        or tag.startswith("LP-")
    )


def _infer_sheet(text: str) -> tuple[str, str, str]:
    matches = []
    for m in SHEET_NUMBER.finditer(text):
        candidate = m.group(0).upper()
        number_part = re.search(r"(\d{1,2})\.(\d{1,2})", candidate)
        if number_part and int(number_part.group(1)) <= 9 and int(number_part.group(2)) <= 9:
            matches.append(candidate)
    sheet = ""
    if matches:
        # Titleblocks usually repeat; choose the last/most specific electrical-like hit.
        sheet = matches[-1]
    title = infer_title(text, sheet) if sheet else ""
    discipline = discipline_for(sheet, title) if sheet else "unknown"
    upper = text.upper()
    if discipline in {"unknown", "electrical"}:
        if any(h in upper for h in LIGHTING_HINTS):
            discipline = "lighting"
        elif any(h in upper for h in POWER_HINTS):
            discipline = "power"
    return sheet, title, discipline


def scan_drawing(input_path: Path, max_pages: int | None = None) -> list[PageScan]:
    scans: list[PageScan] = []
    for pdf in _candidate_pdfs(input_path):
        if pdf.kind not in {"drawings", "addendum", "other_pdf"} and input_path.is_dir():
            continue
        try:
            page_texts = _read_page_texts(pdf.path, max_pages=max_pages)
        except Exception:
            continue
        for page_number, text in enumerate(page_texts, 1):
            sheet, title, discipline = _infer_sheet(text)
            upper = text.upper()
            if input_path.is_dir() and discipline == "unknown" and not any(
                word in upper for word in ("ELECTRICAL", "LIGHTING", "POWER", "FIXTURE", "LUMINAIRE")
            ):
                continue
            if input_path.is_file() and len(page_texts) > 20:
                has_real_sheet = bool(sheet)
                has_electrical_title = any(
                    phrase in upper
                    for phrase in (
                        "ELECTRICAL NOTES",
                        "LIGHTING PLAN",
                        "POWER PLAN",
                        "LOW VOLTAGE",
                        "FIRE ALARM",
                        "SITE LIGHTING",
                        "LUMINAIRE SCHEDULE",
                        "PANEL SCHEDULE",
                    )
                )
                if not has_real_sheet and not has_electrical_title:
                    continue
            tags = Counter()
            for match in TAKEOFF_TAG.finditer(text):
                tag = _normalize_tag(match.group(0))
                if _looks_like_takeoff_tag(tag):
                    tags[tag] += 1
            scans.append(
                PageScan(
                    pdf=pdf.path,
                    page=page_number,
                    sheet_number=sheet,
                    sheet_title=title,
                    discipline=discipline,
                    text_chars=len(text),
                    item_counts=tags,
                )
            )
    return scans


def count_item(input_path: Path, item: str, max_pages: int | None = None) -> list[dict[str, object]]:
    needle = _normalize_tag(item)
    pattern = re.compile(rf"(?<![A-Z0-9-]){re.escape(needle)}(?![A-Z0-9-])", re.I)
    rows: list[dict[str, object]] = []
    for pdf in _candidate_pdfs(input_path):
        if pdf.kind not in {"drawings", "addendum", "other_pdf"} and input_path.is_dir():
            continue
        try:
            page_texts = _read_page_texts(pdf.path, max_pages=max_pages)
        except Exception:
            continue
        for page_number, text in enumerate(page_texts, 1):
            sheet, title, discipline = _infer_sheet(text)
            upper = text.upper()
            count = len(pattern.findall(upper))
            if count:
                rows.append(
                    {
                        "pdf": str(pdf.path),
                        "page": page_number,
                        "sheet_number": sheet,
                        "sheet_title": title,
                        "discipline": discipline,
                        "item": needle,
                        "text_hit_count": count,
                    }
                )
    return rows


def write_scan_outputs(input_path: Path, out_dir: Path, max_pages: int | None = None) -> tuple[Path, Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    scans = scan_drawing(input_path, max_pages=max_pages)
    page_csv = out_dir / "drawing_pages.csv"
    item_csv = out_dir / "item_types.csv"
    report_md = out_dir / "drawing_scan_report.md"

    item_totals: Counter = Counter()
    by_discipline: Counter = Counter()
    searchable_pages = 0
    for scan in scans:
        item_totals.update(scan.item_counts)
        by_discipline[scan.discipline] += 1
        if scan.text_chars:
            searchable_pages += 1

    with page_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["pdf", "page", "sheet_number", "sheet_title", "discipline", "text_chars", "top_item_hits"])
        for scan in scans:
            top = "; ".join(f"{tag}:{count}" for tag, count in scan.item_counts.most_common(12))
            writer.writerow([scan.pdf, scan.page, scan.sheet_number, scan.sheet_title, scan.discipline, scan.text_chars, top])

    with item_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["item_type", "text_hit_count"])
        for tag, count in item_totals.most_common():
            writer.writerow([tag, count])

    with report_md.open("w", encoding="utf-8") as handle:
        handle.write(f"# Drawing scan report - {input_path.name}\n\n")
        handle.write("This is a takeoff starter scan. Counts are text-hit counts from searchable PDF text, not final visual fixture counts.\n\n")
        handle.write("Use this like a coworker pre-read: it finds likely electrical sheets and candidate tags/items so the estimator can decide what to count or map into Accubid.\n\n")
        handle.write("## Summary\n\n")
        handle.write(f"- Input: `{input_path}`\n")
        handle.write(f"- Candidate pages scanned: {len(scans)}\n")
        handle.write(f"- Pages with searchable text: {searchable_pages}\n")
        handle.write(f"- Candidate item types found: {len(item_totals)}\n\n")
        if scans and searchable_pages == 0:
            handle.write("Warning: these drawings appear scanned/image-only. Visual/OCR counting is needed.\n\n")
        handle.write("## Sheet/disciplines found\n\n")
        for discipline, count in by_discipline.most_common():
            handle.write(f"- {discipline}: {count} pages\n")
        if not by_discipline:
            handle.write("- No likely electrical pages were identified.\n")
        handle.write("\n## Top candidate item types / tags\n\n")
        for tag, count in item_totals.most_common(60):
            handle.write(f"- {tag}: {count}\n")
        handle.write("\n## Suggested estimator actions\n\n")
        handle.write("- Open `drawing_pages.csv` to confirm the electrical sheets.\n")
        handle.write("- Open `item_types.csv` to choose which tags/items are real takeoff items versus sheet references/noise.\n")
        handle.write("- For any important item, run `count-item` to get page-by-page hits.\n")
        handle.write("- If the PDF is scanned/image-only, use LiveCount/manual review until visual detection is trained.\n")

    return report_md, page_csv, item_csv


def write_count_outputs(input_path: Path, item: str, out_dir: Path, max_pages: int | None = None) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = count_item(input_path, item, max_pages=max_pages)
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", _normalize_tag(item)).strip("_") or "item"
    csv_path = out_dir / f"count_{safe}.csv"
    report_path = out_dir / f"count_{safe}.md"
    total = sum(int(row["text_hit_count"]) for row in rows)
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["pdf", "page", "sheet_number", "sheet_title", "discipline", "item", "text_hit_count"],
        )
        writer.writeheader()
        writer.writerows(rows)
    with report_path.open("w", encoding="utf-8") as handle:
        handle.write(f"# Count report - {_normalize_tag(item)}\n\n")
        handle.write("These are searchable-text hit counts, not final visually verified counts.\n\n")
        handle.write(f"- Input: `{input_path}`\n")
        handle.write(f"- Total text hits: {total}\n")
        handle.write(f"- Pages with hits: {len(rows)}\n\n")
        handle.write("| Page | Sheet | Discipline | Hits | PDF |\n")
        handle.write("|---:|---|---|---:|---|\n")
        for row in rows:
            handle.write(
                f"| {row['page']} | {row['sheet_number']} | {row['discipline']} | {row['text_hit_count']} | {row['pdf']} |\n"
            )
    return report_path, csv_path


def write_estimate_starter(input_path: Path, out_dir: Path, max_pages: int | None = None) -> tuple[Path, Path, Path]:
    report_md, page_csv, item_csv = write_scan_outputs(input_path, out_dir, max_pages=max_pages)
    coworker_md = out_dir / "estimator_coworker_report.md"
    item_totals = []
    with item_csv.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        item_totals = list(reader)
    with coworker_md.open("w", encoding="utf-8") as handle:
        handle.write(f"# Estimator coworker starter - {input_path.name}\n\n")
        handle.write("## What I prepared\n\n")
        handle.write("- Found likely electrical drawing pages/sheets.\n")
        handle.write("- Listed candidate item types/tags from searchable drawing text.\n")
        handle.write("- Created CSVs you can review or use for mapping into Accubid/LiveCount.\n\n")
        handle.write("## First pass candidate item/tag list\n\n")
        for row in item_totals[:40]:
            handle.write(f"- {row['item_type']}: {row['text_hit_count']} text hits\n")
        handle.write("\n## What I still need from the estimator\n\n")
        handle.write("- Confirm which item types are real takeoff items versus notes/titleblock/sheet-reference noise.\n")
        handle.write("- For each real item type, map it to an Accubid assembly/item.\n")
        handle.write("- Use LiveCount/manual visual review for final counts where symbols are graphical or scanned.\n")
        handle.write("\n## Files\n\n")
        handle.write(f"- Drawing scan report: `{report_md}`\n")
        handle.write(f"- Pages CSV: `{page_csv}`\n")
        handle.write(f"- Item types CSV: `{item_csv}`\n")
    return coworker_md, page_csv, item_csv
