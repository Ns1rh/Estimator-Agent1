from __future__ import annotations

import argparse
import csv
import shutil
from pathlib import Path


LIBRARY_FIELDS = [
    "symbol_id",
    "category",
    "name",
    "aliases",
    "description",
    "typical_shape",
    "template_image_path",
    "confidence_base",
    "notes",
    "source_name",
    "source_file",
    "license_status",
]


def _approved(row: dict[str, str]) -> bool:
    return (row.get("approved") or "").strip().lower() == "yes" or (row.get("review_status") or "").strip().lower() == "approved"


def _safe_id(*parts: str) -> str:
    raw = "_".join(part for part in parts if part).lower()
    safe = "".join(ch if ch.isalnum() else "_" for ch in raw)
    while "__" in safe:
        safe = safe.replace("__", "_")
    return safe.strip("_") or "approved_symbol"


def _existing_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    with path.open(newline="", encoding="utf-8") as handle:
        return {row.get("symbol_id", "") for row in csv.DictReader(handle)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Promote manually approved symbol candidates into a private symbol library.")
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--out-library", type=Path, required=True)
    args = parser.parse_args()

    args.out_library.mkdir(parents=True, exist_ok=True)
    library_csv = args.out_library / "symbols.csv"
    templates_dir = args.out_library / "templates"
    templates_dir.mkdir(parents=True, exist_ok=True)

    with args.candidates.open(newline="", encoding="utf-8") as handle:
        candidates = list(csv.DictReader(handle))

    existing = _existing_ids(library_csv)
    promoted: list[dict[str, str]] = []
    for row in candidates:
        if not _approved(row):
            continue
        category = row.get("category", "").strip()
        tag = row.get("tag", "").strip()
        if not category or not tag:
            continue
        symbol_id = _safe_id(category, tag, row.get("source_name", ""))
        base_id = symbol_id
        counter = 2
        while symbol_id in existing:
            symbol_id = f"{base_id}_{counter}"
            counter += 1
        existing.add(symbol_id)
        template_path = row.get("template_image_path", "")
        promoted_template = ""
        if template_path and Path(template_path).exists():
            promoted_file = templates_dir / f"{symbol_id}{Path(template_path).suffix.lower() or '.png'}"
            shutil.copy2(template_path, promoted_file)
            promoted_template = str(promoted_file)
        promoted.append(
            {
                "symbol_id": symbol_id,
                "category": category,
                "name": row.get("description", "") or tag,
                "aliases": row.get("tag", ""),
                "description": row.get("description", ""),
                "typical_shape": "",
                "template_image_path": promoted_template,
                "confidence_base": row.get("confidence", "0.5") or "0.5",
                "notes": row.get("notes", ""),
                "source_name": row.get("source_name", ""),
                "source_file": row.get("source_file", ""),
                "license_status": row.get("license_status", ""),
            }
        )

    write_header = not library_csv.exists()
    with library_csv.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=LIBRARY_FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerows(promoted)

    print(library_csv)
    print(f"promoted={len(promoted)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
