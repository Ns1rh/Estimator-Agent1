from __future__ import annotations

import csv
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

from .audit import read_counts_csv


MAX_PDFS_PER_PROJECT = 12
MAX_PAGES_PER_PDF = 80


@dataclass(frozen=True)
class LabelCheck:
    project_name: str
    fixture_type: str
    livecount_count: int
    found_in_pdfs: bool
    hit_count: int
    sample_pdf: str = ""


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.upper())


def label_variants(label: str) -> list[str]:
    raw = label.upper().strip()
    if not raw:
        return []
    variants = {raw}
    variants.add(raw.replace("\\'", "'"))
    variants.add(raw.replace("'", " FT"))
    variants.add(raw.replace("'", "FT"))
    variants.add(raw.replace("-", " "))
    variants.add(raw.replace("(", "").replace(")", ""))
    variants.add(re.sub(r"\s+", "", raw))
    variants.add(re.sub(r"[^A-Z0-9]+", " ", raw).strip())
    return [variant for variant in variants if variant]


def label_patterns(label: str) -> list[re.Pattern]:
    variants = label_variants(label)
    if not variants:
        return []
    raw = variants[0]
    patterns: list[re.Pattern] = []
    for variant in variants:
        escaped = re.escape(variant).replace(r"\ ", r"\s+")
        patterns.append(re.compile(rf"(?<![A-Z0-9]){escaped}(?![A-Z0-9])"))

    raw = label.upper().strip()
    escaped = re.escape(raw).replace(r"\ ", r"\s+")

    # Also test the first token for labels like "F2 EM", but skip generic words.
    first = raw.split()[0]
    if len(first) >= 2 and first not in {"EM", "EXIT", "SIGN", "REINSTALL"}:
        patterns.append(re.compile(rf"(?<![A-Z0-9]){re.escape(first)}(?![A-Z0-9])"))
    return patterns


def candidate_pdfs(project_path: Path) -> list[Path]:
    pdfs: list[Path] = []
    for path in project_path.rglob("*.pdf"):
        lower = str(path).lower()
        if any(part in lower for part in ["billing", "waiver", "invoice", "coi", "payapp"]):
            continue
        score = 0
        if "plans" in lower or "drawing" in lower or "dwg" in lower:
            score += 10
        if "spec" in lower or "schedule" in lower:
            score += 5
        if "combined" in lower:
            score += 4
        if "quote" in lower:
            score -= 6
        pdfs.append(path)
    pdfs.sort(key=lambda path: (-("combined" in str(path).lower()), path.stat().st_size))
    return pdfs[:MAX_PDFS_PER_PROJECT]


def all_candidate_pdfs(project_path: Path, limit: int = 50) -> list[Path]:
    pdfs = []
    for path in project_path.rglob("*.pdf"):
        lower = str(path).lower()
        if any(part in lower for part in ["billing", "waiver", "invoice", "coi", "payapp"]):
            continue
        pdfs.append(path)
    pdfs.sort(
        key=lambda path: (
            -("combined" in str(path).lower()),
            -("plan" in str(path).lower() or "drawing" in str(path).lower()),
            path.stat().st_size,
        )
    )
    return pdfs[:limit]


def extract_pdf_text(path: Path, max_pages: int = MAX_PAGES_PER_PDF) -> str:
    chunks: list[str] = []
    try:
        reader = PdfReader(str(path))
        for page in reader.pages[:max_pages]:
            chunks.append(page.extract_text() or "")
    except Exception:
        return ""
    return normalize_text("\n".join(chunks))


def check_project_labels(project_name: str, project_path: Path, packet_dir: Path) -> list[LabelCheck]:
    counts = read_counts_csv(packet_dir / "fixture_counts.csv")
    pdfs = candidate_pdfs(project_path)
    pdf_texts = [(pdf, extract_pdf_text(pdf)) for pdf in pdfs]
    checks: list[LabelCheck] = []
    for fixture_type, count in sorted(counts.items()):
        patterns = label_patterns(fixture_type)
        total_hits = 0
        sample_pdf = ""
        for pdf, text in pdf_texts:
            hits = sum(len(pattern.findall(text)) for pattern in patterns)
            if hits:
                total_hits += hits
                if not sample_pdf:
                    sample_pdf = str(pdf)
        checks.append(
            LabelCheck(
                project_name=project_name,
                fixture_type=fixture_type,
                livecount_count=count,
                found_in_pdfs=total_hits > 0,
                hit_count=total_hits,
                sample_pdf=sample_pdf,
            )
        )
    return checks


def validate_drawings_against_training_set(manifest_csv: Path, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    details_path = out_dir / "drawing_label_check_details.csv"
    report_path = out_dir / "DRAWING_LABEL_CHECK.md"
    all_checks: list[LabelCheck] = []
    project_rows: list[dict] = []

    with manifest_csv.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            checks = check_project_labels(
                row["project_name"],
                Path(row["project_path"]),
                Path(row["packet_dir"]),
            )
            all_checks.extend(checks)
            total_labels = len(checks)
            found_labels = sum(1 for check in checks if check.found_in_pdfs)
            livecount_points = sum(check.livecount_count for check in checks)
            found_points = sum(check.livecount_count for check in checks if check.found_in_pdfs)
            project_rows.append(
                {
                    "project_name": row["project_name"],
                    "labels": total_labels,
                    "labels_found": found_labels,
                    "label_recall": found_labels / total_labels if total_labels else 0,
                    "livecount_points": livecount_points,
                    "points_with_label_found": found_points,
                    "point_weighted_recall": found_points / livecount_points if livecount_points else 0,
                }
            )

    with details_path.open("w", newline="", encoding="utf-8") as handle:
        fieldnames = [
            "project_name",
            "fixture_type",
            "livecount_count",
            "found_in_pdfs",
            "hit_count",
            "sample_pdf",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for check in all_checks:
            writer.writerow(check.__dict__)

    total_labels = len(all_checks)
    found_labels = sum(1 for check in all_checks if check.found_in_pdfs)
    total_points = sum(check.livecount_count for check in all_checks)
    found_points = sum(check.livecount_count for check in all_checks if check.found_in_pdfs)
    missing = [check for check in all_checks if not check.found_in_pdfs]
    missing_by_count = sorted(missing, key=lambda check: check.livecount_count, reverse=True)

    with report_path.open("w", encoding="utf-8") as handle:
        handle.write("# Drawing label check\n\n")
        handle.write("This compares LiveCount fixture labels against searchable text in the project PDFs.\n\n")
        handle.write("## Result\n\n")
        handle.write(f"- Projects checked: {len(project_rows)}\n")
        handle.write(f"- Fixture labels checked: {total_labels}\n")
        handle.write(f"- Fixture labels found in PDFs: {found_labels}\n")
        handle.write(f"- Label recall: {(found_labels / total_labels if total_labels else 0):.1%}\n")
        handle.write(f"- LiveCount fixture points represented by found labels: {found_points} / {total_points}\n")
        handle.write(f"- Point-weighted recall: {(found_points / total_points if total_points else 0):.1%}\n\n")

        handle.write("## By project\n\n")
        handle.write("| Project | Labels found | Label recall | Points covered | Point recall |\n")
        handle.write("|---|---:|---:|---:|---:|\n")
        for row in project_rows:
            handle.write(
                f"| {row['project_name']} | {row['labels_found']} / {row['labels']} | "
                f"{row['label_recall']:.1%} | {row['points_with_label_found']} / {row['livecount_points']} | "
                f"{row['point_weighted_recall']:.1%} |\n"
            )

        handle.write("\n## Biggest labels not found in searchable PDF text\n\n")
        handle.write("| Project | Fixture type | LiveCount count |\n")
        handle.write("|---|---|---:|\n")
        for check in missing_by_count[:40]:
            handle.write(f"| {check.project_name} | {check.fixture_type} | {check.livecount_count} |\n")

        handle.write("\n## Important limitation\n\n")
        handle.write(
            "This is a text-search validation, not a visual takeoff validation. "
            "If a PDF is scanned, flattened, or uses symbols without searchable labels, this check can miss valid items. "
            "A label found in a schedule also does not prove the quantity is correct; it only confirms the label exists in project documents.\n"
        )

    return details_path, report_path


def investigate_missing_labels(
    manifest_csv: Path,
    details_csv: Path,
    out_dir: Path,
    limit: int = 30,
) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {}
    with manifest_csv.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            manifest[row["project_name"]] = row

    missing = []
    with details_csv.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row.get("found_in_pdfs") in {"False", "false", "0", ""}:
                row["livecount_count"] = int(float(row["livecount_count"] or 0))
                missing.append(row)
    missing.sort(key=lambda row: row["livecount_count"], reverse=True)
    missing = missing[:limit]

    detail_path = out_dir / "missing_label_investigation.csv"
    report_path = out_dir / "MISSING_LABEL_INVESTIGATION.md"
    rows = []
    text_cache: dict[Path, str] = {}

    for item in missing:
        project = manifest[item["project_name"]]
        project_path = Path(project["project_path"])
        label = item["fixture_type"]
        patterns = label_patterns(label)
        pdfs = all_candidate_pdfs(project_path, limit=15)
        filename_hits = [
            str(pdf)
            for pdf in pdfs
            if any(variant.replace("\\'", "'").lower() in pdf.name.lower() for variant in label_variants(label))
        ]
        text_hits = []
        readable_pdfs = 0
        for pdf in pdfs:
            if pdf not in text_cache:
                text_cache[pdf] = extract_pdf_text(pdf, max_pages=25)
            text = text_cache[pdf]
            if text:
                readable_pdfs += 1
            hits = sum(len(pattern.findall(text)) for pattern in patterns)
            if hits:
                text_hits.append((str(pdf), hits))

        if text_hits:
            classification = "found_with_deeper_pdf_search"
        elif filename_hits:
            classification = "label_only_in_filename"
        elif readable_pdfs < max(1, len(pdfs) // 3):
            classification = "pdf_text_extraction_weak"
        else:
            classification = "not_found_in_searchable_project_pdfs"

        rows.append(
            {
                "project_name": item["project_name"],
                "fixture_type": label,
                "livecount_count": item["livecount_count"],
                "classification": classification,
                "pdfs_checked": len(pdfs),
                "readable_pdfs": readable_pdfs,
                "text_hit_count": sum(hit_count for _path, hit_count in text_hits),
                "sample_text_hit_pdf": text_hits[0][0] if text_hits else "",
                "sample_filename_hit_pdf": filename_hits[0] if filename_hits else "",
            }
        )

    with detail_path.open("w", newline="", encoding="utf-8") as handle:
        fieldnames = [
            "project_name",
            "fixture_type",
            "livecount_count",
            "classification",
            "pdfs_checked",
            "readable_pdfs",
            "text_hit_count",
            "sample_text_hit_pdf",
            "sample_filename_hit_pdf",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    by_class = Counter(row["classification"] for row in rows)
    with report_path.open("w", encoding="utf-8") as handle:
        handle.write("# Missing label investigation\n\n")
        handle.write("This investigates the largest LiveCount labels not found by the first drawing-label check.\n\n")
        handle.write("## Summary\n\n")
        handle.write(f"- Missing labels investigated: {len(rows)}\n")
        for name, count in sorted(by_class.items()):
            handle.write(f"- {name}: {count}\n")
        handle.write("\n## Investigated labels\n\n")
        handle.write("| Classification | Project | Fixture type | LiveCount count | PDFs checked | Text hits |\n")
        handle.write("|---|---|---|---:|---:|---:|\n")
        for row in rows:
            handle.write(
                f"| {row['classification']} | {row['project_name']} | {row['fixture_type']} | "
                f"{row['livecount_count']} | {row['pdfs_checked']} | {row['text_hit_count']} |\n"
            )
        handle.write("\n## What this means\n\n")
        handle.write("- `found_with_deeper_pdf_search` means the earlier check likely missed a PDF.\n")
        handle.write("- `pdf_text_extraction_weak` means OCR/visual inspection may be needed.\n")
        handle.write("- `not_found_in_searchable_project_pdfs` is the strongest warning bucket.\n")

    return detail_path, report_path


def summarize_missing_labels(details_csv: Path, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    missing_path = out_dir / "unresolved_missing_labels.csv"
    report_path = out_dir / "UNRESOLVED_MISSING_LABELS.md"

    missing = []
    project_totals: dict[str, Counter] = defaultdict(Counter)
    with details_csv.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            count = int(float(row.get("livecount_count") or 0))
            project = row["project_name"]
            project_totals[project]["total_labels"] += 1
            project_totals[project]["total_points"] += count
            if row.get("found_in_pdfs") in {"True", "true", "1"}:
                project_totals[project]["found_labels"] += 1
                project_totals[project]["found_points"] += count
            else:
                row["livecount_count"] = count
                missing.append(row)
                project_totals[project]["missing_labels"] += 1
                project_totals[project]["missing_points"] += count

    missing.sort(key=lambda row: int(row["livecount_count"]), reverse=True)
    with missing_path.open("w", newline="", encoding="utf-8") as handle:
        fieldnames = ["project_name", "fixture_type", "livecount_count", "recommended_followup"]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in missing:
            writer.writerow(
                {
                    "project_name": row["project_name"],
                    "fixture_type": row["fixture_type"],
                    "livecount_count": row["livecount_count"],
                    "recommended_followup": "visual/OCR check against schedule or plan sheet",
                }
            )

    weak_projects = sorted(
        project_totals.items(),
        key=lambda item: item[1]["missing_points"],
        reverse=True,
    )
    with report_path.open("w", encoding="utf-8") as handle:
        handle.write("# Unresolved missing labels\n\n")
        handle.write(
            "These are LiveCount fixture labels that were not found in searchable PDF text after the improved label check. "
            "They should not automatically be treated as estimator errors; many may be PDF text/OCR limitations or symbol-only labels.\n\n"
        )
        handle.write("## Weakest projects by unresolved point count\n\n")
        handle.write("| Project | Missing labels | Missing points | Point recall |\n")
        handle.write("|---|---:|---:|---:|\n")
        for project, counts in weak_projects:
            total_points = counts["total_points"]
            found_points = counts["found_points"]
            recall = found_points / total_points if total_points else 0
            handle.write(
                f"| {project} | {counts['missing_labels']} | {counts['missing_points']} | {recall:.1%} |\n"
            )

        handle.write("\n## Highest-impact unresolved labels\n\n")
        handle.write("| Project | Fixture type | LiveCount count | Follow-up |\n")
        handle.write("|---|---|---:|---|\n")
        for row in missing[:40]:
            handle.write(
                f"| {row['project_name']} | {row['fixture_type']} | {row['livecount_count']} | visual/OCR check |\n"
            )

        handle.write("\n## Practical next step\n\n")
        handle.write(
            "Start with the top two weak projects and render the relevant electrical sheets. "
            "If the labels are visible but not searchable, add OCR/vision. "
            "If the labels are not visible anywhere, flag as a possible LiveCount naming/scope issue.\n"
        )

    return missing_path, report_path
