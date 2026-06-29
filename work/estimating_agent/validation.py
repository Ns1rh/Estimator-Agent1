from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

from .audit import read_counts_csv
from .livecount_tpx import fixture_counts_by_page, read_tpx


def validate_training_set(manifest_csv: Path, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    details_path = out_dir / "accuracy_validation_details.csv"
    report_path = out_dir / "ACCURACY_VALIDATION.md"

    rows = []
    with manifest_csv.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            project_name = row["project_name"]
            latest_tpx = Path(row["latest_tpx"])
            packet_dir = Path(row["packet_dir"])
            expected_points = int(float(row["fixture_points"] or 0))

            documents, points = read_tpx(latest_tpx)
            counts_by_page = fixture_counts_by_page(points)
            direct_tpx_points = sum(sum(counter.values()) for counter in counts_by_page.values())

            packet_counts = read_counts_csv(packet_dir / "fixture_counts.csv")
            packet_points = sum(packet_counts.values())
            match = expected_points == direct_tpx_points == packet_points

            rows.append(
                {
                    "project_name": project_name,
                    "expected_points_from_scan": expected_points,
                    "direct_tpx_points": direct_tpx_points,
                    "packet_fixture_count_points": packet_points,
                    "matches": "yes" if match else "no",
                    "fixture_types_in_packet": len(packet_counts),
                    "tpx": str(latest_tpx),
                    "packet_dir": str(packet_dir),
                }
            )

    with details_path.open("w", newline="", encoding="utf-8") as handle:
        fieldnames = [
            "project_name",
            "expected_points_from_scan",
            "direct_tpx_points",
            "packet_fixture_count_points",
            "matches",
            "fixture_types_in_packet",
            "tpx",
            "packet_dir",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    matched = sum(1 for row in rows if row["matches"] == "yes")
    total = len(rows)
    point_errors = [
        abs(row["direct_tpx_points"] - row["packet_fixture_count_points"])
        for row in rows
    ]
    total_abs_error = sum(point_errors)
    total_points = sum(row["direct_tpx_points"] for row in rows)

    with report_path.open("w", encoding="utf-8") as handle:
        handle.write("# Accuracy validation\n\n")
        handle.write("This validates the current agent's TPX extraction accuracy on the training-set packets.\n\n")
        handle.write("## What is being tested\n\n")
        handle.write("- Re-read each selected LiveCount TPX export directly.\n")
        handle.write("- Recount all `FIXTURES` layer points.\n")
        handle.write("- Compare that count to the generated `fixture_counts.csv` packet.\n")
        handle.write("- Compare both against the original project scan result.\n\n")
        handle.write("## Result\n\n")
        handle.write(f"- Projects tested: {total}\n")
        handle.write(f"- Projects with exact count match: {matched} / {total}\n")
        handle.write(f"- Total direct TPX fixture points: {total_points}\n")
        handle.write(f"- Total absolute point error: {total_abs_error}\n")
        accuracy = 1 - (total_abs_error / total_points if total_points else 0)
        handle.write(f"- Count extraction accuracy: {accuracy:.2%}\n\n")
        handle.write("## Project details\n\n")
        handle.write("| Project | Scan count | Direct TPX count | Packet count | Match? |\n")
        handle.write("|---|---:|---:|---:|:---:|\n")
        for row in rows:
            handle.write(
                f"| {row['project_name']} | {row['expected_points_from_scan']} | "
                f"{row['direct_tpx_points']} | {row['packet_fixture_count_points']} | "
                f"{row['matches']} |\n"
            )
        handle.write("\n## Important limitation\n\n")
        handle.write(
            "This does not prove that the estimator counted the drawing correctly. "
            "It proves the agent is accurately reading and reproducing the LiveCount export counts. "
            "The next accuracy layer must compare LiveCount counts against drawing schedules/symbols.\n"
        )

    return details_path, report_path
