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


FIXTURE_LABEL = re.compile(r"^(?:[A-Z]\d{1,2}[A-Z]?|EM\d?[A-Z]?|EMS|EXIT|X\d+[A-Z]?)(?:[a-z])?$")
LABEL_NOISE = {"OS", "VS", "J", "A", "B", "C", "D", "E", "N", "S", "T"}


def _review_category_for_label(label: str) -> str:
    """Separate strong fixture labels from tags that should stay visible but not trusted blindly."""
    upper = label.upper()
    if upper == "EXIT" or upper.startswith("EM") or upper == "EMS":
        return "likely_fixture_tag"
    if re.match(r"^[A-Z]\d{1,2}[A-Z]?$", upper):
        return "likely_fixture_tag"
    if re.match(r"^X\d+[A-Z]?$", upper):
        return "possible_fixture_tag"
    return "possible_fixture_tag"


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

    def visitor(text: str, cm, tm, font, size) -> None:
        raw_tokens = re.split(r"\s+", text.strip())
        for token in raw_tokens:
            clean = token.strip().upper()
            if clean in LABEL_NOISE or not FIXTURE_LABEL.match(token.strip()):
                continue
            x = int(float(tm[4]) * scale_x)
            y = int((page_h - float(tm[5])) * scale_y)
            if x < left or x > right or y < top or y > bottom:
                continue
            box_w = max(16, int(len(clean) * float(size) * scale_x * 0.62))
            box_h = max(10, int(float(size) * scale_y * 1.25))
            candidates.append(
                FixtureCandidate(
                    sheet_number=sheet_number,
                    source_image=image_path,
                    x=x,
                    y=max(0, y - box_h),
                    width=box_w,
                    height=box_h,
                    symbol_type=f"fixture_label_{clean}",
                    confidence=0.86,
                    reason="embedded PDF text label positioned on lighting plan",
                    review_category=_review_category_for_label(clean),
                )
            )

    try:
        page.extract_text(visitor_text=visitor)
    except Exception:
        return []
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
            if cand.review_category == "likely_fixture_tag":
                color = (255, 0, 0)
            elif cand.review_category == "possible_fixture_tag":
                color = (255, 165, 0)
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
    summary_md = out_dir / "light_fixture_detection.md"

    counts = Counter((cand.sheet_number, cand.symbol_type, cand.review_category) for cand in candidates)
    category_counts = Counter(cand.review_category for cand in candidates)

    with takeoff_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["item", "quantity", "sheet", "location", "confidence", "reason", "review_category", "review_required"])
        for (sheet, symbol_type, review_category), qty in sorted(counts.items()):
            sheet_candidates = [
                c
                for c in candidates
                if c.sheet_number == sheet and c.symbol_type == symbol_type and c.review_category == review_category
            ]
            avg_conf = sum(c.confidence for c in sheet_candidates) / max(1, len(sheet_candidates))
            if symbol_type.startswith("fixture_label_"):
                item_name = f"LIGHT FIXTURE TAG {symbol_type.removeprefix('fixture_label_')}"
                if review_category == "likely_fixture_tag":
                    reason = "embedded PDF fixture label positioned on lighting plan"
                else:
                    reason = "embedded PDF fixture-like label; estimator should confirm it is a fixture schedule tag"
            else:
                item_name = f"LIGHT FIXTURE CANDIDATE - {symbol_type}"
                reason = "visual rectangular/linear fixture candidates"
            writer.writerow(
                [
                    item_name,
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
        writer.writerow(["sheet", "symbol_type", "x", "y", "width", "height", "confidence", "reason", "review_category", "source_image"])
        for cand in candidates:
            writer.writerow(
                [
                    cand.sheet_number,
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
        handle.write("# Light fixture symbol detection\n\n")
        handle.write("This is the first Phase 3 detector. It uses embedded PDF fixture labels when available, then falls back to rendered-sheet visual linework heuristics.\n\n")
        handle.write("This is not final takeoff yet. Every count is marked `review_required` until validated against LiveCount, Accubid, or human takeoff.\n\n")
        handle.write("## Summary\n\n")
        handle.write(f"- Rendered sheet images scanned: {len(images)}\n")
        handle.write(f"- Candidate fixture labels/symbols found: {len(candidates)}\n")
        handle.write(f"- Marked image previews: {len(marked_images)}\n\n")
        handle.write("## Candidate quality buckets\n\n")
        if category_counts:
            for category, qty in sorted(category_counts.items()):
                handle.write(f"- {category}: {qty}\n")
        else:
            handle.write("- No candidate quality buckets found.\n")
        handle.write("\n")
        handle.write("## Counts by sheet/type\n\n")
        for (sheet, symbol_type, review_category), qty in sorted(counts.items()):
            handle.write(f"- {sheet} / {symbol_type} / {review_category}: {qty}\n")
        if not counts:
            handle.write("- No fixture candidates found.\n")
        handle.write("\n## Outputs\n\n")
        handle.write("- `takeoff_items.csv`\n")
        handle.write("- `estimator_review.csv`\n")
        handle.write("- `marked_up_drawings.pdf`\n")
        handle.write("- `marked_images/`\n\n")
        handle.write("## Next improvement\n\n")
        handle.write("Validate these candidates against a known LiveCount/historical takeoff sheet, then tune the detector for one fixture family at a time.\n")

    return summary_md, takeoff_csv, review_csv
