from __future__ import annotations

import csv
import re
import shutil
import subprocess
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pypdf import PdfReader, PdfWriter

from work.estimating_agent.project_intake import (
    SHEET_INDEX_WORDS,
    SHEET_NUMBER,
    discipline_for,
    find_pdf_candidates,
    infer_title,
    normalize_sheet_number,
    sheet_list_hits_from_text,
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
RENDER_RELEVANT_WORDS = (
    "LIGHTING PLAN",
    "FIRE ALARM PLAN",
    "LUMINAIRE SCHEDULE",
    "FIXTURE SCHEDULE",
    "EXIT",
    "EMERGENCY",
    "SMOKE DETECTOR",
    "HORN/STROBE",
    "HORN STROBE",
)


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


@dataclass(frozen=True)
class RenderResult:
    images: list[Path]
    debug_lines: list[str]


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
    found = [pdf.path for pdf in find_pdf_candidates(project_folder, limit=12)]
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
        return _fallback_relevant_pages(project_folder, max_pages=max_pages, max_sheets=max_sheets)

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
    if not located:
        return _fallback_relevant_pages(project_folder, max_pages=max_pages, max_sheets=max_sheets)
    located.sort(key=lambda item: (-item.page_score, DISCIPLINE_PRIORITY.get(item.target.discipline, 99), item.target.sheet_number))
    return located


def _fallback_relevant_pages(project_folder: Path, max_pages: int = 80, max_sheets: int = 6) -> list[LocatedSheet]:
    """Pick renderable pages when a formal sheet index is missing or weak."""
    located: list[LocatedSheet] = []
    pdfs = [pdf.path for pdf in find_pdf_candidates(project_folder, limit=10)]
    for pdf in pdfs:
        for page_number, text in enumerate(_page_texts(pdf, max_pages=max_pages), 1):
            upper = text.upper()
            hits = [word for word in RENDER_RELEVANT_WORDS if word in upper]
            sheet_matches = [normalize_sheet_number(match.group(0)) for match in SHEET_NUMBER.finditer(text)]
            if not hits and not sheet_matches:
                continue
            sheet_number = sheet_matches[0] if sheet_matches else f"PAGE{page_number}"
            title = infer_title(text, sheet_number) or (" ".join(hits[:2]) if hits else "Relevant electrical page")
            discipline = discipline_for(sheet_number, title)
            if discipline == "other" and "FIRE ALARM" in upper:
                discipline = "fire_alarm"
            elif discipline == "other" and any(word in upper for word in ["LIGHTING", "LUMINAIRE", "EXIT", "EMERGENCY"]):
                discipline = "lighting"
            target = SheetTarget(
                discipline=discipline,
                sheet_number=sheet_number,
                sheet_title=title,
                confidence=0.55 if hits else 0.42,
                source_pdf=pdf,
            )
            located.append(
                LocatedSheet(
                    target=target,
                    pdf=pdf,
                    page=page_number,
                    page_score=0.62 if hits else 0.45,
                    text_chars=len(text),
                    reason=f"fallback relevant-page selection; hits={', '.join(hits[:5]) or 'sheet number only'}",
                )
            )
            if len(located) >= max_sheets:
                return located
    # Last-resort review fallback: if the input has drawing PDFs but searchable
    # text/sheet classification was weak, render the first few pages rather
    # than returning no sheets and forcing a placeholder marked PDF.
    for pdf in pdfs:
        try:
            reader = PdfReader(str(pdf))
            page_count = min(len(reader.pages), 3)
        except Exception:
            continue
        for page_number in range(1, page_count + 1):
            target = SheetTarget(
                discipline="review_required",
                sheet_number=f"PAGE{page_number}",
                sheet_title="First pages rendered as fallback review candidates",
                confidence=0.25,
                source_pdf=pdf,
            )
            located.append(
                LocatedSheet(
                    target=target,
                    pdf=pdf,
                    page=page_number,
                    page_score=0.25,
                    text_chars=len(_single_page_text(pdf, page_number)),
                    reason="last-resort first-pages fallback because no relevant sheet text was found",
                )
            )
            if len(located) >= max_sheets:
                return located
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


def render_located_sheets(located: list[LocatedSheet], out_dir: Path, max_render: int = 6) -> RenderResult:
    render_dir = out_dir / "rendered_sheets"
    render_dir.mkdir(parents=True, exist_ok=True)
    temp_dir = out_dir / "_render_tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    rendered: list[Path] = []
    debug: list[str] = []
    pdftoppm = _find_pdftoppm()
    debug.append(f"pdftoppm found: {pdftoppm if pdftoppm else 'no'}")
    pymupdf_available = _pymupdf_available()
    debug.append(f"PyMuPDF available: {'yes' if pymupdf_available else 'no'}")
    if not located:
        debug.append("No located sheets/pages were provided to renderer.")

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
        debug.append(f"Render attempt: sheet={sheet.target.sheet_number}, page={sheet.page}, pdf={sheet.pdf}")
        try:
            reader = PdfReader(str(sheet.pdf))
            writer = PdfWriter()
            writer.add_page(reader.pages[sheet.page - 1])
            with one_page_pdf.open("wb") as handle:
                writer.write(handle)
        except Exception as exc:
            debug.append(f"  one-page PDF creation failed: {exc}")
            continue
        rendered_before = len(rendered)
        if pdftoppm:
            try:
                subprocess.run(
                    [str(pdftoppm), "-png", "-r", "120", str(one_page_pdf), str(prefix)],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    timeout=60,
                    text=True,
                )
                debug.append("  pdftoppm render succeeded")
            except Exception as exc:
                debug.append(f"  pdftoppm render failed: {exc}")
        matches = sorted(render_dir.glob(f"{prefix.name}-*.png"))
        if matches:
            rendered.extend(matches)
        elif _render_page_with_pymupdf(sheet.pdf, sheet.page, render_dir / f"{prefix.name}-1.png"):
            rendered.append(render_dir / f"{prefix.name}-1.png")
            debug.append("  PyMuPDF fallback render succeeded")
        elif not pdftoppm and not pymupdf_available:
            debug.append("  no renderer available: pdftoppm not found and PyMuPDF not installed")
        else:
            debug.append("  selected page failed to render with all available methods")
        if len(rendered) == rendered_before:
            debug.append("  no image created for this page")
    debug.append(f"Rendered page images created: {len(rendered)}")
    return RenderResult(images=rendered, debug_lines=debug)


def _pymupdf_available() -> bool:
    try:
        import fitz  # type: ignore
    except Exception:
        return False
    return True


def _render_page_with_pymupdf(pdf: Path, page_number: int, out_png: Path) -> bool:
    try:
        import fitz  # type: ignore

        doc = fitz.open(str(pdf))
        page = doc.load_page(page_number - 1)
        pix = page.get_pixmap(matrix=fitz.Matrix(1.6, 1.6), alpha=False)
        pix.save(str(out_png))
        doc.close()
        return out_png.exists()
    except Exception:
        return False


def _find_pdftoppm() -> Path | None:
    """Find Poppler without hardcoding one machine path."""
    candidates = [
        Path.home() / ".cache" / "codex-runtimes" / "codex-primary-runtime" / "dependencies" / "native" / "poppler" / "Library" / "bin" / "pdftoppm.exe",
        Path.home() / ".cache" / "codex-runtimes" / "codex-primary-runtime" / "dependencies" / "native" / "poppler" / "bin" / "pdftoppm.exe",
        Path.home() / ".cache" / "codex-runtimes" / "codex-primary-runtime" / "dependencies" / "bin" / "pdftoppm.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    from_path = shutil.which("pdftoppm.exe") or shutil.which("pdftoppm")
    if from_path:
        return Path(from_path)
    return None


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
    render_result = render_located_sheets(located, out_dir)
    rendered = render_result.images

    page_map_csv = out_dir / "sheet_page_map.csv"
    regions_csv = out_dir / "drawing_regions.csv"
    dashboard_md = out_dir / "drawing_intelligence.md"
    render_debug_md = out_dir / "render_debug.md"

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
    pdfs_discovered = find_pdf_candidates(project_folder, limit=20)
    with render_debug_md.open("w", encoding="utf-8") as handle:
        handle.write("# Render debug\n\n")
        handle.write(f"- Timestamp: {datetime.now().isoformat(timespec='seconds')}\n")
        handle.write(f"- Input project path: `{project_folder}`\n")
        handle.write(f"- Input type: {'single PDF' if project_folder.is_file() else 'folder'}\n")
        handle.write(f"- PDFs discovered: {len(pdfs_discovered)}\n")
        for candidate in pdfs_discovered[:20]:
            handle.write(f"  - {candidate.kind}: `{candidate.path}`\n")
        handle.write(f"- Selected sheets/pages: {len(located)}\n")
        for sheet in located[:30]:
            handle.write(f"  - {sheet.target.sheet_number} page {sheet.page} from `{sheet.pdf}`: {sheet.reason}\n")
        handle.write(f"- Rendered page images created: {len(rendered)}\n\n")
        handle.write("## Render attempts\n\n")
        for line in render_result.debug_lines:
            handle.write(f"- {line}\n")
        if not rendered:
            if not located:
                reason = "No relevant lighting or fire alarm sheets selected"
            elif not _find_pdftoppm() and not _pymupdf_available():
                reason = "pdftoppm not found and PyMuPDF not installed"
            else:
                reason = "selected pages failed to render"
            handle.write(f"\n## Placeholder reason if needed\n\n- {reason}\n")
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
        if not rendered:
            handle.write("- Render warning: no page images were created. See `render_debug.md`.\n\n")

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
        handle.write("- `render_debug.md`\n")
        handle.write("- `rendered_sheets/` preview PNGs when rendering succeeds\n\n")
        handle.write("## Next estimator-agent step\n\n")
        handle.write("Use the located lighting sheets as the first target for symbol detection. Start with one symbol category, such as light fixtures, and compare detected counts against LiveCount/Accubid data when available.\n")

    return dashboard_md, page_map_csv, regions_csv
