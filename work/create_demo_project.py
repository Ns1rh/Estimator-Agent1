from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import landscape, letter
from reportlab.pdfgen import canvas


def create_demo_project(out_dir: Path) -> Path:
    """Create a safe synthetic project folder for demos and smoke tests."""
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = out_dir / "safe_lighting_plans_demo.pdf"

    c = canvas.Canvas(str(pdf_path), pagesize=landscape(letter))
    width, height = landscape(letter)

    c.setFont("Helvetica-Bold", 18)
    c.drawString(48, height - 54, "E1.1 LIGHTING PLAN - LEVEL 1")
    c.setFont("Helvetica", 9)
    c.drawString(width - 180, height - 54, "SAFE SYNTHETIC DEMO")
    c.drawString(width - 180, 40, "Title block / not counted")

    c.setFont("Helvetica", 8)
    c.drawString(48, height - 86, "GENERAL NOTES - demo only")
    c.drawString(48, height - 100, "Fixture tags in this notes area should not drive the demo count: A1 A2")

    c.setFont("Helvetica-Bold", 11)
    c.drawString(90, height - 140, "OPEN OFFICE")
    c.setFont("Helvetica", 12)
    for x, y, tag in [
        (130, 360, "A1"),
        (240, 360, "A1"),
        (350, 360, "A2"),
        (130, 260, "A1"),
        (240, 260, "A2"),
        (350, 260, "EXIT"),
    ]:
        c.rect(x - 8, y - 5, 36, 18)
        c.drawString(x, y, tag)

    c.showPage()

    c.setFont("Helvetica-Bold", 18)
    c.drawString(48, height - 54, "E4.0 LIGHTING FIXTURE SCHEDULE")
    c.setFont("Helvetica-Bold", 10)
    c.drawString(48, height - 100, "LIGHTING FIXTURE SCHEDULE TAG DESCRIPTION MANUFACTURER MODEL")
    c.setFont("Helvetica", 10)
    c.drawString(48, height - 128, "A1 2x4 LED TROFFER - SAFE DEMO LIGHTING STL-24")
    c.drawString(48, height - 152, "A2 4 INCH LED DOWNLIGHT - SAFE DEMO LIGHTING SDL-4")
    c.drawString(48, height - 176, "EXIT LED EXIT SIGN - SAFE DEMO LIGHTING SEX-1")
    c.drawString(48, height - 220, "SCHEDULE NOTES")
    c.drawString(48, height - 238, "This synthetic file is for estimator-agent demos only.")
    c.save()

    return pdf_path


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Create a safe synthetic estimator-agent demo project.")
    parser.add_argument("--out-dir", type=Path, default=Path("samples/safe_light_fixture_project"))
    args = parser.parse_args()
    pdf = create_demo_project(args.out_dir)
    print(pdf)
