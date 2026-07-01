from __future__ import annotations

import csv
import math
import os
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from pypdf import PdfReader
from reportlab.lib.pagesizes import landscape
from reportlab.pdfgen import canvas


@dataclass(frozen=True)
class FixtureCandidate:
    sheet_number: str
    source_image: Path
    x: int
    y: int
    width: int
    height: int
    category: str
    tag: str
    symbol_type: str
    confidence: float
    reason: str
    review_category: str

    @property
    def cx(self) -> float:
        return self.x + self.width / 2

    @property
    def cy(self) -> float:
        return self.y + self.height / 2


@dataclass(frozen=True)
class SymbolTemplate:
    source_file: Path
    page_number: int
    category: str
    tag: str
    description: str
    template_image_path: str
    x: int
    y: int
    width: int
    height: int
    confidence: float
    extraction_method: str


@dataclass(frozen=True)
class RcpRectangleCandidate:
    source_file: Path
    page_number: int
    sheet_name: str
    x: int
    y: int
    width: int
    height: int
    aspect_ratio: float
    area: int
    fill_ratio: float
    repeated_size_score: float
    accepted: bool
    rejection_reason: str
    confidence: float
    repeated_size_group: str = ""
    group_count: int = 0
    accepted_by_grouping: bool = False


def _sheet_from_image_name(path: Path) -> str:
    match = re.match(r"([A-Za-z0-9.]+)_p\d+", path.stem)
    return match.group(1).upper() if match else path.stem.upper()


LABEL_TOKEN = re.compile(
    r"^(?:[A-Z]{1,3}\d{1,2}[A-Z]?|B|EM\d?[A-Z]?|EMS|EMER|EXIT|EX|X\d*[A-Z]?|SD|HD|DD|PS|PULL|HS|H/S|FACP|FAAP|NAC|MM|MON|CM|CTRL)(?:[a-z])?$",
    re.IGNORECASE,
)
LABEL_NOISE = {"OS", "VS", "J", "A", "C", "D", "E", "N", "S", "T"}
SINGLE_LETTER_LIGHTING_TAGS = {"B"}
FIRE_ALARM_TOKENS = {"SD", "HD", "DD", "PS", "PULL", "HS", "H/S", "FACP", "FAAP", "NAC", "MM", "MON", "CM", "CTRL"}
NON_PLAN_HEADING = re.compile(
    r"\b(?:LEGEND|SYMBOL\s+LEGEND|GENERAL\s+NOTES?|SHEET\s+NOTES?|LIGHTING\s+NOTES?|FIRE\s+ALARM\s+NOTES?|FIXTURE\s+SCHEDULE|LUMINAIRE\s+SCHEDULE|FIRE\s+ALARM\s+DEVICE\s+SCHEDULE|SHEET\s+INDEX|TITLE\s+BLOCK|EQUIPMENT\s+LIST|PROJECT\s+INFORMATION|SUMMARY\s+CONTACTS|HEADWALL\s+EQUIPMENT\s+EXAMPLES|OPTIONS\s+FOR\s+PRICING\s+PACKAGE|CURRICULUM|ADMINISTRATIVE\s+REQUIREMENTS)\b",
    re.IGNORECASE,
)
NON_TAKEOFF_PAGE_TEXT = re.compile(
    r"\b(?:EQUIPMENT\s+LIST|EXISTING\s+SPACE\s*-\s*INTERIOR\s+PHOTOS|PROJECT\s+INFORMATION|SUMMARY\s+CONTACTS|HEADWALL\s+EQUIPMENT\s+EXAMPLES|OPTIONS\s+FOR\s+PRICING\s+PACKAGE|CONTACTS|CURRICULUM|ADMINISTRATIVE\s+REQUIREMENTS|MATERIAL\s+PHOTOS|INTERIOR\s+PHOTOS)\b",
    re.IGNORECASE,
)
NON_PLAN_INLINE_TEXT = re.compile(
    r"(?:[A-Z]:\\|\\USERS\\|\.RVT\b|\.DWG\b|MEP\s+MODEL|REVIT|PROJECT\s*#|DRAWN\s+BY|CHECKED\s+BY|LICENSE\s+INFORMATION)",
    re.IGNORECASE,
)
LEGEND_PAGE_TEXT = re.compile(
    r"\b(?:SYMBOL\s+LEGEND|ELECTRICAL\s+LEGEND|LIGHTING\s+LEGEND|FIXTURE\s+LEGEND|LUMINAIRE\s+SCHEDULE|LIGHT\s+FIXTURE\s+SCHEDULE|DEVICE\s+LEGEND|FIRE\s+ALARM\s+LEGEND|FIRE\s+ALARM\s+DEVICE\s+SCHEDULE|POWER\s+LEGEND|TELE/DATA\s+LEGEND)\b",
    re.IGNORECASE,
)
RCP_PAGE_TEXT = re.compile(r"\b(?:REFLECTED\s+CEILING\s+PLAN|CEILING\s+PLAN|RCP)\b", re.IGNORECASE)


def _review_category_for_label(label: str) -> str:
    """Separate strong fixture labels from tags that should stay visible but not trusted blindly."""
    upper = label.upper()
    if upper in {"EXIT", "EX", "X"} or upper.startswith("EM") or upper == "EMS":
        return "likely_fixture_tag"
    if upper in FIRE_ALARM_TOKENS:
        return "likely_device_tag"
    if re.match(r"^(?:[A-Z]{1,3}\d{1,2}[A-Z]?|B)$", upper):
        return "likely_fixture_tag"
    if re.match(r"^X\d*[A-Z]?$", upper):
        return "possible_fixture_tag"
    return "possible_fixture_tag"


def _classify_label(label: str, sheet_number: str, sheet_text: str) -> tuple[str, str, float, str] | None:
    """Map drawing label tokens into estimator-facing categories.

    This intentionally stays generic: it reads tags from the drawing/schedule
    text and sheet context, but does not hardcode expected quantities or
    coordinates for any test case.
    """
    upper = label.upper()
    context = f"{sheet_number} {sheet_text}".upper()
    fire_context = any(word in context for word in ["FIRE ALARM", "FA-", "FA1", "FA2", "SMOKE", "HEAT", "HORN", "STROBE", "PULL", "FACP", "FAAP"])
    lighting_context = any(word in context for word in ["LIGHTING", "LIGHT FIXTURE", "LUMINAIRE", "REFLECTED CEILING", "CEILING PLAN", "RCP"])
    if upper in FIRE_ALARM_TOKENS:
        return "fire_alarm_device", upper, 0.86, "embedded PDF fire alarm device label positioned on plan"
    if upper in {"EXIT", "EX"} or re.match(r"^X\d*[A-Z]?$", upper):
        return "exit_sign", upper, 0.86, "embedded PDF exit sign label positioned on plan"
    if upper.startswith("EM") or upper in {"EMS", "EMER"}:
        return "emergency_light", upper, 0.86, "embedded PDF emergency light label positioned on plan"
    if re.match(r"^(?:[A-Z]{1,3}\d{1,2}[A-Z]?|B)$", upper):
        if fire_context and upper in {"H1", "H2", "S1", "S2"}:
            return "fire_alarm_device", upper, 0.80, "embedded PDF fire alarm device-like label positioned on fire alarm plan"
        if not lighting_context:
            return None
        if len(upper) == 1 and upper not in SINGLE_LETTER_LIGHTING_TAGS:
            return None
        return "light_fixture", upper, 0.84 if len(upper) == 1 else 0.86, "embedded PDF light fixture label positioned on plan"
    return None


def _extract_label_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for raw in re.findall(r"[A-Za-z][A-Za-z0-9/]{0,5}", text):
        clean = raw.strip().upper()
        if LABEL_TOKEN.match(clean):
            tokens.append(clean)
    return tokens


def _one_page_pdf_for_image(image_path: Path) -> Path | None:
    # Phase 2 renders from sibling _render_tmp/E1.1_p127.pdf to
    # rendered_sheets/E1.1_p127-1.png.
    base = re.sub(r"-\d+$", "", image_path.stem)
    candidate = image_path.parent.parent / "_render_tmp" / f"{base}.pdf"
    return candidate if candidate.exists() else None


def _category_from_template_text(text: str) -> tuple[str, str]:
    upper = text.upper()
    if "EXIT" in upper:
        return "exit_sign", "EXIT"
    if "EMER" in upper or re.search(r"\bEM\b", upper):
        return "emergency_light", "EM"
    if any(token in upper for token in ["SMOKE", "HEAT", "HORN", "STROBE", "PULL", "FACP", "FAAP"]):
        if "SMOKE" in upper:
            return "fire_alarm_device", "SD"
        if "HORN" in upper or "STROBE" in upper:
            return "fire_alarm_device", "HS"
        return "fire_alarm_device", "FA_DEVICE"
    if "2X4" in upper or "2 X 4" in upper or "LED" in upper or "LUMINAIRE" in upper or "FIXTURE" in upper:
        return "light_fixture", "2x4_LED" if ("2X4" in upper or "2 X 4" in upper) else "LIGHT_FIXTURE"
    if "RECEPTACLE" in upper:
        return "receptacle", "DUPLEX"
    if "DATA" in upper or "TELE" in upper:
        return "tele_data", "DATA"
    return "other_reference_item", "REFERENCE"


def _candidate_project_pdfs(project_folder: Path | None, manifest: dict[str, dict[str, str]]) -> list[Path]:
    paths: list[Path] = []
    if project_folder:
        if project_folder.is_file() and project_folder.suffix.lower() == ".pdf":
            paths.append(project_folder)
        elif project_folder.is_dir():
            paths.extend(path for path in project_folder.rglob("*.pdf") if path.is_file())
    for row in manifest.values():
        pdf = Path(row.get("pdf", ""))
        if pdf.exists():
            paths.append(pdf)
    seen: set[str] = set()
    unique: list[Path] = []
    for path in paths:
        key = str(path).lower()
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique[:20]


def _extract_symbol_templates(project_folder: Path | None, manifest: dict[str, dict[str, str]], out_dir: Path) -> list[SymbolTemplate]:
    template_dir = out_dir / ".." / "symbol_templates"
    template_dir = template_dir.resolve()
    template_dir.mkdir(parents=True, exist_ok=True)
    project_library_dir = out_dir / ".." / "project_symbol_library"
    project_library_dir = project_library_dir.resolve()
    project_templates_dir = project_library_dir / "templates"
    project_templates_dir.mkdir(parents=True, exist_ok=True)
    templates: list[SymbolTemplate] = []
    project_templates: list[SymbolTemplate] = []
    for pdf in _candidate_project_pdfs(project_folder, manifest):
        try:
            reader = PdfReader(str(pdf))
        except Exception:
            continue
        for page_index, page in enumerate(reader.pages[:120], 1):
            try:
                text = page.extract_text() or ""
            except Exception:
                continue
            if not LEGEND_PAGE_TEXT.search(text):
                continue
            lines = [re.sub(r"\s+", " ", line.strip()) for line in text.splitlines() if line.strip()]
            for line in lines:
                category, tag = _category_from_template_text(line)
                if category == "other_reference_item":
                    continue
                template = SymbolTemplate(
                    source_file=pdf,
                    page_number=page_index,
                    category=category,
                    tag=tag,
                    description=line[:180],
                    template_image_path="",
                    x=0,
                    y=0,
                    width=0,
                    height=0,
                    confidence=0.55,
                    extraction_method="legend_text",
                )
                project_templates.append(template)
                templates.append(template)
    private_library_csv = _default_private_symbol_library_csv()
    if private_library_csv:
        templates.extend(_library_symbol_templates("private_company_library", private_library_csv))
    templates.extend(_library_symbol_templates("starter_symbol_taxonomy", Path(__file__).parent / "symbol_library" / "starter" / "symbols.csv"))
    csv_path = template_dir / "symbol_templates.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["source_file", "page_number", "category", "tag", "description", "template_image_path", "x", "y", "width", "height", "confidence", "extraction_method"])
        for item in templates:
            writer.writerow([str(item.source_file), item.page_number, item.category, item.tag, item.description, item.template_image_path, item.x, item.y, item.width, item.height, item.confidence, item.extraction_method])
    project_csv = project_library_dir / "project_symbols.csv"
    with project_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["source_file", "page_number", "category", "tag", "name", "description", "aliases", "template_image_path", "x", "y", "width", "height", "confidence", "extraction_method"])
        for item in project_templates:
            writer.writerow([str(item.source_file), item.page_number, item.category, item.tag, item.tag, item.description, item.tag, item.template_image_path, item.x, item.y, item.width, item.height, item.confidence, item.extraction_method])
    return templates


def _library_symbol_templates(source_label: str, csv_path: Path) -> list[SymbolTemplate]:
    if not csv_path.exists():
        return []
    rows: list[SymbolTemplate] = []
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for index, row in enumerate(reader, 1):
            category = row.get("category", "").strip()
            tag = (row.get("symbol_id") or row.get("tag") or row.get("name") or f"symbol_{index}").strip()
            if not category:
                continue
            try:
                confidence = float(row.get("confidence_base") or row.get("confidence") or 0.45)
            except ValueError:
                confidence = 0.45
            rows.append(
                SymbolTemplate(
                    source_file=csv_path,
                    page_number=0,
                    category=category,
                    tag=tag,
                    description=(row.get("description") or row.get("name") or "").strip(),
                    template_image_path=(row.get("template_image_path") or "").strip(),
                    x=0,
                    y=0,
                    width=0,
                    height=0,
                    confidence=confidence,
                    extraction_method=source_label,
                )
            )
    return rows


def _default_private_symbol_library_csv() -> Path | None:
    configured = os.environ.get("ESTIMATOR_SYMBOL_LIBRARY_DIR")
    if configured:
        candidate = Path(configured) / "symbols.csv"
        return candidate if candidate.exists() else None
    for candidate in (
        Path("C:/EstimatorAgentData/symbol_library/company_symbols_zip2_v1/symbols.csv"),
        Path("C:/EstimatorAgentData/symbol_library/company_symbols_zip2/symbols.csv"),
        Path("C:/EstimatorAgentData/symbol_library/company_symbols/symbols.csv"),
    ):
        if candidate.exists():
            return candidate
    return None


def _dedupe_label_candidates(candidates: list[FixtureCandidate], distance: float = 6.0) -> list[FixtureCandidate]:
    kept: list[FixtureCandidate] = []
    for cand in sorted(candidates, key=lambda c: (c.sheet_number, c.y, c.x, -len(c.symbol_type), -c.confidence)):
        duplicate = False
        cand_item = cand.symbol_type
        replacement_index: int | None = None
        for index, old in enumerate(kept):
            if old.source_image != cand.source_image:
                continue
            if old.tag != cand.tag:
                continue
            same_item_nearby = old.symbol_type == cand_item and math.hypot(cand.cx - old.cx, cand.cy - old.cy) <= distance
            overlapping_text = _overlap_ratio(cand, old) >= 0.55
            if same_item_nearby or overlapping_text:
                duplicate = True
                if len(cand.symbol_type) > len(old.symbol_type):
                    replacement_index = index
                break
        if not duplicate:
            kept.append(cand)
        elif replacement_index is not None:
            kept[replacement_index] = cand
    return kept


def _overlap_ratio(a: FixtureCandidate, b: FixtureCandidate) -> float:
    left = max(a.x, b.x)
    top = max(a.y, b.y)
    right = min(a.x + a.width, b.x + b.width)
    bottom = min(a.y + a.height, b.y + b.height)
    if right <= left or bottom <= top:
        return 0.0
    overlap = (right - left) * (bottom - top)
    smaller = min(a.width * a.height, b.width * b.height)
    return overlap / max(1, smaller)


def _text_exclusion_zones(
    text_lines: list[tuple[str, int, int, int, int]],
    image_w: int,
    image_h: int,
) -> list[tuple[int, int, int, int, str]]:
    zones: list[tuple[int, int, int, int, str]] = []
    for text, x, y, box_w, box_h in text_lines:
        upper = text.upper()
        if not NON_PLAN_HEADING.search(upper):
            continue
        # Exclude a modest block below headings. For sidebars/title blocks,
        # extend to the right edge. For notes/legends in the body, keep the
        # zone local so normal plan tags elsewhere still count.
        if x > image_w * 0.55:
            left = max(0, x - 18)
            right = image_w
        else:
            left = max(0, x - 24)
            right = min(image_w, x + max(260, box_w + 220))
        top = max(0, y - box_h - 10)
        bottom = min(image_h, y + max(70, int(image_h * 0.20)))
        zones.append((left, top, right, bottom, upper[:40]))
    return zones


def _inside_exclusion_zone(x: int, y: int, zones: list[tuple[int, int, int, int, str]]) -> bool:
    return any(left <= x <= right and top <= y <= bottom for left, top, right, bottom, _reason in zones)


def _normalize_label_box_to_plan(
    x: int,
    y: int,
    box_w: int,
    box_h: int,
    image_w: int,
    image_h: int,
    crop_bounds: tuple[int, int, int, int],
) -> tuple[int, int, str] | None:
    left, top, right, bottom = crop_bounds

    def inside(test_x: int, test_y: int) -> bool:
        cx = test_x + box_w // 2
        cy = test_y + box_h // 2
        return left <= cx <= right and top <= cy <= bottom

    if inside(x, y):
        return x, y, ""
    # Some Revit/PDF text runs expose plan labels with y values one or more
    # rendered-page heights outside the image even though the rendered drawing
    # shows the label in the plan. Only wrap coordinate text back onto the page
    # when the resulting label lands inside the protected plan crop.
    wrapped_x = x % image_w if image_w else x
    wrapped_y = y % image_h if image_h else y
    if (wrapped_x, wrapped_y) != (x, y) and inside(wrapped_x, wrapped_y):
        return wrapped_x, wrapped_y, "pdf_text_y_wrapped_to_rendered_page"
    return None


def _pdf_label_candidates(
    image_path: Path,
    pdf_path: Path,
    label_debug_rows: list[dict[str, object]] | None = None,
) -> list[FixtureCandidate]:
    image = Image.open(image_path)
    image_w, image_h = image.size
    sheet_number = _sheet_from_image_name(image_path)
    candidates: list[FixtureCandidate] = []
    try:
        reader = PdfReader(str(pdf_path))
        page = reader.pages[0]
        page_w = float(page.mediabox.width)
        page_h = float(page.mediabox.height)
    except Exception:
        return []

    scale_x = image_w / page_w
    scale_y = image_h / page_h
    left, top, right, bottom = _plan_crop_bounds(image_w, image_h)
    text_lines: list[tuple[str, int, int, int, int]] = []
    raw_label_hits: list[tuple[str, int, int, int, int, str, str]] = []

    def visitor(text: str, cm, tm, font, size) -> None:
        clean_text = re.sub(r"\s+", " ", text.strip())
        if clean_text:
            line_x = int(float(tm[4]) * scale_x)
            line_y = int((page_h - float(tm[5])) * scale_y)
            line_w = max(12, int(len(clean_text) * float(size) * scale_x * 0.55))
            line_h = max(8, int(float(size) * scale_y * 1.25))
            text_lines.append((clean_text, line_x, line_y, line_w, line_h))
        for clean in _extract_label_tokens(clean_text):
            if NON_PLAN_INLINE_TEXT.search(clean_text):
                continue
            x = int(float(tm[4]) * scale_x)
            y = int((page_h - float(tm[5])) * scale_y)
            box_w = max(16, int(len(clean) * float(size) * scale_x * 0.62))
            box_h = max(10, int(float(size) * scale_y * 1.25))
            category_guess = ""
            confidence = 0.0
            classified = _classify_label(clean, sheet_number, "")
            if classified:
                category_guess, _tag, confidence, _reason = classified
            normalized_box = _normalize_label_box_to_plan(x, max(0, y - box_h), box_w, box_h, image_w, image_h, (left, top, right, bottom))
            if normalized_box is None:
                if label_debug_rows is not None:
                    label_debug_rows.append(
                        {
                            "source_file": str(image_path),
                            "page_number": "",
                            "sheet_name": sheet_number,
                            "raw_text": clean_text,
                            "normalized_tag": clean,
                            "x": x,
                            "y": max(0, y - box_h),
                            "width": box_w,
                            "height": box_h,
                            "category_guess": category_guess,
                            "accepted": "no",
                            "rejection_reason": "outside_plan_crop",
                            "confidence": confidence,
                        }
                    )
                continue
            normalized_x, normalized_y, normalization_note = normalized_box
            if clean in LABEL_NOISE and clean not in SINGLE_LETTER_LIGHTING_TAGS:
                if label_debug_rows is not None:
                    label_debug_rows.append(
                        {
                            "source_file": str(image_path),
                            "page_number": "",
                            "sheet_name": sheet_number,
                            "raw_text": clean_text,
                            "normalized_tag": clean,
                            "x": x,
                            "y": max(0, y - box_h),
                            "width": box_w,
                            "height": box_h,
                            "category_guess": category_guess,
                            "accepted": "no",
                            "rejection_reason": "label_noise",
                            "confidence": confidence,
                        }
                    )
                continue
            raw_label_hits.append((clean, normalized_x, normalized_y, box_w, box_h, clean_text, normalization_note))

    try:
        page.extract_text(visitor_text=visitor)
    except Exception:
        return []
    sheet_text = " ".join(text for text, *_rest in text_lines)
    if NON_TAKEOFF_PAGE_TEXT.search(sheet_text):
        return []
    zones = _text_exclusion_zones(text_lines, image_w, image_h)
    for clean, x, y, box_w, box_h, raw_text, normalization_note in raw_label_hits:
        if _inside_exclusion_zone(x + box_w // 2, y + box_h // 2, zones):
            if label_debug_rows is not None:
                label_debug_rows.append(
                    {
                        "source_file": str(image_path),
                        "page_number": "",
                        "sheet_name": sheet_number,
                        "raw_text": raw_text,
                        "normalized_tag": clean,
                        "x": x,
                        "y": y,
                        "width": box_w,
                        "height": box_h,
                        "category_guess": "",
                        "accepted": "no",
                        "rejection_reason": "non_plan_heading_zone",
                        "confidence": "",
                    }
                )
            continue
        classified = _classify_label(clean, sheet_number, sheet_text)
        if not classified:
            if label_debug_rows is not None:
                label_debug_rows.append(
                    {
                        "source_file": str(image_path),
                        "page_number": "",
                        "sheet_name": sheet_number,
                        "raw_text": raw_text,
                        "normalized_tag": clean,
                        "x": x,
                        "y": y,
                        "width": box_w,
                        "height": box_h,
                        "category_guess": "",
                        "accepted": "no",
                        "rejection_reason": "not_fixture_or_supported_device_label",
                        "confidence": "",
                    }
                )
            continue
        category, tag, confidence, reason = classified
        if label_debug_rows is not None:
            label_debug_rows.append(
                {
                    "source_file": str(image_path),
                    "page_number": "",
                    "sheet_name": sheet_number,
                    "raw_text": raw_text,
                    "normalized_tag": tag,
                    "x": x,
                    "y": y,
                    "width": box_w,
                    "height": box_h,
                    "category_guess": category,
                    "accepted": "yes",
                    "rejection_reason": normalization_note,
                    "confidence": confidence,
                }
            )
        candidates.append(
            FixtureCandidate(
                sheet_number=sheet_number,
                source_image=image_path,
                x=x,
                y=y,
                width=box_w,
                height=box_h,
                category=category,
                tag=tag,
                symbol_type="text_label_match",
                confidence=confidence,
                reason=reason,
                review_category=_review_category_for_label(clean),
            )
        )
    if zones:
        candidates = [cand for cand in candidates if not _inside_exclusion_zone(cand.cx, cand.cy, zones)]
    return _dedupe_label_candidates(candidates)


def _plan_crop_bounds(width: int, height: int) -> tuple[int, int, int, int]:
    """Estimator-oriented default crop.

    Most plotted sheets have a right title block and large top whitespace. This
    crop keeps the plan area and ignores the title block/notes as much as
    possible without needing a full layout engine yet.
    """
    left = int(width * 0.02)
    top = int(height * 0.18)
    right = int(width * 0.84)
    bottom = int(height * 0.985)
    return left, top, right, bottom


def _integral_image(mask: np.ndarray) -> np.ndarray:
    return mask.astype(np.int32).cumsum(axis=0).cumsum(axis=1)


def _rect_sum(ii: np.ndarray, x: int, y: int, w: int, h: int) -> int:
    x2 = x + w - 1
    y2 = y + h - 1
    total = ii[y2, x2]
    if x > 0:
        total -= ii[y2, x - 1]
    if y > 0:
        total -= ii[y - 1, x2]
    if x > 0 and y > 0:
        total += ii[y - 1, x - 1]
    return int(total)


def _dilate(mask: np.ndarray, iterations: int = 1) -> np.ndarray:
    out = mask
    for _ in range(iterations):
        padded = np.pad(out, 1, mode="constant", constant_values=False)
        out = (
            padded[1:-1, 1:-1]
            | padded[:-2, 1:-1]
            | padded[2:, 1:-1]
            | padded[1:-1, :-2]
            | padded[1:-1, 2:]
        )
    return out


def _connected_components(mask: np.ndarray, max_components: int = 20000) -> list[tuple[int, int, int, int, int]]:
    """Return component bboxes as x, y, w, h, area."""
    h, w = mask.shape
    visited = np.zeros(mask.shape, dtype=bool)
    components: list[tuple[int, int, int, int, int]] = []
    ys, xs = np.nonzero(mask)
    for start_y, start_x in zip(ys, xs):
        if visited[start_y, start_x]:
            continue
        stack = [(int(start_x), int(start_y))]
        visited[start_y, start_x] = True
        min_x = max_x = int(start_x)
        min_y = max_y = int(start_y)
        area = 0
        while stack:
            x, y = stack.pop()
            area += 1
            if x < min_x:
                min_x = x
            if x > max_x:
                max_x = x
            if y < min_y:
                min_y = y
            if y > max_y:
                max_y = y
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if nx < 0 or ny < 0 or nx >= w or ny >= h:
                    continue
                if visited[ny, nx] or not mask[ny, nx]:
                    continue
                visited[ny, nx] = True
                stack.append((nx, ny))
        components.append((min_x, min_y, max_x - min_x + 1, max_y - min_y + 1, area))
        if len(components) >= max_components:
            break
    return components


def _component_candidates(mask: np.ndarray, crop_offset: tuple[int, int], source_image: Path, sheet_number: str) -> list[FixtureCandidate]:
    """Find likely fixture symbols using connected-component geometry."""
    ox, oy = crop_offset
    candidates: list[FixtureCandidate] = []

    # Tiny dilation joins rectangle line segments without growing text too much.
    work = _dilate(mask, iterations=1)
    components = _connected_components(work)
    raw_ii = _integral_image(mask)

    for x, y, w, h, area in components:
        if w < 6 or h < 3 or w > 90 or h > 36:
            continue
        bbox_area = w * h
        fill = area / max(1, bbox_area)
        aspect = w / max(1, h)
        if fill < 0.08 or fill > 0.75:
            continue

        is_linear = 2.2 <= aspect <= 14 and 7 <= w <= 90 and 3 <= h <= 18
        is_square = 0.65 <= aspect <= 1.55 and 7 <= w <= 28 and 7 <= h <= 28
        if not (is_linear or is_square):
            continue

        # Reject most text letters: symbols tend to have dark pixels on both
        # long borders, while letters cluster irregularly.
        top = _rect_sum(raw_ii, x, y, w, 1)
        bottom = _rect_sum(raw_ii, x, y + h - 1, w, 1)
        left = _rect_sum(raw_ii, x, y, 1, h)
        right = _rect_sum(raw_ii, x + w - 1, y, 1, h)
        border = top + bottom + left + right
        raw_dark = _rect_sum(raw_ii, x, y, w, h)
        border_ratio = border / max(1, raw_dark)
        if is_linear and border_ratio < 0.12:
            continue
        if is_square and border_ratio < 0.16:
            continue

        symbol_type = "linear_fixture" if is_linear else "square_fixture"
        confidence = 0.42
        if is_linear:
            confidence += min(0.22, (aspect - 2.2) * 0.03)
        if is_square:
            confidence += 0.12
        confidence += min(0.22, border_ratio * 0.45)
        confidence -= min(0.18, abs(fill - 0.28) * 0.35)
        confidence = max(0.05, min(0.93, confidence))
        candidates.append(
            FixtureCandidate(
                sheet_number=sheet_number,
                source_image=source_image,
                x=x + ox,
                y=y + oy,
                width=w,
                height=h,
                category="light_fixture",
                tag=symbol_type,
                symbol_type=symbol_type,
                confidence=round(confidence, 2),
                reason=f"connected-component fixture candidate; aspect={aspect:.2f}; fill={fill:.2f}; border={border_ratio:.2f}",
                review_category="visual_candidate",
            )
        )

    return candidates


def _rcp_rectangle_candidates(image_path: Path, manifest_row: dict[str, str] | None = None) -> tuple[list[FixtureCandidate], list[RcpRectangleCandidate]]:
    pdf_path = _one_page_pdf_for_image(image_path)
    page_text = ""
    if pdf_path:
        try:
            page_text = PdfReader(str(pdf_path)).pages[0].extract_text() or ""
        except Exception:
            page_text = ""
    manifest_text = " ".join((manifest_row or {}).values())
    if not RCP_PAGE_TEXT.search(f"{page_text} {manifest_text}"):
        return [], []

    image = Image.open(image_path).convert("L")
    arr = np.asarray(image)
    width, height = image.size
    left = int(width * 0.04)
    top = int(height * 0.12)
    right = int(width * 0.84)
    bottom = int(height * 0.90)
    crop = arr[top:bottom, left:right]
    mask = crop < 120
    work = _dilate(mask, iterations=1)
    components = _connected_components(work)
    raw_ii = _integral_image(mask)
    raw_candidates: list[tuple[int, int, int, int, int, float, float]] = []
    debug_rows: list[RcpRectangleCandidate] = []

    for x, y, w, h, area in components:
        global_x = x + left
        global_y = y + top
        bbox_area = w * h
        aspect = w / max(1, h)
        fill = _rect_sum(raw_ii, x, y, w, h) / max(1, bbox_area)
        rejection = ""
        accepted_for_repeat_check = False
        elongated_fixture = aspect >= 1.8
        square_grid_fixture = (
            18 <= w <= 65
            and 18 <= h <= 65
            and 0.72 <= aspect <= 1.38
            and 0.22 <= fill <= 0.78
        )
        if w < 10 or h < 3:
            rejection = "too small for 2x4 fixture"
        elif w > 170 or h > 65:
            rejection = "too large for fixture symbol"
        elif not elongated_fixture and not square_grid_fixture:
            rejection = "not an elongated rectangle"
        elif elongated_fixture and (fill < 0.03 or fill > 0.48):
            rejection = "fill ratio not fixture-like"
        elif global_y < height * 0.14 or global_y > height * 0.88 or global_x > width * 0.84:
            rejection = "near title/header/footer/sidebar"
        elif square_grid_fixture:
            raw_candidates.append((global_x, global_y, w, h, bbox_area, aspect, fill))
            accepted_for_repeat_check = True
        else:
            top_edge = _rect_sum(raw_ii, x, y, w, 1)
            bottom_edge = _rect_sum(raw_ii, x, y + h - 1, w, 1)
            left_edge = _rect_sum(raw_ii, x, y, 1, h)
            right_edge = _rect_sum(raw_ii, x + w - 1, y, 1, h)
            edge_ratio = (top_edge + bottom_edge + left_edge + right_edge) / max(1, _rect_sum(raw_ii, x, y, w, h))
            if edge_ratio < 0.04 and fill < 0.08:
                raw_candidates.append((global_x, global_y, w, h, bbox_area, aspect, fill))
                accepted_for_repeat_check = True
                rejection = ""
            elif edge_ratio < 0.04:
                rejection = "does not look like a rectangular outline"
            else:
                raw_candidates.append((global_x, global_y, w, h, bbox_area, aspect, fill))
                accepted_for_repeat_check = True

        if not accepted_for_repeat_check:
            debug_rows.append(
                RcpRectangleCandidate(
                    source_file=image_path,
                    page_number=int((manifest_row or {}).get("pdf_page") or 0),
                    sheet_name=(manifest_row or {}).get("sheet_title", _sheet_from_image_name(image_path)),
                    x=global_x,
                    y=global_y,
                    width=w,
                    height=h,
                    aspect_ratio=round(aspect, 2),
                    area=bbox_area,
                    fill_ratio=round(fill, 3),
                    repeated_size_score=0.0,
                    accepted=False,
                    rejection_reason=rejection,
                    confidence=0.0,
                )
            )

    raw_candidates.extend(_rcp_line_pair_rectangles(mask, raw_ii, left, top, width, height))

    deduped_raw: list[tuple[int, int, int, int, int, float, float]] = []
    for cand in sorted(raw_candidates, key=lambda item: (item[1], item[0], -item[2] * item[3])):
        x, y, w, h, _area, _aspect, _fill = cand
        if any(abs(x - ox) <= 8 and abs(y - oy) <= 8 and abs(w - ow) <= 12 and abs(h - oh) <= 12 for ox, oy, ow, oh, *_rest in deduped_raw):
            continue
        deduped_raw.append(cand)
    raw_candidates = deduped_raw

    size_groups: Counter[tuple[int, int]] = Counter((round(w / 8), round(h / 4)) for _x, _y, w, h, _area, _aspect, _fill in raw_candidates)
    candidates: list[FixtureCandidate] = []
    sheet_number = _sheet_from_image_name(image_path)
    for x, y, w, h, bbox_area, aspect, fill in raw_candidates:
        group_key = (round(w / 8), round(h / 4))
        group_count = sum(
            count
            for (gw, gh), count in size_groups.items()
            if abs(gw - group_key[0]) <= 1 and abs(gh - group_key[1]) <= 1
        )
        is_square_grid = 0.72 <= aspect <= 1.38 and 0.22 <= fill <= 0.78 and 18 <= w <= 65 and 18 <= h <= 65
        repeated_score = min(1.0, group_count / (3 if is_square_grid else 4))
        accepted = repeated_score >= (0.66 if is_square_grid else 0.5)
        confidence = round(
            min(
                0.78,
                0.42
                + repeated_score * 0.22
                + (0.06 if is_square_grid else min(0.14, (aspect - 1.8) * 0.025)),
            ),
            2,
        )
        rejection = "" if accepted else "not repeated enough on this RCP page"
        debug_rows.append(
            RcpRectangleCandidate(
                source_file=image_path,
                page_number=int((manifest_row or {}).get("pdf_page") or 0),
                sheet_name=(manifest_row or {}).get("sheet_title", sheet_number),
                x=x,
                y=y,
                width=w,
                height=h,
                aspect_ratio=round(aspect, 2),
                area=bbox_area,
                fill_ratio=round(fill, 3),
                repeated_size_score=round(repeated_score, 2),
                accepted=accepted,
                rejection_reason=rejection,
                confidence=confidence if accepted else 0.0,
                repeated_size_group=f"{group_key[0]}x{group_key[1]}",
                group_count=group_count,
                accepted_by_grouping=accepted,
            )
        )
        if not accepted:
            continue
        candidates.append(
            FixtureCandidate(
                sheet_number=sheet_number,
                source_image=image_path,
                x=x,
                y=y,
                width=w,
                height=h,
                category="light_fixture",
                tag="SQUARE_CEILING_SYMBOL" if is_square_grid else "2x4_LED",
                symbol_type="rcp_repeated_square_grid" if is_square_grid else "rcp_repeated_rectangle",
                confidence=confidence,
                reason="RCP repeated square/grid ceiling symbol fallback" if is_square_grid else "RCP repeated-rectangle fallback",
                review_category="rcp_rectangle_fallback",
            )
        )
    return _dedupe_candidates(candidates, distance=16.0), debug_rows


def _row_runs(row: np.ndarray, min_len: int, max_len: int) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for idx, value in enumerate(row):
        if value and start is None:
            start = idx
        elif not value and start is not None:
            length = idx - start
            if min_len <= length <= max_len:
                runs.append((start, length))
            start = None
    if start is not None:
        length = len(row) - start
        if min_len <= length <= max_len:
            runs.append((start, length))
    return runs


def _rcp_line_pair_rectangles(
    mask: np.ndarray,
    raw_ii: np.ndarray,
    offset_x: int,
    offset_y: int,
    image_w: int,
    image_h: int,
) -> list[tuple[int, int, int, int, int, float, float]]:
    runs: list[tuple[int, int, int]] = []
    min_len = max(34, int(image_w * 0.025))
    max_len = max(150, int(image_w * 0.11))
    for y in range(0, mask.shape[0], 1):
        for x, length in _row_runs(mask[y], min_len=min_len, max_len=max_len):
            if runs and abs(runs[-1][0] - y) <= 2 and abs(runs[-1][1] - x) <= 4 and abs(runs[-1][2] - length) <= 8:
                continue
            runs.append((y, x, length))

    candidates: list[tuple[int, int, int, int, int, float, float]] = []
    for idx, (y1, x1, w1) in enumerate(runs):
        for y2, x2, w2 in runs[idx + 1 : idx + 120]:
            h = y2 - y1
            if h < 18 or h > 62:
                continue
            if abs(x1 - x2) > 8 or abs(w1 - w2) > 16:
                continue
            w = int((w1 + w2) / 2)
            aspect = w / max(1, h)
            if aspect < 1.8 or aspect > 6.5:
                continue
            x = int((x1 + x2) / 2)
            dark = _rect_sum(raw_ii, x, y1, min(w, mask.shape[1] - x), min(h, mask.shape[0] - y1))
            area = w * h
            fill = dark / max(1, area)
            if fill < 0.025 or fill > 0.30:
                continue
            global_x = x + offset_x
            global_y = y1 + offset_y
            if global_y < image_h * 0.14 or global_y > image_h * 0.88 or global_x > image_w * 0.84:
                continue
            candidates.append((global_x, global_y, w, h, area, aspect, fill))
    return candidates


def _write_rcp_debug(rows: list[RcpRectangleCandidate], out_dir: Path) -> Path:
    csv_path = out_dir / "rcp_rectangle_candidates.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["source_file", "page_number", "sheet_name", "x", "y", "width", "height", "aspect_ratio", "area", "fill_ratio", "repeated_size_score", "repeated_size_group", "group_count", "accepted_by_grouping", "accepted", "rejection_reason", "confidence"])
        for row in rows:
            writer.writerow([str(row.source_file), row.page_number, row.sheet_name, row.x, row.y, row.width, row.height, row.aspect_ratio, row.area, row.fill_ratio, row.repeated_size_score, row.repeated_size_group, row.group_count, "yes" if row.accepted_by_grouping else "no", "yes" if row.accepted else "no", row.rejection_reason, row.confidence])
    debug_dir = out_dir / "rcp_debug_images"
    debug_dir.mkdir(parents=True, exist_ok=True)
    by_image: dict[Path, list[RcpRectangleCandidate]] = {}
    for row in rows:
        by_image.setdefault(row.source_file, []).append(row)
    for image_path, image_rows in by_image.items():
        try:
            image = Image.open(image_path).convert("RGB")
        except Exception:
            continue
        draw = ImageDraw.Draw(image)
        for row in image_rows[:500]:
            color = (255, 0, 0) if row.accepted else (180, 180, 0)
            draw.rectangle([row.x, row.y, row.x + row.width, row.y + row.height], outline=color, width=2)
        image.save(debug_dir / f"{image_path.stem}_rcp_debug.png")
    return csv_path


def _dedupe_candidates(candidates: list[FixtureCandidate], distance: float = 10.0) -> list[FixtureCandidate]:
    candidates = sorted(candidates, key=lambda c: (-c.confidence, c.y, c.x))
    kept: list[FixtureCandidate] = []
    for cand in candidates:
        duplicate = False
        for old in kept:
            if cand.source_image != old.source_image:
                continue
            if math.hypot(cand.cx - old.cx, cand.cy - old.cy) <= distance:
                duplicate = True
                break
        if not duplicate:
            kept.append(cand)
    return sorted(kept, key=lambda c: (c.source_image.name, c.y, c.x))


def _template_image_candidates(
    image_path: Path,
    templates: list[SymbolTemplate],
    manifest_row: dict[str, str] | None = None,
    min_score: float = 0.68,
    allowed_categories: set[str] | None = None,
) -> list[FixtureCandidate]:
    usable = [item for item in templates if item.template_image_path and Path(item.template_image_path).exists()]
    if allowed_categories is not None:
        usable = [item for item in usable if item.category in allowed_categories]
    if not usable:
        return []
    image = Image.open(image_path).convert("L")
    image_arr = np.asarray(image)
    left, top, right, bottom = _plan_crop_bounds(image.width, image.height)
    plan_mask = image_arr[top:bottom, left:right] < 140
    candidates: list[FixtureCandidate] = []
    sheet = (manifest_row or {}).get("sheet_number") or _sheet_from_image_name(image_path)
    for template in usable[:40]:
        try:
            template_image = Image.open(template.template_image_path).convert("L")
        except Exception:
            continue
        if template_image.width < 4 or template_image.height < 4:
            continue
        for scale in (0.85, 1.0, 1.15):
            tw = max(4, int(template_image.width * scale))
            th = max(4, int(template_image.height * scale))
            if tw > plan_mask.shape[1] or th > plan_mask.shape[0]:
                continue
            tpl = np.asarray(template_image.resize((tw, th))) < 150
            dark = int(tpl.sum())
            if dark < 8:
                continue
            step = max(3, min(tw, th) // 5)
            for y in range(0, plan_mask.shape[0] - th + 1, step):
                for x in range(0, plan_mask.shape[1] - tw + 1, step):
                    window = plan_mask[y : y + th, x : x + tw]
                    overlap = int((window & tpl).sum())
                    score = overlap / max(1, dark)
                    if score < min_score:
                        continue
                    candidates.append(
                        FixtureCandidate(
                            sheet_number=sheet,
                            source_image=image_path,
                            x=x + left,
                            y=y + top,
                            width=tw,
                            height=th,
                            category=template.category,
                            tag=template.tag,
                            symbol_type="library_template_match",
                            confidence=round(min(0.88, score), 2),
                            reason=f"library template match from {template.extraction_method}",
                            review_category="template_match",
                        )
                    )
    return _dedupe_candidates(candidates, distance=12.0)


def _allowed_template_categories(manifest_row: dict[str, str] | None) -> tuple[set[str], str]:
    text = " ".join((manifest_row or {}).values()).upper()
    if any(word in text for word in ["FIRE ALARM", "FA-", "SMOKE", "STROBE", "HORN", "PULL STATION"]):
        return {"fire_alarm_device"}, "fire alarm sheet context"
    if any(word in text for word in ["LIGHTING", "LUMINAIRE", "REFLECTED CEILING", "CEILING PLAN", "RCP"]):
        return {"light_fixture", "exit_sign", "emergency_light"}, "lighting/RCP sheet context"
    if any(word in text for word in ["POWER", "RECEPTACLE", "OUTLET"]):
        return {"receptacle", "tele_data"}, "power sheet context"
    return {"light_fixture", "exit_sign", "emergency_light", "fire_alarm_device"}, "generic electrical sheet context"


def _symbol_detection_sheet_allowed(manifest_row: dict[str, str] | None) -> tuple[bool, str]:
    text = " ".join((manifest_row or {}).values()).upper()
    discipline = ((manifest_row or {}).get("discipline") or "").lower()
    if discipline in {"lighting", "fire_alarm"}:
        return True, "lighting/fire-alarm discipline"
    if any(word in text for word in ["LIGHTING", "LUMINAIRE", "REFLECTED CEILING", "CEILING PLAN", "RCP", "FIRE ALARM"]):
        return True, "sheet text indicates lighting/RCP/fire-alarm plan"
    return False, "not a supported symbol-detection sheet for this lighting/device pass"


def detect_light_fixtures_from_image(
    image_path: Path,
    min_confidence: float = 0.55,
    label_debug_rows: list[dict[str, object]] | None = None,
) -> list[FixtureCandidate]:
    pdf_path = _one_page_pdf_for_image(image_path)
    if pdf_path:
        try:
            page_text = PdfReader(str(pdf_path)).pages[0].extract_text() or ""
            if NON_TAKEOFF_PAGE_TEXT.search(page_text):
                return []
        except Exception:
            pass
        label_candidates = [cand for cand in _pdf_label_candidates(image_path, pdf_path, label_debug_rows) if cand.confidence >= min_confidence]
        if label_candidates:
            return label_candidates

    image = Image.open(image_path).convert("L")
    arr = np.asarray(image)
    width, height = image.size
    left, top, right, bottom = _plan_crop_bounds(width, height)
    crop = arr[top:bottom, left:right]

    # Dark linework mask. Lighting plans are mostly light gray linework with
    # darker fixture symbols/text; this threshold intentionally finds candidates
    # for review rather than pretending to be final.
    mask = crop < 95
    sheet_number = _sheet_from_image_name(image_path)
    candidates = _component_candidates(mask, (left, top), image_path, sheet_number)
    candidates = [cand for cand in _dedupe_candidates(candidates) if cand.confidence >= min_confidence]
    return candidates


def _read_render_manifest(rendered_sheets_dir: Path) -> dict[str, dict[str, str]]:
    manifest = rendered_sheets_dir.parent / "rendered_sheet_manifest.csv"
    if not manifest.exists():
        return {}
    with manifest.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return {str(Path(row.get("image", ""))).lower(): row for row in rows if row.get("image")}


def _write_marked_images(
    candidates: list[FixtureCandidate],
    out_dir: Path,
    source_images: list[Path] | None = None,
    image_notes: dict[Path, str] | None = None,
) -> list[Path]:
    marked_dir = out_dir / "marked_images"
    marked_dir.mkdir(parents=True, exist_ok=True)
    by_image: dict[Path, list[FixtureCandidate]] = {}
    for cand in candidates:
        by_image.setdefault(cand.source_image, []).append(cand)
    for image_path in source_images or []:
        by_image.setdefault(image_path, [])

    marked_paths: list[Path] = []
    for image_path, items in by_image.items():
        image = Image.open(image_path).convert("RGB")
        draw = ImageDraw.Draw(image)
        if not items:
            note = (image_notes or {}).get(image_path) or "Sheet rendered for estimator review; coordinate markup was limited/unavailable."
            draw.rectangle([10, 10, min(image.width - 10, 760), 58], fill=(255, 255, 210), outline=(180, 120, 0), width=2)
            draw.text((20, 24), note, fill=(120, 80, 0))
        elif (image_notes or {}).get(image_path):
            note = (image_notes or {})[image_path]
            draw.rectangle([10, 10, min(image.width - 10, 760), 58], fill=(220, 245, 255), outline=(0, 90, 150), width=2)
            draw.text((20, 24), note, fill=(0, 70, 120))
        for idx, cand in enumerate(items, 1):
            if cand.category == "light_fixture":
                color = (255, 0, 0)
            elif cand.category == "exit_sign":
                color = (0, 150, 60)
            elif cand.category == "emergency_light":
                color = (0, 90, 255)
            elif cand.category == "fire_alarm_device":
                color = (150, 0, 200)
            else:
                color = (255, 200, 0) if cand.confidence >= 0.7 else (255, 165, 0)
            draw.rectangle([cand.x, cand.y, cand.x + cand.width, cand.y + cand.height], outline=color, width=3)
            if idx <= 200:
                label = f"{idx} {cand.category}/{cand.tag} {cand.confidence:.2f}"
                draw.text((cand.x, max(0, cand.y - 14)), label, fill=color)
        out = marked_dir / f"{image_path.stem}_marked_review.png"
        image.save(out)
        marked_paths.append(out)
    return marked_paths


def _write_marked_pdf(marked_images: list[Path], out_path: Path) -> None:
    if not marked_images:
        return
    if out_path.exists():
        out_path.unlink()
    first = Image.open(marked_images[0])
    page_size = landscape((first.width, first.height))
    c = canvas.Canvas(str(out_path), pagesize=page_size)
    for image_path in marked_images:
        img = Image.open(image_path)
        page_size = landscape((img.width, img.height))
        c.setPageSize(page_size)
        c.drawImage(str(image_path), 0, 0, width=img.width, height=img.height)
        c.showPage()
    c.save()


def _write_template_matches(out_dir: Path, candidates: list[FixtureCandidate]) -> Path:
    path = out_dir / "template_matches.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["source_file", "page_number", "sheet_name", "category", "tag", "symbol_id", "symbol_source", "template_image_path", "x", "y", "width", "height", "match_score", "scale", "rotation", "accepted", "rejection_reason", "confidence"])
        for cand in candidates:
            if "label" not in cand.symbol_type and "template" not in cand.symbol_type:
                continue
            writer.writerow([str(cand.source_image), "", cand.sheet_number, cand.category, cand.tag, cand.tag, cand.reason, "", cand.x, cand.y, cand.width, cand.height, cand.confidence, "1.0", "0", "yes", "", cand.confidence])
    return path


def _write_label_candidates(out_dir: Path, rows: list[dict[str, object]]) -> Path:
    path = out_dir / "label_candidates.csv"
    fieldnames = [
        "source_file",
        "page_number",
        "sheet_name",
        "raw_text",
        "normalized_tag",
        "x",
        "y",
        "width",
        "height",
        "category_guess",
        "accepted",
        "rejection_reason",
        "confidence",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})
    return path


def _write_template_attempts(out_dir: Path, rows: list[dict[str, object]]) -> Path:
    path = out_dir / "template_attempts.csv"
    fieldnames = ["source_file", "sheet_name", "templates_available", "templates_allowed", "attempted", "skip_reason", "matches_accepted"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})
    return path


def _source_priority(candidate: FixtureCandidate) -> tuple[int, float]:
    reason = candidate.reason.lower()
    symbol = candidate.symbol_type.lower()
    if "project" in reason:
        priority = 0
    elif "label" in symbol:
        priority = 1
    elif "private_company" in reason or "company" in reason:
        priority = 2
    elif "starter" in reason and "template" in symbol:
        priority = 3
    elif "rcp" in symbol or "fallback" in reason:
        priority = 4
    else:
        priority = 5
    return priority, -candidate.confidence


def _overlaps(a: FixtureCandidate, b: FixtureCandidate) -> bool:
    if a.source_image != b.source_image:
        return False
    return _overlap_ratio(a, b) >= 0.30 or math.hypot(a.cx - b.cx, a.cy - b.cy) <= max(12, min(a.width, b.width, a.height, b.height))


def _fuse_candidates(candidates: list[FixtureCandidate]) -> tuple[list[FixtureCandidate], dict[FixtureCandidate, list[str]]]:
    fused: list[FixtureCandidate] = []
    merged_from: dict[FixtureCandidate, list[str]] = {}
    for cand in sorted(candidates, key=_source_priority):
        match_index: int | None = None
        for index, existing in enumerate(fused):
            if existing.category == cand.category and _overlaps(existing, cand):
                if existing.tag != cand.tag and "label" in existing.symbol_type and "label" in cand.symbol_type:
                    continue
                match_index = index
                break
        if match_index is None:
            fused.append(cand)
            merged_from[cand] = [cand.symbol_type]
            continue
        existing = fused[match_index]
        keep_new = _source_priority(cand) < _source_priority(existing)
        winner = cand if keep_new else existing
        loser = existing if keep_new else cand
        sources = [*merged_from.get(existing, [existing.symbol_type]), loser.symbol_type]
        if keep_new:
            fused[match_index] = winner
            merged_from.pop(existing, None)
        merged_from[winner] = sorted(set(sources))
    return sorted(fused, key=lambda c: (c.source_image.name, c.y, c.x)), merged_from


def _estimator_output_candidates(candidates: list[FixtureCandidate], merged_from: dict[FixtureCandidate, list[str]]) -> list[FixtureCandidate]:
    output: list[FixtureCandidate] = []
    for cand in candidates:
        sources = set(merged_from.get(cand, [cand.symbol_type]))
        if "text_label_match" in sources:
            output.append(cand)
    return output


def _write_final_candidates(out_dir: Path, candidates: list[FixtureCandidate], merged_from: dict[FixtureCandidate, list[str]]) -> Path:
    path = out_dir / "final_candidates.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["source_file", "page_number", "sheet_name", "category", "tag", "x", "y", "width", "height", "confidence", "evidence", "merged_from", "review_status"])
        for cand in candidates:
            writer.writerow([str(cand.source_image), "", cand.sheet_number, cand.category, cand.tag, cand.x, cand.y, cand.width, cand.height, cand.confidence, cand.reason, ";".join(merged_from.get(cand, [cand.symbol_type])), "NEEDS_REVIEW"])
    return path


def _write_detection_strategy_debug(
    out_dir: Path,
    *,
    templates: list[SymbolTemplate],
    images: list[Path],
    detection_images: list[Path],
    skipped_review_only: int,
    template_attempts: int,
    template_matches: int,
    label_attempts: int,
    label_matches: int,
    rcp_attempts: int,
    rcp_accepted: int,
    final_candidates: list[FixtureCandidate],
    template_attempt_rows: list[dict[str, object]],
    label_debug_rows: list[dict[str, object]],
) -> Path:
    path = out_dir / "detection_strategy_debug.md"
    counts = Counter(item.extraction_method for item in templates)
    template_images = [item for item in templates if item.template_image_path and Path(item.template_image_path).exists()]
    with path.open("w", encoding="utf-8") as handle:
        handle.write("# Detection strategy debug\n\n")
        handle.write("This file explains which detection sources contributed candidates. It is internal evidence, not final bid output.\n\n")
        handle.write("## Sources loaded\n\n")
        handle.write(f"- Project templates loaded: {counts.get('legend_text', 0)}\n")
        handle.write(f"- Company templates loaded: {counts.get('private_company_library', 0)}\n")
        handle.write(f"- Starter symbols loaded: {counts.get('starter_symbol_taxonomy', 0)}\n")
        handle.write(f"- Template images available: {len(template_images)}\n")
        handle.write("\n## Attempts\n\n")
        handle.write(f"- Rendered images: {len(images)}\n")
        handle.write(f"- Detection-allowed images: {len(detection_images)}\n")
        handle.write(f"- Review-only images skipped: {skipped_review_only}\n")
        handle.write(f"- Template matching attempted on images: {template_attempts}\n")
        handle.write(f"- Template matches accepted: {template_matches}\n")
        handle.write(f"- Template attempts/skips recorded: {len(template_attempt_rows)}\n")
        handle.write(f"- Label matching attempted on images: {label_attempts}\n")
        handle.write(f"- Label/visual matches accepted before RCP fallback: {label_matches}\n")
        handle.write(f"- Label candidates recorded: {len(label_debug_rows)}\n")
        handle.write(f"- RCP fallback attempted on images: {rcp_attempts}\n")
        handle.write(f"- RCP fallback accepted candidates: {rcp_accepted}\n")
        handle.write(f"- Final fused candidates: {len(final_candidates)}\n\n")
        handle.write("## Why sources may not contribute\n\n")
        if not template_images:
            handle.write("- Template matching had no image templates to use. Starter metadata can assist labels, but metadata alone is not a visual match.\n")
        for row in template_attempt_rows[:20]:
            if row.get("attempted") != "yes":
                handle.write(f"- Template matching skipped on {row.get('sheet_name')}: {row.get('skip_reason')}\n")
        if not final_candidates:
            handle.write("- No source produced accepted coordinate-level detections.\n")
        handle.write("- Previous estimate and TPX references are intentionally excluded from AI detections.\n")
    return path


def detect_light_fixtures(rendered_sheets_dir: Path, out_dir: Path, min_confidence: float = 0.55, project_folder: Path | None = None) -> tuple[Path, Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    images = sorted(rendered_sheets_dir.glob("*.png"))
    manifest = _read_render_manifest(rendered_sheets_dir)
    templates = _extract_symbol_templates(project_folder, manifest, out_dir)
    detection_images: list[Path] = []
    image_notes: dict[Path, str] = {}
    skipped_review_only = 0
    for image in images:
        row = manifest.get(str(image).lower(), {})
        if row and row.get("detection_allowed") != "yes":
            skipped_review_only += 1
            image_notes[image] = "Rendered for review only - no automatic visual count used."
            continue
        allowed_sheet, sheet_skip_reason = _symbol_detection_sheet_allowed(row)
        if row and not allowed_sheet:
            skipped_review_only += 1
            image_notes[image] = f"Rendered for review only - {sheet_skip_reason}."
            continue
        detection_images.append(image)
        image_notes[image] = "Used for first-pass AI detection."
    candidates: list[FixtureCandidate] = []
    rcp_debug_rows: list[RcpRectangleCandidate] = []
    template_attempts = 0
    template_matches_count = 0
    label_attempts = 0
    label_matches_count = 0
    rcp_attempts = 0
    template_attempt_rows: list[dict[str, object]] = []
    label_debug_rows: list[dict[str, object]] = []
    template_images_available = [item for item in templates if item.template_image_path and Path(item.template_image_path).exists()]
    for image in detection_images:
        manifest_row = manifest.get(str(image).lower(), {})
        allowed_template_categories, allowed_reason = _allowed_template_categories(manifest_row)
        allowed_template_count = sum(1 for item in template_images_available if item.category in allowed_template_categories)
        template_matches: list[FixtureCandidate] = []
        if template_images_available and allowed_template_count:
            template_attempts += 1
            template_matches = _template_image_candidates(image, templates, manifest_row, allowed_categories=allowed_template_categories)
            if template_matches:
                template_matches_count += len(template_matches)
                candidates.extend(template_matches)
            template_attempt_rows.append(
                {
                    "source_file": str(image),
                    "sheet_name": manifest_row.get("sheet_number") or _sheet_from_image_name(image),
                    "templates_available": len(template_images_available),
                    "templates_allowed": allowed_template_count,
                    "attempted": "yes",
                    "skip_reason": "",
                    "matches_accepted": len(template_matches),
                }
            )
        else:
            skip_reason = "no template images available" if not template_images_available else f"no templates allowed for {allowed_reason}"
            template_attempt_rows.append(
                {
                    "source_file": str(image),
                    "sheet_name": manifest_row.get("sheet_number") or _sheet_from_image_name(image),
                    "templates_available": len(template_images_available),
                    "templates_allowed": allowed_template_count,
                    "attempted": "no",
                    "skip_reason": skip_reason,
                    "matches_accepted": 0,
                }
            )
        label_attempts += 1
        label_or_visual = detect_light_fixtures_from_image(image, min_confidence=min_confidence, label_debug_rows=label_debug_rows)
        if label_or_visual:
            label_matches_count += len(label_or_visual)
            candidates.extend(label_or_visual)
            continue
        rcp_attempts += 1
        rcp_candidates, debug_rows = _rcp_rectangle_candidates(image, manifest_row)
        rcp_debug_rows.extend(debug_rows)
        candidates.extend([cand for cand in rcp_candidates if cand.confidence >= 0.48])
        if not rcp_candidates and RCP_PAGE_TEXT.search(" ".join(manifest_row.values())):
            image_notes[image] = "RCP page selected, but no rectangular light fixture detections were found."

    fused_candidates, merged_from = _fuse_candidates(candidates)
    output_candidates = _estimator_output_candidates(fused_candidates, merged_from)
    label_candidates_csv = _write_label_candidates(out_dir, label_debug_rows)
    template_attempts_csv = _write_template_attempts(out_dir, template_attempt_rows)
    template_matches_csv = _write_template_matches(out_dir, fused_candidates)
    rcp_debug_csv = _write_rcp_debug(rcp_debug_rows, out_dir)
    final_candidates_csv = _write_final_candidates(out_dir, output_candidates, merged_from)
    strategy_debug = _write_detection_strategy_debug(
        out_dir,
        templates=templates,
        images=images,
        detection_images=detection_images,
        skipped_review_only=skipped_review_only,
        template_attempts=template_attempts,
        template_matches=template_matches_count,
        label_attempts=label_attempts,
        label_matches=label_matches_count,
        rcp_attempts=rcp_attempts,
        rcp_accepted=sum(1 for row in rcp_debug_rows if row.accepted),
        final_candidates=output_candidates,
        template_attempt_rows=template_attempt_rows,
        label_debug_rows=label_debug_rows,
    )

    marked_images = _write_marked_images(output_candidates, out_dir, source_images=images, image_notes=image_notes)
    marked_pdf = out_dir / "marked_up_drawings.pdf"
    _write_marked_pdf(marked_images, marked_pdf)

    takeoff_csv = out_dir / "takeoff_items.csv"
    review_csv = out_dir / "estimator_review.csv"
    summary_md = out_dir / "symbol_detection.md"

    counts = Counter((cand.sheet_number, cand.category, cand.tag, cand.symbol_type, cand.review_category) for cand in output_candidates)
    category_counts = Counter(cand.category for cand in output_candidates)

    with takeoff_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["item", "category", "tag", "quantity", "sheet", "location", "confidence", "reason", "review_category", "review_required"])
        for (sheet, category, tag, symbol_type, review_category), qty in sorted(counts.items()):
            sheet_candidates = [
                c
                for c in candidates
                if c.sheet_number == sheet and c.category == category and c.tag == tag and c.symbol_type == symbol_type and c.review_category == review_category
            ]
            avg_conf = sum(c.confidence for c in sheet_candidates) / max(1, len(sheet_candidates))
            if "label" in symbol_type:
                label = {
                    "light_fixture": "LIGHT FIXTURE",
                    "exit_sign": "EXIT SIGN",
                    "emergency_light": "EMERGENCY LIGHT",
                    "fire_alarm_device": "FIRE ALARM DEVICE",
                }.get(category, category.replace("_", " ").upper())
                item_name = f"{label} TAG {tag}"
                reason = sheet_candidates[0].reason if sheet_candidates else "embedded PDF label positioned on plan"
            else:
                item_name = f"LIGHT FIXTURE CANDIDATE - {tag}"
                reason = sheet_candidates[0].reason if sheet_candidates else "visual rectangular/linear fixture candidates"
            writer.writerow(
                [
                    item_name,
                    category,
                    tag,
                    qty,
                    sheet,
                    "rendered drawing coordinates",
                    round(avg_conf, 2),
                    reason,
                    review_category,
                    "yes",
                ]
            )

    with review_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["sheet", "category", "tag", "symbol_type", "x", "y", "width", "height", "confidence", "reason", "review_category", "source_image"])
        for cand in output_candidates:
            writer.writerow(
                [
                    cand.sheet_number,
                    cand.category,
                    cand.tag,
                    cand.symbol_type,
                    cand.x,
                    cand.y,
                    cand.width,
                    cand.height,
                    cand.confidence,
                    cand.reason,
                    cand.review_category,
                    str(cand.source_image),
                ]
            )

    with summary_md.open("w", encoding="utf-8") as handle:
        handle.write("# Symbol detection\n\n")
        handle.write("This Phase 3 detector handles first-pass light fixtures, exit signs, emergency lights, and fire alarm device labels. It uses embedded PDF labels when available, then falls back to rendered-sheet visual linework heuristics for light fixture candidates.\n\n")
        handle.write("This is not final takeoff yet. Every count is marked `review_required` until validated against LiveCount, Accubid, or human takeoff.\n\n")
        handle.write("## Summary\n\n")
        handle.write(f"- Rendered sheet images scanned: {len(images)}\n")
        handle.write(f"- Rendered sheet images allowed for AI detection: {len(detection_images)}\n")
        handle.write(f"- Rendered sheet images skipped as review-only: {skipped_review_only}\n")
        handle.write(f"- Symbol templates found from legend/schedule pages: {len(templates)}\n")
        handle.write(f"- RCP rectangle candidates inspected: {len(rcp_debug_rows)}\n")
        handle.write(f"- RCP rectangle candidates accepted: {sum(1 for row in rcp_debug_rows if row.accepted)}\n")
        handle.write(f"- Raw candidate labels/symbols found: {len(candidates)}\n")
        handle.write(f"- Final estimator-output candidates: {len(output_candidates)}\n")
        handle.write(f"- Marked image previews: {len(marked_images)}\n\n")
        if images and not candidates:
            handle.write("Rendered pages were still included in `marked_up_drawings.pdf` with a review note because no coordinate-level candidates were found.\n\n")
        handle.write("## Categories\n\n")
        if category_counts:
            for category, qty in sorted(category_counts.items()):
                handle.write(f"- {category}: {qty}\n")
        else:
            handle.write("- No candidate categories found.\n")
        handle.write("\n")
        handle.write("## Counts by sheet/type\n\n")
        for (sheet, category, tag, symbol_type, review_category), qty in sorted(counts.items()):
            handle.write(f"- {sheet} / {category} / {tag} / {review_category}: {qty}\n")
        if not counts:
            handle.write("- No candidates found.\n")
        handle.write("\n## Outputs\n\n")
        handle.write("- `takeoff_items.csv`\n")
        handle.write("- `estimator_review.csv`\n")
        handle.write("- `marked_up_drawings.pdf`\n")
        handle.write("- `marked_images/`\n\n")
        handle.write("- `template_matches.csv`\n")
        handle.write("- `label_candidates.csv`\n")
        handle.write("- `template_attempts.csv`\n")
        handle.write("- `rcp_rectangle_candidates.csv`\n")
        handle.write("- `rcp_debug_images/`\n")
        handle.write("- `final_candidates.csv`\n")
        handle.write("- `detection_strategy_debug.md`\n")
        handle.write("- `_internal/symbol_templates/symbol_templates.csv`\n\n")
        if templates:
            handle.write("## Symbol templates\n\n")
            handle.write("Project legend/schedule text produced template references. Image-crop template matching is still conservative; this run records text-derived templates and label/template-style matches separately.\n\n")
        else:
            handle.write("## Symbol templates\n\n")
            handle.write("No usable legend/schedule templates were found, so RCP repeated-geometry fallback may be used on strong RCP pages.\n\n")
        handle.write("## Next improvement\n\n")
        handle.write("Validate these candidates against a known LiveCount/historical takeoff sheet, then tune the detector for one fixture family at a time.\n")

    return summary_md, takeoff_csv, review_csv
