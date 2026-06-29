from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .livecount_tpx import TpxDocument, TpxPoint, fixture_counts_by_page
from .sheet_map import SheetInfo


@dataclass(frozen=True)
class SheetAudit:
    page: int
    drawing_number: str
    description: str
    layer: str
    counts: Counter
    sheet_number: str = ""
    sheet_title: str = ""
    sheet_note: str = ""

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    @property
    def label(self) -> str:
        parts = [part for part in [self.sheet_number, self.sheet_title] if part]
        if parts:
            return " - ".join(parts)
        if self.drawing_number:
            return self.drawing_number
        return f"TPX page {self.page}"


def read_counts_csv(path: Path) -> Counter:
    counts = Counter()
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            fixture_type = (row.get("type") or "").strip()
            if fixture_type:
                counts[fixture_type] += int(float(row.get("count") or 0))
    return counts


def write_counts_csv(path: Path, counts: Counter) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["type", "count"])
        for fixture_type, count in sorted(counts.items()):
            writer.writerow([fixture_type, count])


def audit_fixture_sheets(
    documents: list[TpxDocument],
    points: list[TpxPoint],
    sheet_map: dict[int, SheetInfo] | None = None,
) -> list[SheetAudit]:
    sheet_map = sheet_map or {}
    document_by_page = {document.page: document for document in documents}
    fixture_counts = fixture_counts_by_page(points)
    audits: list[SheetAudit] = []
    for page, counts in sorted(fixture_counts.items()):
        document = document_by_page.get(page)
        sheet_info = sheet_map.get(page)
        audits.append(
            SheetAudit(
                page=page,
                drawing_number=(sheet_info.sheet_number if sheet_info and sheet_info.sheet_number else document.drawing_number if document else ""),
                description=document.description if document else "",
                layer="FIXTURES",
                counts=counts,
                sheet_number=sheet_info.sheet_number if sheet_info else "",
                sheet_title=sheet_info.sheet_title if sheet_info else "",
                sheet_note=sheet_info.note if sheet_info else "",
            )
        )
    return audits


def write_project_audit_report(path: Path, project_name: str, sheet_audits: list[SheetAudit]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    grand_total = sum(sheet.total for sheet in sheet_audits)
    fixture_types = sorted({fixture_type for sheet in sheet_audits for fixture_type in sheet.counts})

    with path.open("w", encoding="utf-8") as handle:
        handle.write(f"# {project_name} - LiveCount/Accubid Agent Audit\n\n")
        handle.write("This is an agent-readable summary of the LiveCount takeoff data.\n\n")
        handle.write("## Summary\n\n")
        handle.write(f"- Fixture sheets found: {len(sheet_audits)}\n")
        handle.write(f"- Total fixture points: {grand_total}\n")
        handle.write(f"- Fixture types found: {len(fixture_types)}\n\n")

        handle.write("## Estimator coworker notes\n\n")
        handle.write("Here is what I would look at first before trusting or pushing quantities forward:\n\n")
        if not sheet_audits:
            handle.write("- No fixture takeoff sheets were found in the LiveCount export.\n")
            handle.write("- This may mean the job has no lighting fixture scope, the takeoff uses another layer name, or the TPX export is incomplete.\n\n")
        elif grand_total < 20:
            handle.write(
                "- This is a very small fixture takeoff. Verify whether the project scope is actually this small, "
                "or whether other systems/layers need to be audited.\n\n"
            )
        for sheet in sheet_audits:
            high_count_types = [name for name, count in sheet.counts.items() if count >= 10]
            low_count_types = [name for name, count in sheet.counts.items() if count <= 2]
            handle.write(f"### {sheet.label}\n\n")
            handle.write(f"- LiveCount has {sheet.total} fixture points on this sheet.\n")
            if not sheet.sheet_number and not sheet.sheet_title:
                handle.write("- Sheet name is not mapped yet. Add this TPX page to `sheet_map.csv` for cleaner reports.\n")
            if high_count_types:
                handle.write(f"- Main repeated types: {', '.join(sorted(high_count_types))}.\n")
            if low_count_types:
                handle.write(
                    "- Small-count/special items to manually verify: "
                    f"{', '.join(sorted(low_count_types))}.\n"
                )
            if sheet.sheet_note:
                handle.write(f"- Sheet-map note: {sheet.sheet_note}\n")
            handle.write("\n")

        handle.write("## Fixture sheets\n\n")
        handle.write("| TPX page | Sheet | TPX description | Fixture points |\n")
        handle.write("|---:|---|---|---:|\n")
        for sheet in sheet_audits:
            handle.write(
                f"| {sheet.page} | {sheet.label} | {sheet.description} | {sheet.total} |\n"
            )

        handle.write("\n## Counts by sheet\n\n")
        for sheet in sheet_audits:
            handle.write(f"### {sheet.label}\n\n")
            if sheet.description:
                handle.write(f"{sheet.description}\n\n")
            handle.write("| Type | Count |\n")
            handle.write("|---|---:|\n")
            for fixture_type, count in sorted(sheet.counts.items()):
                handle.write(f"| {fixture_type} | {count} |\n")
            handle.write("\n")

        handle.write("## Agent next checks\n\n")
        handle.write("- Verify small-count/special items first. These are more likely to be missed or miscoded.\n")
        handle.write("- Compare fixture schedule tags against LiveCount fixture types.\n")
        handle.write("- Compare drawing symbols against LiveCount points/quantities.\n")
        handle.write("- Flag sheets with fixtures in drawings but no LiveCount fixture layer.\n")
        handle.write("- Produce Accubid-facing quantity review notes.\n")
