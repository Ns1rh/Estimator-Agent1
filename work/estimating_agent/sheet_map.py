from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SheetInfo:
    page: int
    sheet_number: str = ""
    sheet_title: str = ""
    note: str = ""

    @property
    def label(self) -> str:
        parts = [part for part in [self.sheet_number, self.sheet_title] if part]
        return " - ".join(parts) if parts else f"TPX page {self.page}"


def read_sheet_map(path: Path | None) -> dict[int, SheetInfo]:
    if path is None or not path.exists():
        return {}

    result: dict[int, SheetInfo] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            page_text = (row.get("tpx_page") or row.get("page") or "").strip()
            if not page_text:
                continue
            page = int(page_text)
            result[page] = SheetInfo(
                page=page,
                sheet_number=(row.get("sheet_number") or "").strip(),
                sheet_title=(row.get("sheet_title") or "").strip(),
                note=(row.get("note") or "").strip(),
            )
    return result


def write_sheet_map_template(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["tpx_page", "sheet_number", "sheet_title", "note"])
        writer.writerow(["56", "E1.0", "Lighting Plan", "Example row - verify sheet mapping"])
