from __future__ import annotations

import csv
import re
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader, PdfWriter

from work.estimating_agent.project_intake import (
    SHEET_INDEX_WORDS,
    find_pdf_candidates,
    normalize_sheet_number,
)


DISCIPLINE_PRIORITY = {
    "lighting": 0,
    "power": 1,
    "electrical": 2,
    "fire_alarm": 3,
    "low_voltage": 4,
    "electrical_demo": 5,
}

REGION_KEYWORDS = {
    "legend": ("legend", "symbols", "abbreviations", "symbol list"),
    "schedule": ("schedule", "fixture schedule", "panel schedule", "equipment schedule", "luminaire schedule"),
    "notes": ("general notes", "keyed notes", "sheet notes", "notes"),
    "plan_area": ("plan", "level", "roof", "floor plan", "lighting plan", "power plan", "fire alarm plan"),
    "title_block": ("sheet title", "sheet number", "issue", "revision", "northwestern", "drawn by", "checked by"),
}


@dataclass(frozen=True)
class SheetTarget:
    discipline: str
    sheet_number: str
    sheet_title: str
    confidence: float
    source_pdf: Path


@dataclass(frozen=True)
class LocatedSheet:
    target: SheetTarget
    pdf: Path
    page: int
    page_score: float
    text_chars: int
    reason: str


@dataclass(frozen=True)
class RegionHint:
    sheet_number: str
    pdf: Path
    page: int
    region_type: str
    confidence: float
    location_hint: str
    reason: str


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _target_sheets(sheet_index_csv: Path, limit: int) -> list[SheetTarget]:
    rows = _read_csv(sheet_index_csv)
    targets: list[SheetTarget] = []
    seen: set[str] = set()
    rows.sort(
        key=lambda row: (
            DISCIPLINE_PRIORITY.get(row.get("discipline", ""), 99),
            -float(row.get("confidence") or 0),
            row.get("sheet_number", ""),
        )
    )
    for row in rows:
        sheet = normalize_sheet_number(row.get("sheet_number", ""))
        if not sheet or sheet in seen or sheet == "NONE":
            continue
        seen.add(sheet)
        pdf = Path(row.get("pdf", ""))
        try:
            confidence = float(row.get("confidence") or 0)
        except ValueError:
            confidence = 0
        targets.append(
            SheetTarget(
                discipline=row.get("discipline", ""),
                sheet_number=sheet,
                sheet_title=row.get("sheet_title", ""),
                confidence=confidence,
                source_pdf=pdf,
            )
        )
        if len(targets) >= limit:
            break
    return targets


def _page_texts(pdf: Path, max_pages: int) -> list[str]:
    try:
        reader = PdfReader(str(pdf))
    except Exception:
        return []
    texts: list[str] = []
    for page in reader.pages[:max_pages]:
        try:
            texts.append(page.extract_text() or "")
        except Exception:
            texts.append("")
    return texts


def _outline_sheet_pages(pdf: Path) -> dict[str, tuple[int, str]]:
    try:
        reader = PdfReader(str(pdf))
        outline = reader.outline
    except Exception:
        return {}

    result: dict[str, tuple[int, str]] = {}

    def walk(items: list[object]) -> None:
        for item in items:
            if isinstance(item, list):
                walk(item)
                continue
            title = getattr(item, "title", str(item))
            match = re.match(r"\s*([A-Z]{1,3}\d{1,2}\.\d{1,2}[A-Z]?|[A-Z]{1,3}-\d{2,3}[A-Z]?|[A-Z]{1,3}\d{3}[A-Z]?)\s*(?:-|:)?\s*(.*)", title, re.I)
            if not match:
                continue
            sheet = normalize_sheet_number(match.group(1))
            sheet_title = re.sub(r"\s+", " ", match.group(2).strip())
            try:
                page = reader.get_destination_page_number(item) + 1
            except Exception:
                continue
            result.setdefault(sheet, (page, sheet_title))

    if isinstance(outline, list):
        walk(outline)
    return result


def _single_page_text(pdf: Path, page_number: int) -> str:
    try:
        reader = PdfReader(str(pdf))
        if page_number < 1 or page_number > len(reader.pages):
            return ""
        return reader.pages[page_number - 1].extract_text() or ""
    except Exception:
        return ""


def _title_words(title: str) -> set[str]:
    return {
        word
        for word in re.findall(r"[A-Z0-9]{3,}", title.upper())
        if word not in {"THE", "AND", "FOR", "PLAN", "LEVEL", "SHEET", "DETAILS"}
    }


def _score_sheet_page(target: SheetTarget, text: str) -> tuple[float, str]:
    upper = text.upper()
    lower = text.lower()
    sheet = target.sheet_number.upper()
    score = 0.0
    reasons: list[str] = []

    if sheet in upper:
        score += 0.45
        reasons.append("sheet number appears")
    if upper.count(sheet) >= 2:
        score += 0.12
        reasons.append("sheet number repeated")

    title_words = _title_words(target.sheet_title)
    matched_title_words = [word for word in title_words if word in upper]
    if matched_title_words:
        score += min(0.22, 0.04 * len(matched_title_words))
        reasons.append("title words match")

    if target.discipline and target.discipline.replace("_", " ") in lower:
        score += 0.06
        reasons.append("discipline text appears")

    if any(word in lower for word in SHEET_INDEX_WORDS):
        score -= 0.35
        reasons.append("possible sheet index")

    sheet_list_count = len(sheet_list_hits_from_text(text))
    if sheet_list_count >= 8:
        score -= 0.45
        reasons.append(f"sheet-list page with {sheet_list_count} entries")

    if any(word in lower for word in ("scale:", "key plan", "north arrow", "general notes")):
        score += 0.04
        reasons.append("drawing-page clues")

    return round(max(0.0, min(0.99, score)), 2), "; ".join(reasons) or "no strong text clue"


def _candidate_pdfs(project_folder: Path, targets: list[SheetTarget]) -> list[Path]:
    from_targets = [target.source_pdf for target in targets if str(target.source_pdf) and target.source_pdf.exists()]
    found = [pdf.path for pdf in find_pdf_candidates(project_folder, limit=12) if pdf.kind in {"drawings", "addendum"}]
    seen: set[str] = set()
    result: list[Path] = []
    for pdf in [*from_targets, *found]:
        key = str(pdf).lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(pdf)
    return result


def locate_sheet_pages(project_folder: Path, sheet_index_csv: Path, max_pages: int = 80, max_sheets: int = 12) -> list[LocatedSheet]:
    targets = _target_sheets(sheet_index_csv, max_sheets)
    if not targets:
        return []

    pdfs = _candidate_pdfs(project_folder, targets)
    outline_maps = {pdf: _outline_sheet_pages(pdf) for pdf in pdfs}
    pdf_texts: dict[Path, list[str]] = {}
    located: list[LocatedSheet] = []
    for target in targets:
        best: LocatedSheet | None = None
        for pdf in pdfs:
            outline_hit = outline_maps.get(pdf, {}).get(target.sheet_number)
            if outline_hit:
                page, outline_title = outline_hit
                text = _single_page_text(pdf, page)
                best = LocatedSheet(
                    target=SheetTarget(
                        discipline=target.discipline,
                        sheet_number=target.sheet_number,
                        sheet_title=target.sheet_title or outline_title,
                        confidence=max(target.confidence, 0.98),
                        source_pdf=target.source_pdf,
                    ),
                    pdf=pdf,
                    page=page,
                    page_score=0.98,
                    text_chars=len(text),
                    reason="PDF bookmark/outline matched sheet number",
                )
                break
            if pdf not in pdf_texts:
                pdf_texts[pdf] = _page_texts(pdf, max_pages=max_pages)
            texts = pdf_texts.get(pdf, [])
            for page_number, text in enumerate(texts, 1):
                score, reason = _score_sheet_page(target, text)
                if score <= 0:
                    continue
                candidate = LocatedSheet(
                    target=target,
                    pdf=pdf,
                    page=page_number,
                    page_score=score,
                    text_chars=len(text),
                    reason=reason,
                )
                if best is None or candidate.page_score > best.page_score:
                    best = candidate
        if best:
            located.append(best)
    located.sort(key=lambda item: (-item.page_score, DISCIPLINE_PRIORITY.get(item.target.discipline, 99), item.target.sheet_number))
    return located


def infer_region_hints(located: list[LocatedSheet], max_pages: int = 120) -> list[RegionHint]:
    page_text_cache: dict[tuple[Path, int], str] = {}
    regions: list[RegionHint] = []
    for sheet in located:
        key = (sheet.pdf, sheet.page)
        if key not in page_text_cache:
            page_text_cache[key] = _single_page_text(sheet.pdf, sheet.page)
        text = page_text_cache[key]
        lower = text.lower()
        counts = Counter()
        for region_type, keywords in REGION_KEYWORDS.items():
            for keyword in keywords:
                if keyword in lower:
                    counts[region_type] += 1

        for region_type, count in counts.items():
            if not count:
                continue
            confidence = min(0.95, 0.35 + count * 0.12 + sheet.page_score * 0.25)
            if region_type == "title_block":
                location = "usually right edge or bottom-right title block"
            elif region_type == "plan_area":
                location = "main central drawing area"
            elif region_type in {"legend", "schedule", "notes"}:
                location = "usually side panel, top area, or separate schedule/legend block"
            else:
                location = "unknown"
            regions.append(
                RegionHint(
                    sheet_number=sheet.target.sheet_number,
                    pdf=sheet.pdf,
                    page=sheet.page,
                    region_type=region_type,
                    confidence=round(confidence, 2),
                    location_hint=location,
                    reason=f"{count} keyword hit(s) on located sheet page",
                )
            )
    return regions


def render_located_sheets(located: list[LocatedSheet], out_dir: Path, max_render: int = 6) -> list[Path]:
    render_dir = out_dir / "rendered_sheets"
    render_dir.mkdir(parents=True, exist_ok=True)
    temp_dir = out_dir / "_render_tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    rendered: list[Path] = []
    pdftoppm = Path(r"C:\Users\namid\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\poppler\Library\bin\pdftoppm.exe")
    if not pdftoppm.exists():
        return rendered

    seen_pages: set[tuple[str, int]] = set()
    for sheet in located:
        key = (str(sheet.pdf).lower(), sheet.page)
        if key in seen_pages:
            continue
        seen_pages.add(key)
        if len(rendered) >= max_render:
            break
        safe_sheet = re.sub(r"[^A-Za-z0-9._-]+", "_", sheet.target.sheet_number).strip("_")
        prefix = render_dir / f"{safe_sheet}_p{sheet.page}"
        one_page_pdf = temp_dir / f"{safe_sheet}_p{sheet.page}.pdf"
        try:
            reader = PdfReader(str(sheet.pdf))
            writer = PdfWriter()
            writer.add_page(reader.pages[sheet.page - 1])
            with one_page_pdf.open("wb") as handle:
                writer.write(handle)
        except Exception:
            continue
        try:
            subprocess.run(
                [str(pdftoppm), "-png", "-r", "120", str(one_page_pdf), str(prefix)],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=60,
            )
        except Exception:
            continue
        matches = sorted(render_dir.glob(f"{prefix.name}-*.png"))
        rendered.extend(matches)
    return rendered


def write_drawing_intelligence_outputs(
    project_folder: Path,
    sheet_index_csv: Path,
    out_dir: Path,
    max_pages: int = 80,
    max_sheets: int = 12,
) -> tuple[Path, Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    located = locate_sheet_pages(project_folder, sheet_index_csv, max_pages=max_pages, max_sheets=max_sheets)
    regions = infer_region_hints(located, max_pages=max_pages)
    rendered = render_located_sheets(located, out_dir)

    page_map_csv = out_dir / "sheet_page_map.csv"
    regions_csv = out_dir / "drawing_regions.csv"
    dashboard_md = out_dir / "drawing_intelligence.md"

    with page_map_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["discipline", "sheet_number", "sheet_title", "pdf_page", "page_score", "reason", "text_chars", "pdf"])
        for sheet in located:
            writer.writerow(
                [
                    sheet.target.discipline,
                    sheet.target.sheet_number,
                    sheet.target.sheet_title,
                    sheet.page,
                    sheet.page_score,
                    sheet.reason,
                    sheet.text_chars,
                    str(sheet.pdf),
                ]
            )

    with regions_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["sheet_number", "pdf_page", "region_type", "confidence", "location_hint", "reason", "pdf"])
        for region in regions:
            writer.writerow(
                [
                    region.sheet_number,
                    region.page,
                    region.region_type,
                    region.confidence,
                    region.location_hint,
                    region.reason,
                    str(region.pdf),
                ]
            )

    by_discipline = Counter(sheet.target.discipline for sheet in located)
    by_region = Counter(region.region_type for region in regions)
    with dashboard_md.open("w", encoding="utf-8") as handle:
        handle.write(f"# Drawing Intelligence - {project_folder.name}\n\n")
        handle.write("This is Phase 2 starter output. It uses the Phase 1 sheet index plus existing PDF text/rendering tools to locate likely sheet pages and identify useful estimating regions.\n\n")
        handle.write("It does not perform final takeoff. It prepares the sheets for symbol detection and estimator review.\n\n")
        handle.write("## Summary\n\n")
        handle.write(f"- Project folder: `{project_folder}`\n")
        handle.write(f"- Sheet index: `{sheet_index_csv}`\n")
        handle.write(f"- Located sheet pages: {len(located)}\n")
        handle.write(f"- Region hints: {len(regions)}\n")
        handle.write(f"- Rendered previews: {len(rendered)}\n\n")

        handle.write("## Located disciplines\n\n")
        for discipline, count in by_discipline.most_common():
            handle.write(f"- {discipline}: {count}\n")
        if not by_discipline:
            handle.write("- No sheets were located. Run Project Intelligence first or review `electrical_sheet_index.csv`.\n")

        handle.write("\n## Region hints\n\n")
        for region_type, count in by_region.most_common():
            handle.write(f"- {region_type}: {count}\n")
        if not by_region:
            handle.write("- No region hints were found from searchable text.\n")

        handle.write("\n## Best located sheets\n\n")
        handle.write("| Sheet | Discipline | Page | Score | Title | Reason |\n")
        handle.write("|---|---|---:|---:|---|---|\n")
        for sheet in located[:30]:
            handle.write(
                f"| {sheet.target.sheet_number} | {sheet.target.discipline} | {sheet.page} | "
                f"{sheet.page_score:.2f} | {sheet.target.sheet_title} | {sheet.reason} |\n"
            )

        handle.write("\n## Outputs\n\n")
        handle.write("- `sheet_page_map.csv`\n")
        handle.write("- `drawing_regions.csv`\n")
        handle.write("- `rendered_sheets/` preview PNGs when rendering succeeds\n\n")
        handle.write("## Next estimator-agent step\n\n")
        handle.write("Use the located lighting sheets as the first target for symbol detection. Start with one symbol category, such as light fixtures, and compare detected counts against LiveCount/Accubid data when available.\n")

    return dashboard_md, page_map_csv, regions_csv
