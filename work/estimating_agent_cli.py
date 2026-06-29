from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from work.estimating_agent.audit import audit_fixture_sheets, write_project_audit_report
from work.estimating_agent.drawing_check import (
    investigate_missing_labels,
    summarize_missing_labels,
    validate_drawings_against_training_set,
)
from work.estimating_agent.drawing_estimator import (
    write_count_outputs,
    write_estimate_starter,
    write_scan_outputs as write_drawing_scan_outputs,
)
from work.estimating_agent.drawing_intelligence import write_drawing_intelligence_outputs
from work.estimating_agent.estimator_workflow import run_estimator_workflow
from work.estimating_agent.livecount_tpx import read_tpx
from work.estimating_agent.project_scan import project_dirs, scan_project, write_scan_outputs
from work.estimating_agent.project_intake import write_intake_outputs
from work.estimating_agent.sheet_map import read_sheet_map, write_sheet_map_template
from work.estimating_agent.symbol_detection import detect_light_fixtures
from work.estimating_agent.symbol_validation import (
    validate_symbol_detections,
    validate_symbol_detections_against_counts_csv,
)
from work.estimating_agent.training_set import build_training_set
from work.estimating_agent.validation import validate_training_set
from work.estimating_agent.web_accubid_prep import write_web_accubid_prep
from work.estimating_agent.worker_mode import run_full_worker_mode


def main() -> None:
    if len(sys.argv) == 2 and sys.argv[1] in {"-h", "--help"}:
        print(
            "\n".join(
                [
                    "Estimator coworker agent",
                    "",
                    "Primary workflow:",
                    "  estimate-project --project-folder <PROJECT_FOLDER> --out-dir <OUTPUT_FOLDER>",
                    "",
                    "What it produces:",
                    "  project_dashboard.md",
                    "  takeoff_items.csv",
                    "  estimator_review.csv",
                    "  accubid_mapping.csv",
                    "  marked_up_drawings.pdf",
                    "  validation_answer_key_template.csv",
                    "",
                    "Support/experimental commands still exist for development, but estimate-project is the estimator-facing entrypoint.",
                ]
            )
        )
        return

    parser = argparse.ArgumentParser(
        description=(
            "Estimator coworker agent. Primary command: estimate-project. "
            "Other commands are lower-level support/experimental tools."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True, metavar="{estimate-project}")

    estimate_project_parser = subparsers.add_parser(
        "estimate-project",
        help="PRIMARY WORKFLOW: run the estimator coworker on a project folder and produce the main output contract.",
    )
    estimate_project_parser.add_argument("--project-folder", type=Path, required=True)
    estimate_project_parser.add_argument("--out-dir", type=Path, required=True)
    estimate_project_parser.add_argument("--project-name")
    estimate_project_parser.add_argument("--max-sheets", type=int, default=6)
    estimate_project_parser.add_argument("--min-confidence", type=float, default=0.55)

    audit_parser = subparsers.add_parser(
        "audit-tpx",
        help=argparse.SUPPRESS,
    )
    audit_parser.add_argument("--project-name", required=True)
    audit_parser.add_argument("--tpx", type=Path, required=True)
    audit_parser.add_argument("--out", type=Path, required=True)
    audit_parser.add_argument("--sheet-map", type=Path)

    init_parser = subparsers.add_parser(
        "init-project",
        help=argparse.SUPPRESS,
    )
    init_parser.add_argument("--project-name", required=True)
    init_parser.add_argument("--out-dir", type=Path, required=True)

    scan_parser = subparsers.add_parser(
        "scan-projects",
        help=argparse.SUPPRESS,
    )
    scan_parser.add_argument("--root", type=Path, required=True)
    scan_parser.add_argument("--out-dir", type=Path, required=True)
    scan_parser.add_argument("--limit", type=int, default=50)
    scan_parser.add_argument("--max-files-per-project", type=int, default=5000)
    scan_parser.add_argument("--quiet", action="store_true")

    train_parser = subparsers.add_parser(
        "build-training-set",
        help=argparse.SUPPRESS,
    )
    train_parser.add_argument("--scan-csv", type=Path, required=True)
    train_parser.add_argument("--out-dir", type=Path, required=True)
    train_parser.add_argument("--grades", default="good_training_candidate")
    train_parser.add_argument("--limit", type=int, default=10)

    validate_parser = subparsers.add_parser(
        "validate-training-set",
        help=argparse.SUPPRESS,
    )
    validate_parser.add_argument("--manifest", type=Path, required=True)
    validate_parser.add_argument("--out-dir", type=Path, required=True)

    drawing_parser = subparsers.add_parser(
        "check-drawing-labels",
        help=argparse.SUPPRESS,
    )
    drawing_parser.add_argument("--manifest", type=Path, required=True)
    drawing_parser.add_argument("--out-dir", type=Path, required=True)

    missing_parser = subparsers.add_parser(
        "investigate-missing-labels",
        help=argparse.SUPPRESS,
    )
    missing_parser.add_argument("--manifest", type=Path, required=True)
    missing_parser.add_argument("--details", type=Path, required=True)
    missing_parser.add_argument("--out-dir", type=Path, required=True)
    missing_parser.add_argument("--limit", type=int, default=30)

    unresolved_parser = subparsers.add_parser(
        "summarize-missing-labels",
        help=argparse.SUPPRESS,
    )
    unresolved_parser.add_argument("--details", type=Path, required=True)
    unresolved_parser.add_argument("--out-dir", type=Path, required=True)

    intake_parser = subparsers.add_parser(
        "intake-project",
        help=argparse.SUPPRESS,
    )
    intake_parser.add_argument("--project-folder", type=Path, required=True)
    intake_parser.add_argument("--out-dir", type=Path, required=True)

    scan_drawing_parser = subparsers.add_parser(
        "scan-drawing",
        help=argparse.SUPPRESS,
    )
    scan_drawing_parser.add_argument("--input", type=Path, required=True)
    scan_drawing_parser.add_argument("--out-dir", type=Path, required=True)
    scan_drawing_parser.add_argument("--max-pages", type=int)

    count_item_parser = subparsers.add_parser(
        "count-item",
        help=argparse.SUPPRESS,
    )
    count_item_parser.add_argument("--input", type=Path, required=True)
    count_item_parser.add_argument("--item", required=True)
    count_item_parser.add_argument("--out-dir", type=Path, required=True)
    count_item_parser.add_argument("--max-pages", type=int)

    estimate_drawing_parser = subparsers.add_parser(
        "estimate-drawing",
        help=argparse.SUPPRESS,
    )
    estimate_drawing_parser.add_argument("--input", type=Path, required=True)
    estimate_drawing_parser.add_argument("--out-dir", type=Path, required=True)
    estimate_drawing_parser.add_argument("--max-pages", type=int)

    web_accubid_parser = subparsers.add_parser(
        "web-accubid-prep",
        help=argparse.SUPPRESS,
    )
    web_accubid_parser.add_argument("--input", type=Path, required=True)
    web_accubid_parser.add_argument("--out-dir", type=Path, required=True)
    web_accubid_parser.add_argument("--project-name")
    web_accubid_parser.add_argument("--max-pages", type=int)
    web_accubid_parser.add_argument("--item-limit", type=int, default=80)

    worker_parser = subparsers.add_parser(
        "full-worker",
        help=argparse.SUPPRESS,
    )
    worker_parser.add_argument("--project-folder", type=Path, required=True)
    worker_parser.add_argument("--out-dir", type=Path, required=True)
    worker_parser.add_argument("--project-name")

    drawing_intel_parser = subparsers.add_parser(
        "drawing-intelligence",
        help=argparse.SUPPRESS,
    )
    drawing_intel_parser.add_argument("--project-folder", type=Path, required=True)
    drawing_intel_parser.add_argument("--sheet-index", type=Path, required=True)
    drawing_intel_parser.add_argument("--out-dir", type=Path, required=True)
    drawing_intel_parser.add_argument("--max-pages", type=int, default=80)
    drawing_intel_parser.add_argument("--max-sheets", type=int, default=12)

    light_fixture_parser = subparsers.add_parser(
        "detect-light-fixtures",
        help=argparse.SUPPRESS,
    )
    light_fixture_parser.add_argument("--rendered-sheets-dir", type=Path, required=True)
    light_fixture_parser.add_argument("--out-dir", type=Path, required=True)
    light_fixture_parser.add_argument("--min-confidence", type=float, default=0.55)

    validate_symbols_parser = subparsers.add_parser(
        "validate-detections",
        help=argparse.SUPPRESS,
    )
    validate_symbols_parser.add_argument("--detections", type=Path, required=True)
    validate_symbols_parser.add_argument("--tpx", type=Path, required=True)
    validate_symbols_parser.add_argument("--out-dir", type=Path, required=True)

    validate_counts_parser = subparsers.add_parser(
        "validate-detections-csv",
        help=argparse.SUPPRESS,
    )
    validate_counts_parser.add_argument("--detections", type=Path, required=True)
    validate_counts_parser.add_argument("--answer-key", type=Path, required=True)
    validate_counts_parser.add_argument("--out-dir", type=Path, required=True)

    args = parser.parse_args()

    if args.command == "estimate-project":
        result = run_estimator_workflow(
            args.project_folder,
            args.out_dir,
            project_name=args.project_name,
            max_sheets=args.max_sheets,
            min_confidence=args.min_confidence,
        )
        print(result.project_dashboard)
        print(result.takeoff_items)
        print(result.estimator_review)
        print(result.accubid_mapping)
        print(result.marked_up_drawings)
        print(result.validation_answer_key)

    if args.command == "audit-tpx":
        documents, points = read_tpx(args.tpx)
        sheet_map = read_sheet_map(args.sheet_map)
        sheet_audits = audit_fixture_sheets(documents, points, sheet_map)
        write_project_audit_report(args.out, args.project_name, sheet_audits)
        print(args.out)
        print(f"fixture_sheets={len(sheet_audits)}")
        print(f"fixture_points={sum(sheet.total for sheet in sheet_audits)}")

    if args.command == "init-project":
        args.out_dir.mkdir(parents=True, exist_ok=True)
        write_sheet_map_template(args.out_dir / "sheet_map.csv")
        readme = args.out_dir / "README.md"
        readme.write_text(
            "\n".join(
                [
                    f"# {args.project_name} estimating-agent packet",
                    "",
                    "Fill in `sheet_map.csv`, then run `audit-tpx` with the TPX export.",
                    "",
                    "Example:",
                    "",
                    "```powershell",
                    "& 'C:\\Users\\namid\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\python\\python.exe' "
                    "'C:\\Users\\namid\\Documents\\Codex\\2026-06-22\\is\\work\\estimating_agent_cli.py' "
                    "audit-tpx --project-name 'PROJECT NAME' --tpx 'PATH_TO_EXPORT.tpx' "
                    "--sheet-map 'sheet_map.csv' --out 'agent_review.md'",
                    "```",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        print(args.out_dir)

    if args.command == "scan-projects":
        results = []
        for project_dir in project_dirs(args.root, args.limit):
            if not args.quiet:
                print(f"scan {project_dir.name}")
            results.append(scan_project(project_dir, max_files=args.max_files_per_project))
        csv_path, md_path = write_scan_outputs(results, args.out_dir)
        print(csv_path)
        print(md_path)

    if args.command == "build-training-set":
        grades = {grade.strip() for grade in args.grades.split(",") if grade.strip()}
        manifest_path, vocab_path, summary_path = build_training_set(
            args.scan_csv,
            args.out_dir,
            grades,
            args.limit,
        )
        print(manifest_path)
        print(vocab_path)
        print(summary_path)

    if args.command == "validate-training-set":
        details_path, report_path = validate_training_set(args.manifest, args.out_dir)
        print(details_path)
        print(report_path)

    if args.command == "check-drawing-labels":
        details_path, report_path = validate_drawings_against_training_set(
            args.manifest,
            args.out_dir,
        )
        print(details_path)
        print(report_path)

    if args.command == "investigate-missing-labels":
        detail_path, report_path = investigate_missing_labels(
            args.manifest,
            args.details,
            args.out_dir,
            args.limit,
        )
        print(detail_path)
        print(report_path)

    if args.command == "summarize-missing-labels":
        missing_path, report_path = summarize_missing_labels(args.details, args.out_dir)
        print(missing_path)
        print(report_path)

    if args.command == "intake-project":
        dashboard_md, project_files_csv, sheets_csv = write_intake_outputs(
            args.project_folder,
            args.out_dir,
        )
        print(dashboard_md)
        print(project_files_csv)
        print(sheets_csv)

    if args.command == "scan-drawing":
        report_md, page_csv, item_csv = write_drawing_scan_outputs(
            args.input,
            args.out_dir,
            max_pages=args.max_pages,
        )
        print(report_md)
        print(page_csv)
        print(item_csv)

    if args.command == "count-item":
        report_md, csv_path = write_count_outputs(
            args.input,
            args.item,
            args.out_dir,
            max_pages=args.max_pages,
        )
        print(report_md)
        print(csv_path)

    if args.command == "estimate-drawing":
        coworker_md, page_csv, item_csv = write_estimate_starter(
            args.input,
            args.out_dir,
            max_pages=args.max_pages,
        )
        print(coworker_md)
        print(page_csv)
        print(item_csv)

    if args.command == "web-accubid-prep":
        report_md, task_csv, mapping_csv, page_csv, workflow_md = write_web_accubid_prep(
            args.input,
            args.out_dir,
            project_name=args.project_name,
            max_pages=args.max_pages,
            item_limit=args.item_limit,
        )
        print(report_md)
        print(task_csv)
        print(mapping_csv)
        print(page_csv)
        print(workflow_md)

    if args.command == "full-worker":
        result = run_full_worker_mode(
            args.project_folder,
            args.out_dir,
            project_name=args.project_name,
        )
        print(result.dashboard)
        print(result.out_dir)

    if args.command == "drawing-intelligence":
        dashboard_md, page_map_csv, regions_csv = write_drawing_intelligence_outputs(
            args.project_folder,
            args.sheet_index,
            args.out_dir,
            max_pages=args.max_pages,
            max_sheets=args.max_sheets,
        )
        print(dashboard_md)
        print(page_map_csv)
        print(regions_csv)

    if args.command == "detect-light-fixtures":
        summary_md, takeoff_csv, review_csv = detect_light_fixtures(
            args.rendered_sheets_dir,
            args.out_dir,
            min_confidence=args.min_confidence,
        )
        print(summary_md)
        print(takeoff_csv)
        print(review_csv)

    if args.command == "validate-detections":
        details_csv, report_md = validate_symbol_detections(
            args.detections,
            args.tpx,
            args.out_dir,
        )
        print(details_csv)
        print(report_md)

    if args.command == "validate-detections-csv":
        details_csv, report_md = validate_symbol_detections_against_counts_csv(
            args.detections,
            args.answer_key,
            args.out_dir,
        )
        print(details_csv)
        print(report_md)


if __name__ == "__main__":
    main()
