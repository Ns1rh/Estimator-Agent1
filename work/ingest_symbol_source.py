from __future__ import annotations

import argparse
import csv
import re
import shutil
from pathlib import Path

import numpy as np
from PIL import Image


FIELDS = [
    "approved",
    "review_status",
    "source_name",
    "source_file",
    "license_status",
    "page_number",
    "category",
    "tag",
    "description",
    "template_image_path",
    "x",
    "y",
    "width",
    "height",
    "confidence",
    "extraction_method",
    "notes",
]


SOURCE_CATEGORY_CLUES = [
    (re.compile(r"\b(?:lighting|luminaire|light)\b", re.IGNORECASE), "light_fixture", "SYMBOL_SHEET_LIGHT"),
    (re.compile(r"\b(?:outlet|receptacle|socket)\b", re.IGNORECASE), "receptacle", "SYMBOL_SHEET_RECEPTACLE"),
    (re.compile(r"\b(?:switch|dimmer)\b", re.IGNORECASE), "switch", "SYMBOL_SHEET_SWITCH"),
    (re.compile(r"\b(?:fire|alarm|strobe|horn|smoke)\b", re.IGNORECASE), "fire_alarm_device", "SYMBOL_SHEET_FIRE_ALARM"),
    (re.compile(r"\b(?:data|telephone|tele|tv)\b", re.IGNORECASE), "tele_data", "SYMBOL_SHEET_TELE_DATA"),
    (re.compile(r"\b(?:security|doorbell)\b", re.IGNORECASE), "low_voltage", "SYMBOL_SHEET_LOW_VOLTAGE"),
    (re.compile(r"\b(?:thermostat|hvac|ventilation)\b", re.IGNORECASE), "mechanical_reference", "SYMBOL_SHEET_MECHANICAL_REFERENCE"),
]


def _safe_name(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_")
    return safe or "symbol_source"


def _category_guess(source_name: str, source_file: Path) -> tuple[str, str, str]:
    text = f"{source_name} {source_file.stem}".replace("_", " ").replace("-", " ")
    for pattern, category, tag in SOURCE_CATEGORY_CLUES:
        if pattern.search(text):
            return category, tag, f"Auto-classified from source filename: {source_file.name}"
    return "", "", "Manual approval required before promotion."


def _render_source(source: Path, rendered_dir: Path, source_name: str) -> list[Path]:
    rendered_dir.mkdir(parents=True, exist_ok=True)
    suffix = source.suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}:
        image = Image.open(source).convert("RGB")
        out = rendered_dir / f"{_safe_name(source_name)}_p1.png"
        image.save(out)
        return [out]
    if suffix == ".pdf":
        try:
            import fitz  # type: ignore
        except Exception:
            return []
        doc = fitz.open(str(source))
        paths: list[Path] = []
        for index in range(min(len(doc), 20)):
            page = doc.load_page(index)
            pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0), alpha=False)
            out = rendered_dir / f"{_safe_name(source_name)}_p{index + 1}.png"
            pix.save(str(out))
            paths.append(out)
        doc.close()
        return paths
    if suffix == ".svg":
        copied = rendered_dir / source.name
        shutil.copy2(source, copied)
        return []
    return []


def _component_boxes(mask: np.ndarray) -> list[tuple[int, int, int, int, int]]:
    height, width = mask.shape
    visited = np.zeros(mask.shape, dtype=bool)
    boxes: list[tuple[int, int, int, int, int]] = []
    ys, xs = np.nonzero(mask)
    for sy, sx in zip(ys, xs):
        if visited[sy, sx]:
            continue
        stack = [(int(sx), int(sy))]
        visited[sy, sx] = True
        min_x = max_x = int(sx)
        min_y = max_y = int(sy)
        area = 0
        while stack:
            x, y = stack.pop()
            area += 1
            min_x = min(min_x, x)
            max_x = max(max_x, x)
            min_y = min(min_y, y)
            max_y = max(max_y, y)
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if nx < 0 or ny < 0 or nx >= width or ny >= height:
                    continue
                if visited[ny, nx] or not mask[ny, nx]:
                    continue
                visited[ny, nx] = True
                stack.append((nx, ny))
        boxes.append((min_x, min_y, max_x - min_x + 1, max_y - min_y + 1, area))
    return boxes


def _candidate_rows(
    rendered: list[Path],
    crops_dir: Path,
    source: Path,
    source_name: str,
    license_status: str,
    auto_classify: bool = False,
) -> list[dict[str, str]]:
    crops_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, str]] = []
    for image_path in rendered:
        match = re.search(r"_p(\d+)", image_path.stem)
        page_number = match.group(1) if match else "1"
        image = Image.open(image_path).convert("L")
        arr = np.asarray(image)
        mask = arr < 110
        boxes = _component_boxes(mask)
        kept = 0
        for x, y, w, h, area in boxes:
            if kept >= 80:
                break
            if w < 8 or h < 8 or w > 180 or h > 180:
                continue
            fill = area / max(1, w * h)
            if fill < 0.03 or fill > 0.75:
                continue
            pad = 6
            left = max(0, x - pad)
            top = max(0, y - pad)
            right = min(image.width, x + w + pad)
            bottom = min(image.height, y + h + pad)
            crop_name = f"{_safe_name(source_name)}_p{page_number}_{kept + 1:03d}.png"
            crop_path = crops_dir / crop_name
            Image.open(image_path).crop((left, top, right, bottom)).save(crop_path)
            category, tag, notes = _category_guess(source_name, source) if auto_classify else ("", "", "Manual approval required before promotion.")
            rows.append(
                {
                    "approved": "no",
                    "review_status": "needs_review",
                    "source_name": source_name,
                    "source_file": str(source),
                    "license_status": license_status,
                    "page_number": page_number,
                    "category": category,
                    "tag": tag,
                    "description": tag.replace("_", " ").title() if tag else "",
                    "template_image_path": str(crop_path),
                    "x": str(left),
                    "y": str(top),
                    "width": str(right - left),
                    "height": str(bottom - top),
                    "confidence": "0.35",
                    "extraction_method": "connected_component_crop",
                    "notes": notes,
                }
            )
            kept += 1
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest an approved local symbol source into review candidates.")
    parser.add_argument("--source-file", type=Path, required=True)
    parser.add_argument("--source-name", required=True)
    parser.add_argument("--license-status", required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--auto-classify-from-name", action="store_true", help="Fill category/tag guesses from the source filename while still requiring review before promotion.")
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    rendered = _render_source(args.source_file, args.out_dir / "rendered", args.source_name)
    rows = _candidate_rows(
        rendered,
        args.out_dir / "crops",
        args.source_file,
        args.source_name,
        args.license_status,
        auto_classify=args.auto_classify_from_name,
    )
    candidates_csv = args.out_dir / "symbol_candidates.csv"
    with candidates_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(candidates_csv)
    print(f"rendered_pages={len(rendered)}")
    print(f"candidate_crops={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
