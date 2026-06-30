from __future__ import annotations

import argparse
import csv
import random
import shutil
from dataclasses import dataclass
from pathlib import Path

from reportlab.lib.pagesizes import landscape, letter
from reportlab.pdfgen import canvas


@dataclass(frozen=True)
class FixtureType:
    tag: str
    description: str


@dataclass(frozen=True)
class FixturePlacement:
    sheet_number: str
    sheet_name: str
    tag: str
    x: int
    y: int


ROOM_NAMES = [
    "OPEN OFFICE",
    "EXAM ROOM",
    "WAITING AREA",
    "CORRIDOR",
    "NURSE STATION",
    "IMAGING SUPPORT",
    "CONSULT ROOM",
]

FIXTURE_LIBRARY = [
    FixtureType("A1", "2x4 LED TROFFER - SAFE DEMO LIGHTING STL-24"),
    FixtureType("A2", "4 INCH LED DOWNLIGHT - SAFE DEMO LIGHTING SDL-4"),
    FixtureType("A3", "LINEAR LED SLOT - SAFE DEMO LIGHTING SLS-8"),
    FixtureType("B1", "DECORATIVE WALL SCONCE - SAFE DEMO LIGHTING SWS-1"),
    FixtureType("C1", "UNDERCABINET LED STRIP - SAFE DEMO LIGHTING UCS-2"),
    FixtureType("EM1", "EMERGENCY BATTERY UNIT - SAFE DEMO LIGHTING EBU-1"),
    FixtureType("EXIT", "LED EXIT SIGN - SAFE DEMO LIGHTING SEX-1"),
]


def _sheet_number(rng: random.Random) -> str:
    return rng.choice(["E1.1", "E2.1", "EL1.1", "E101"])


def _schedule_sheet_number(plan_sheet: str) -> str:
    if plan_sheet.startswith("EL"):
        return "EL4.0"
    if plan_sheet.startswith("E10"):
        return "E401"
    return "E4.0"


def _choose_fixture_types(rng: random.Random) -> list[FixtureType]:
    base = rng.sample(FIXTURE_LIBRARY[:6], k=rng.randint(2, 4))
    if rng.random() < 0.8:
        base.append(FIXTURE_LIBRARY[-1])
    return base


def _placements_for_types(
    rng: random.Random,
    sheet_number: str,
    sheet_name: str,
    fixture_types: list[FixtureType],
) -> list[FixturePlacement]:
    placements: list[FixturePlacement] = []
    x_positions = [115, 200, 285, 370, 455, 540]
    y_positions = [370, 320, 270, 220, 170]
    grid = [(x, y) for y in y_positions for x in x_positions]
    rng.shuffle(grid)
    for fixture_type in fixture_types:
        qty = rng.randint(1, 5)
        for _ in range(qty):
            x, y = grid.pop()
            placements.append(
                FixturePlacement(
                    sheet_number=sheet_number,
                    sheet_name=sheet_name,
                    tag=fixture_type.tag,
                    x=x + rng.randint(-5, 5),
                    y=y + rng.randint(-4, 4),
                )
            )
    rng.shuffle(placements)
    return placements


def _draw_title_block(c: canvas.Canvas, width: float, height: float, rng: random.Random, project_name: str) -> None:
    c.setFont("Helvetica", 8)
    if rng.random() < 0.5:
        c.rect(width - 190, 30, 150, height - 80)
        c.drawString(width - 180, height - 54, project_name)
        c.drawString(width - 180, 54, "Title block / sidebar")
    else:
        c.rect(40, 28, width - 80, 54)
        c.drawString(54, 58, project_name)
        c.drawString(width - 210, 58, "Bottom title block / not plan area")


def _write_answer_key(out_dir: Path, project_name: str, source_pdf: Path, placements: list[FixturePlacement]) -> Path:
    answer_dir = out_dir / "answer_key"
    answer_dir.mkdir(parents=True, exist_ok=True)
    answer_csv = answer_dir / "fixture_counts.csv"
    counts: dict[tuple[str, str], int] = {}
    sheet_names: dict[str, str] = {}
    for placement in placements:
        counts[(placement.sheet_number, placement.tag)] = counts.get((placement.sheet_number, placement.tag), 0) + 1
        sheet_names[placement.sheet_number] = placement.sheet_name
    with answer_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["project_name", "source_file", "sheet_number", "sheet_name", "category", "tag", "reviewed_quantity", "notes"])
        for (sheet_number, tag), qty in sorted(counts.items()):
            writer.writerow([project_name, str(source_pdf), sheet_number, sheet_names.get(sheet_number, ""), "LIGHT FIXTURE", tag, qty, "Synthetic answer key; validation only."])
    return answer_csv


def create_demo_project(out_dir: Path, seed: int = 1) -> Path:
    """Create a safe synthetic project folder for demos and smoke tests.

    The generated answer key is stored under answer_key/ and is not used by
    estimate-project. It is only for after-the-fact validation.
    """
    rng = random.Random(seed)
    out_dir.mkdir(parents=True, exist_ok=True)
    for old_pdf in out_dir.glob("safe*.pdf"):
        old_pdf.unlink()
    answer_dir = out_dir / "answer_key"
    if answer_dir.exists():
        shutil.rmtree(answer_dir)

    project_name = f"Safe Synthetic Lighting Project {seed}"
    plan_sheet = _sheet_number(rng)
    plan_title = rng.choice(["LIGHTING PLAN - LEVEL 1", "LIGHTING PLAN - AREA A", "LIGHTING FLOOR PLAN"])
    schedule_sheet = _schedule_sheet_number(plan_sheet)
    fixture_types = _choose_fixture_types(rng)
    placements = _placements_for_types(rng, plan_sheet, plan_title, fixture_types)
    unused_schedule = rng.choice([item for item in FIXTURE_LIBRARY if item not in fixture_types])

    pdf_path = out_dir / f"safe_lighting_plans_seed_{seed}.pdf"
    c = canvas.Canvas(str(pdf_path), pagesize=landscape(letter))
    width, height = landscape(letter)

    c.setFont("Helvetica-Bold", 18)
    c.drawString(48, height - 54, f"{plan_sheet} {plan_title}")
    _draw_title_block(c, width, height, rng, project_name)

    c.setFont("Helvetica", 8)
    c.drawString(48, height - 88, rng.choice(["GENERAL NOTES", "LIGHTING NOTES", "SHEET NOTES"]))
    decoys = " ".join(item.tag for item in rng.sample(FIXTURE_LIBRARY, k=2))
    c.drawString(48, height - 102, f"Tags in notes/sidebar are review noise, not plan counts: {decoys}")

    c.setFont("Helvetica-Bold", 11)
    c.drawString(88, height - 145, rng.choice(ROOM_NAMES))
    c.setFont("Helvetica", 12)
    for placement in placements:
        c.rect(placement.x - 8, placement.y - 5, 38, 18)
        c.drawString(placement.x, placement.y, placement.tag)

    c.setFont("Helvetica", 8)
    c.drawString(610, 300, "SYMBOL LEGEND")
    c.drawString(610, 286, "A1 = fixture tag example")
    c.showPage()

    c.setFont("Helvetica-Bold", 18)
    c.drawString(48, height - 54, f"{schedule_sheet} LIGHTING FIXTURE SCHEDULE")
    c.setFont("Helvetica-Bold", 10)
    c.drawString(48, height - 100, "LIGHTING FIXTURE SCHEDULE TAG DESCRIPTION MANUFACTURER MODEL")
    c.setFont("Helvetica", 10)
    schedule_rows = [*fixture_types, unused_schedule]
    rng.shuffle(schedule_rows)
    y = height - 128
    for fixture_type in schedule_rows:
        c.drawString(48, y, f"{fixture_type.tag} {fixture_type.description}")
        y -= 24
    c.drawString(48, y - 20, "SCHEDULE NOTES")
    c.drawString(48, y - 38, "Synthetic file for estimator-agent capability checks only.")
    c.save()

    _write_answer_key(out_dir, project_name, pdf_path, placements)
    return pdf_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create a safe synthetic estimator-agent demo project.")
    parser.add_argument("--out-dir", type=Path, default=Path("samples/safe_light_fixture_project"))
    parser.add_argument("--seed", type=int, default=1, help="Deterministic random seed. Same seed produces the same safe project.")
    args = parser.parse_args()
    pdf = create_demo_project(args.out_dir, seed=args.seed)
    print(pdf)
