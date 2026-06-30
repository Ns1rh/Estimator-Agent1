from __future__ import annotations

import csv
import math
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


def _sheet_from_image_name(path: Path) -> str:
    match = re.match(r"([A-Za-z0-9.]+)_p\d+", path.stem)
    return match.group(1).upper() if match else path.stem.upper()


LABEL_TOKEN = re.compile(
    r"^(?:[A-Z]\d{1,2}[A-Z]?|EM\d?[A-Z]?|EMS|EMER|EXIT|EX|X\d*[A-Z]?|SD|HD|DD|PS|PULL|HS|H/S|FACP|FAAP|NAC|MM|MON|CM|CTRL)(?:[a-z])?$",
    re.IGNORECASE,
)
LABEL_NOISE = {"OS", "VS", "J", "A", "B", "C", "D", "E", "N", "S", "T"}
FIRE_ALARM_TOKENS = {"SD", "HD", "DD", "PS", "PULL", "HS", "H/S", "FACP", "FAAP", "NAC", "MM", "MON", "CM", "CTRL"}
NON_PLAN_HEADING = re.compile(
    r"\b(?:LEGEND|SYMBOL\s+LEGEND|GENERAL\s+NOTES?|SHEET\s+NOTES?|LIGHTING\s+NOTES?|FIRE\s+ALARM\s+NOTES?|FIXTURE\s+SCHEDULE|LUMINAIRE\s+SCHEDULE|FIRE\s+ALARM\s+DEVICE\s+SCHEDULE|SHEET\s+INDEX|TITLE\s+BLOCK)\b",
    re.IGNORECASE,
)


def _review_category_for_label(label: str) -> str:
    """Separate strong fixture labels from tags that should stay visible but not trusted blindly."""
    upper = label.upper()
    if upper in {"EXIT", "EX", "X"} or upper.startswith("EM") or upper == "EMS":
        return "likely_fixture_tag"
    if upper in FIRE_ALARM_TOKENS:
        return "likely_device_tag"
    if re.match(r"^[A-Z]\d{1,2}[A-Z]?$", upper):
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
    if upper in FIRE_ALARM_TOKENS:
        return "fire_alarm_device", upper, 0.86, "embedded PDF fire alarm device label positioned on plan"
    if upper in {"EXIT", "EX"} or re.match(r"^X\d*[A-Z]?$", upper):
        return "exit_sign", upper, 0.86, "embedded PDF exit sign label positioned on plan"
    if upper.startswith("EM") or upper in {"EMS", "EMER"}:
        return "emergency_light", upper, 0.86, "embedded PDF emergency light label positioned on plan"
    if re.match(r"^[A-Z]\d{1,2}[A-Z]?$", upper):
        if fire_context and upper in {"H1", "H2", "S1", "S2"}:
            return "fire_alarm_device", upper, 0.80, "embedded PDF fire alarm device-like label positioned on fire alarm plan"
        return "light_fixture", upper, 0.86, "embedded PDF light fixture label positioned on plan"
    return None


def _one_page_pdf_for_image(image_path: Path) -> Path | None:
    # Phase 2 renders from sibling _render_tmp/E1.1_p127.pdf to
    # rendered_sheets/E1.1_p127-1.png.
    base = re.sub(r"-\d+$", "", image_path.stem)
    candidate = image_path.parent.parent / "_render_tmp" / f"{base}.pdf"
    return candidate if candidate.exists() else None


def _dedupe_label_candidates(candidates: list[FixtureCandidate], distance: float = 6.0) -> list[FixtureCandidate]:
    kept: list[FixtureCandidate] = []
    for cand in sorted(candidates, key=lambda c: (c.sheet_number, c.y, c.x, -len(c.symbol_type), -c.confidence)):
        duplicate = False
        cand_item = cand.symbol_type
        replacement_index: int | None = None
        for index, old in enumerate(kept):
            if old.source_image != cand.source_image:
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


def _pdf_label_candidates(image_path: Path, pdf_path: Path) -> list[FixtureCandidate]:
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
    raw_label_hits: list[tuple[str, int, int, int, int]] = []

    def visitor(text: str, cm, tm, font, size) -> None:
        clean_text = re.sub(r"\s+", " ", text.strip())
        if clean_text:
            line_x = int(float(tm[4]) * scale_x)
            line_y = int((page_h - float(tm[5])) * scale_y)
            line_w = max(12, int(len(clean_text) * float(size) * scale_x * 0.55))
            line_h = max(8, int(float(size) * scale_y * 1.25))
            text_lines.append((clean_text, line_x, line_y, line_w, line_h))
        raw_tokens = re.split(r"\s+", text.strip())
        for token in raw_tokens:
            clean = token.strip().upper()
            if clean in LABEL_NOISE or not LABEL_TOKEN.match(token.strip()):
                continue
            x = int(float(tm[4]) * scale_x)
            y = int((page_h - float(tm[5])) * scale_y)
            if x < left or x > right or y < top or y > bottom:
                continue
            box_w = max(16, int(len(clean) * float(size) * scale_x * 0.62))
            box_h = max(10, int(float(size) * scale_y * 1.25))
            raw_label_hits.append((clean, x, max(0, y - box_h), box_w, box_h))

    try:
        page.extract_text(visitor_text=visitor)
    except Exception:
        return []
    zones = _text_exclusion_zones(text_lines, image_w, image_h)
    sheet_text = " ".join(text for text, *_rest in text_lines)
    for clean, x, y, box_w, box_h in raw_label_hits:
        if _inside_exclusion_zone(x + box_w // 2, y + box_h // 2, zones):
            continue
        classified = _classify_label(clean, sheet_number, sheet_text)
        if not classified:
            continue
        category, tag, confidence, reason = classified
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
                symbol_type=f"{category}_label_{tag}",
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
    bottom = int(height * 0.90)
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


def detect_light_fixtures_from_image(image_path: Path, min_confidence: float = 0.55) -> list[FixtureCandidate]:
    pdf_path = _one_page_pdf_for_image(image_path)
    if pdf_path:
        label_candidates = [cand for cand in _pdf_label_candidates(image_path, pdf_path) if cand.confidence >= min_confidence]
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


def _write_marked_images(candidates: list[FixtureCandidate], out_dir: Path) -> list[Path]:
    marked_dir = out_dir / "marked_images"
    marked_dir.mkdir(parents=True, exist_ok=True)
    by_image: dict[Path, list[FixtureCandidate]] = {}
    for cand in candidates:
        by_image.setdefault(cand.source_image, []).append(cand)

    marked_paths: list[Path] = []
    for image_path, items in by_image.items():
        image = Image.open(image_path).convert("RGB")
        draw = ImageDraw.Draw(image)
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
                draw.text((cand.x, max(0, cand.y - 12)), str(idx), fill=color)
        out = marked_dir / f"{image_path.stem}_light_fixture_candidates.png"
        image.save(out)
        marked_paths.append(out)
    return marked_paths


def _write_marked_pdf(marked_images: list[Path], out_path: Path) -> None:
    if not marked_images:
        return
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


def detect_light_fixtures(rendered_sheets_dir: Path, out_dir: Path, min_confidence: float = 0.55) -> tuple[Path, Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    images = sorted(rendered_sheets_dir.glob("*.png"))
    candidates: list[FixtureCandidate] = []
    for image in images:
        candidates.extend(detect_light_fixtures_from_image(image, min_confidence=min_confidence))

    marked_images = _write_marked_images(candidates, out_dir)
    marked_pdf = out_dir / "marked_up_drawings.pdf"
    _write_marked_pdf(marked_images, marked_pdf)

    takeoff_csv = out_dir / "takeoff_items.csv"
    review_csv = out_dir / "estimator_review.csv"
    summary_md = out_dir / "symbol_detection.md"

    counts = Counter((cand.sheet_number, cand.category, cand.tag, cand.symbol_type, cand.review_category) for cand in candidates)
    category_counts = Counter(cand.category for cand in candidates)

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
            if "_label_" in symbol_type:
                label = {
                    "light_fixture": "LIGHT FIXTURE",
                    "exit_sign": "EXIT SIGN",
                    "emergency_light": "EMERGENCY LIGHT",
                    "fire_alarm_device": "FIRE ALARM DEVICE",
                }.get(category, category.replace("_", " ").upper())
                item_name = f"{label} TAG {tag}"
                reason = sheet_candidates[0].reason if sheet_candidates else "embedded PDF label positioned on plan"
            else:
                item_name = f"LIGHT FIXTURE CANDIDATE - {symbol_type}"
                reason = "visual rectangular/linear fixture candidates"
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
        for cand in candidates:
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
        handle.write(f"- Candidate labels/symbols found: {len(candidates)}\n")
        handle.write(f"- Marked image previews: {len(marked_images)}\n\n")
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
        handle.write("## Next improvement\n\n")
        handle.write("Validate these candidates against a known LiveCount/historical takeoff sheet, then tune the detector for one fixture family at a time.\n")

    return summary_md, takeoff_csv, review_csv
