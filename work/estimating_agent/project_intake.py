from __future__ import annotations

import csv
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader


NOISE_PARTS = {"billing", "waivers", "invoice", "invoices", "coi", "payapps", "tax exemption"}
SHEET_NUMBER = re.compile(
    r"""
    \b
    (?:
        (?:E|ED|EL|EP|FA|LV|AV|SE|T)\d{1,2}\.\d{1,2}[A-Z]? |
        (?:E|ED|EL|EP|FA|LV|AV|SE|T)-\d{2,3}[A-Z]? |
        (?:E|ED|EL|EP|FA|LV|AV|SE|T)\d{3}[A-Z]?
    )
    \b
    """,
    re.IGNORECASE | re.VERBOSE,
)
SHEET_LIST_LINE = re.compile(
    r"^\s*((?:E|ED|EL|EP|FA|LV|AV|SE|T)\d{1,2}\.\d{1,2}[A-Z]?|(?:E|ED|EL|EP|FA|LV|AV|SE|T)-\d{2,3}[A-Z]?|(?:E|ED|EL|EP|FA|LV|AV|SE|T)\d{3}[A-Z]?)\s+(.{4,120})\s*$",
    re.IGNORECASE,
)
SHEET_INDEX_WORDS = {
    "sheet index",
    "drawing index",
    "index of drawings",
    "sheet list",
    "list of drawings",
}
ELECTRICAL_KEYWORDS = {
    "electrical",
    "lighting",
    "light fixture",
    "luminaire",
    "power",
    "receptacle",
    "branch power",
    "panel",
    "panelboard",
    "one-line",
    "one line",
    "riser",
    "fire alarm",
    "low voltage",
    "telecom",
    "data",
    "security",
    "disconnect",
    "transformer",
}
FIXTURE_TAG = re.compile(
    r"\b(?:F\d+[A-Z]?|L\d+[A-Z]?|A\d*|B\d*|C\d*|D\d*|EXIT|EM|EBU|X\d+[A-Z-]*|LP-[A-Z0-9-]+)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PdfCandidate:
    path: Path
    kind: str
    size: int
    score: int


@dataclass(frozen=True)
class ProjectFile:
    path: Path
    category: str
    role: str
    extension: str
    size: int
    score: int


@dataclass(frozen=True)
class SheetHit:
    pdf: str
    page: int
    sheet_number: str
    sheet_title: str
    discipline: str
    confidence: float
    reason: str


def is_noise(path: Path) -> bool:
    lower_parts = {part.lower() for part in path.parts}
    return bool(lower_parts & NOISE_PARTS)


def classify_pdf(path: Path) -> tuple[str, int]:
    lower = str(path).lower()
    name = path.name.lower()
    normalized = re.sub(r"[_-]+", " ", lower)
    lower_parts = {part.lower() for part in path.parts}
    score = 0
    kind = "other_pdf"
    if (
        any(word in name for word in ["plan", "drawing", "dwg", "combined", "issue for bid"])
        or "plans" in lower_parts
        or "drawings" in lower_parts
        or "\\dwg" in lower
        or "/dwg" in lower
    ):
        kind = "drawings"
        score += 20
    if any(word in normalized for word in ["spec", "project manual"]):
        kind = "specs"
        score += 15
    if "addendum" in lower or "addenda" in lower or "add#" in lower:
        kind = "addendum"
        score += 12
    if "material testing" in lower or "\\misc\\" in lower or "/misc/" in lower:
        score -= 25
    if any(word in lower for word in ["quote", "proposal", "submittal"]):
        score -= 10
    if "electrical" in lower or "\\e" in lower or "/e" in lower:
        score += 5
    return kind, score


def classify_project_file(path: Path) -> tuple[str, str, int]:
    """Classify a project file for estimator intake.

    This intentionally stays practical instead of clever: the Phase 1 job is to
    organize the project folder so an estimator and the later symbol detector
    know where to look first.
    """
    lower = str(path).lower()
    name = path.name.lower()
    suffix = path.suffix.lower()
    category = "other"
    role = "reference"
    score = 0

    if suffix == ".pdf":
        pdf_kind, pdf_score = classify_pdf(path)
        score += pdf_score
        if pdf_kind == "drawings":
            category = "drawings"
            role = "drawing_set"
        elif pdf_kind == "specs":
            category = "specifications"
            role = "project_manual"
        elif pdf_kind == "addendum":
            category = "addenda"
            role = "addendum"
        else:
            category = "pdf"
    elif suffix in {".tpx", ".tlc"}:
        category = "livecount"
        role = "takeoff_export"
        score += 15
    elif suffix in {".es15", ".es16", ".est", ".ebm"}:
        category = "accubid"
        role = "estimate_file"
        score += 15
    elif suffix in {".xlsx", ".xls", ".csv"}:
        category = "spreadsheet"
        role = "schedule_or_bid_data"
        score += 5

    if "addendum" in lower or "addenda" in lower:
        category = "addenda"
        role = "addendum"
        score += 15
    if any(word in lower for word in ["fixture", "luminaire", "schedule", "panel schedule"]):
        role = "schedule"
        score += 10
    if "spec" in name or "project manual" in lower:
        category = "specifications"
        role = "project_manual"
        score += 10
    if any(word in lower for word in ["plan", "drawing", "dwg", "permit", "bid set"]):
        if suffix == ".pdf":
            category = "drawings"
            role = "drawing_set"
            score += 10
    if is_noise(path):
        category = "administrative_noise"
        role = "ignore_for_takeoff"
        score -= 30

    return category, role, score


def find_project_files(project_folder: Path, limit: int = 2000) -> list[ProjectFile]:
    files: list[ProjectFile] = []
    if project_folder.is_file():
        try:
            size = project_folder.stat().st_size
        except OSError:
            size = 0
        category, role, score = classify_project_file(project_folder)
        return [
            ProjectFile(
                path=project_folder,
                category=category,
                role=role,
                extension=project_folder.suffix.lower(),
                size=size,
                score=score,
            )
        ]
    for path in project_folder.rglob("*"):
        if not path.is_file():
            continue
        if any(part.startswith(".") for part in path.relative_to(project_folder).parts):
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        category, role, score = classify_project_file(path)
        files.append(
            ProjectFile(
                path=path,
                category=category,
                role=role,
                extension=path.suffix.lower(),
                size=size,
                score=score,
            )
        )
        if len(files) >= limit:
            break
    files.sort(key=lambda item: (-item.score, item.category, str(item.path).lower()))
    return files


def find_pdf_candidates(project_folder: Path, limit: int = 40) -> list[PdfCandidate]:
    candidates: list[PdfCandidate] = []
    if project_folder.is_file() and project_folder.suffix.lower() == ".pdf":
        kind, score = classify_pdf(project_folder)
        try:
            size = project_folder.stat().st_size
        except OSError:
            size = 0
        return [PdfCandidate(path=project_folder, kind=kind, size=size, score=score)]
    for path in project_folder.rglob("*.pdf"):
        if is_noise(path):
            continue
        kind, score = classify_pdf(path)
        try:
            size = path.stat().st_size
        except OSError:
            continue
        candidates.append(PdfCandidate(path=path, kind=kind, size=size, score=score))
    candidates.sort(key=lambda item: (-item.score, -("combined" in item.path.name.lower()), -item.size))
    return candidates[:limit]


def extract_page_texts(pdf_path: Path, max_pages: int = 60) -> list[str]:
    texts: list[str] = []
    try:
        reader = PdfReader(str(pdf_path))
        for page in reader.pages[:max_pages]:
            texts.append(page.extract_text() or "")
    except Exception:
        return texts
    return texts


def infer_title(text: str, sheet_number: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    upper_sheet = sheet_number.upper()
    candidates: list[tuple[int, str]] = []
    for idx, line in enumerate(lines):
        line_upper = line.upper()
        if upper_sheet in line_upper:
            candidates.append((100 - min(idx, 40), line))
        elif any(word in line_upper for word in ["LIGHTING", "POWER", "ELECTRICAL", "FIRE ALARM", "LOW VOLTAGE", "ONE-LINE", "SCHEDULE"]):
            candidates.append((75 - min(idx, 40), line))
    if not candidates:
        return ""
    title = max(candidates[:12], key=lambda item: (item[0], len(item[1])))[1]
    title = re.sub(r"^\s*(?:SHEET\s+)?(?:NO\.?|NUMBER)?\s*", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s+", " ", title)
    return title[:120]


def discipline_for(sheet: str, title: str) -> str:
    hay = f"{sheet} {title}".upper()
    sheet_upper = sheet.upper()
    if sheet_upper.startswith("FA") or "FIRE ALARM" in hay:
        return "fire_alarm"
    if sheet_upper.startswith(("LV", "AV", "T")) or any(word in hay for word in ["LOW VOLTAGE", "TELECOM", "DATA", "SECURITY", "ACCESS", "AV "]):
        return "low_voltage"
    if sheet_upper.startswith("EL") or "LIGHT" in hay or "LUMINAIRE" in hay:
        return "lighting"
    if sheet_upper.startswith("EP") or any(word in hay for word in ["POWER", "ONE-LINE", "ONE LINE", "PANEL", "RISER", "DISTRIBUTION"]):
        return "power"
    if sheet_upper.startswith("ED") or "DEMOLITION" in hay or "DEMO" in hay:
        return "electrical_demo"
    if sheet.upper().startswith("E"):
        return "electrical"
    return "other"


def normalize_sheet_number(raw: str) -> str:
    sheet = re.sub(r"\s+", "", raw.upper())
    sheet = sheet.replace("--", "-")
    return sheet


def page_sheet_confidence(text: str, sheet: str, title: str, pdf_name: str) -> tuple[float, str]:
    upper = text.upper()
    lower = text.lower()
    sheet_upper = sheet.upper()
    confidence = 0.35
    reasons: list[str] = ["sheet number found"]

    if any(word in lower for word in SHEET_INDEX_WORDS):
        confidence -= 0.25
        reasons.append("possible sheet-index page")

    keyword_hits = [word for word in ELECTRICAL_KEYWORDS if word.upper() in upper]
    if keyword_hits:
        confidence += min(0.25, 0.04 * len(keyword_hits))
        reasons.append("electrical keywords")

    if title:
        confidence += 0.15
        reasons.append("title inferred")

    if sheet_upper in Path(pdf_name).stem.upper():
        confidence += 0.2
        reasons.append("sheet number in filename")

    if sheet_upper.startswith(("E", "FA", "LV", "AV", "T")):
        confidence += 0.1
        reasons.append("electrical discipline prefix")

    if upper.count(sheet_upper) >= 2:
        confidence += 0.05
        reasons.append("sheet repeated on page")

    confidence = max(0.05, min(0.99, confidence))
    return round(confidence, 2), "; ".join(reasons)


def sheet_list_hits_from_text(text: str) -> list[tuple[str, str]]:
    hits: list[tuple[str, str]] = []
    seen: set[str] = set()
    for line in text.splitlines():
        clean = re.sub(r"\s+", " ", line.strip())
        match = SHEET_LIST_LINE.match(clean)
        if not match:
            continue
        sheet = normalize_sheet_number(match.group(1))
        title = match.group(2).strip(" -:\t")
        title = re.sub(r"\s+", " ", title)[:120]
        if sheet in seen:
            continue
        seen.add(sheet)
        hits.append((sheet, title))
    return hits


def sheet_index_from_pdfs(pdfs: list[PdfCandidate]) -> list[SheetHit]:
    hits: list[SheetHit] = []
    seen = set()
    for candidate in pdfs:
        if candidate.kind not in {"drawings", "addendum"}:
            continue
        for page_index, text in enumerate(extract_page_texts(candidate.path, max_pages=12), 1):
            line_hits = sheet_list_hits_from_text(text)
            if line_hits:
                electrical = line_hits
            else:
                full_matches = [normalize_sheet_number(m.group(0)) for m in SHEET_NUMBER.finditer(text)]
                electrical = []
                for match in full_matches:
                    number_part = re.search(r"(\d{1,3})(?:\.(\d{1,2}))?", match)
                    if number_part and match.startswith("E") and int(number_part.group(1)) > 900:
                        continue
                    if match not in {sheet for sheet, _ in electrical}:
                        electrical.append((match, ""))
                electrical = electrical[:5]
            for sheet, line_title in electrical:
                key = (str(candidate.path), page_index, sheet)
                if key in seen:
                    continue
                seen.add(key)
                title = line_title or infer_title(text, sheet)
                confidence, reason = page_sheet_confidence(text, sheet, title, candidate.path.name)
                if line_title:
                    confidence = min(0.99, round(confidence + 0.12, 2))
                    reason = f"{reason}; sheet-list line"
                hits.append(
                    SheetHit(
                        pdf=str(candidate.path),
                        page=page_index,
                        sheet_number=sheet,
                        sheet_title=title,
                        discipline=discipline_for(sheet, title),
                        confidence=confidence,
                        reason=reason,
                    )
                )
    hits.sort(key=lambda item: (-item.confidence, item.discipline, item.sheet_number, item.page))
    return hits


def schedule_tags_from_pdfs(pdfs: list[PdfCandidate]) -> Counter:
    tags: Counter = Counter()
    for candidate in pdfs:
        if candidate.kind not in {"drawings", "specs", "addendum"}:
            continue
        for text in extract_page_texts(candidate.path, max_pages=40):
            upper = text.upper()
            if not any(word in upper for word in ["FIXTURE", "LUMINAIRE", "LIGHTING", "SCHEDULE", "ELECTRICAL"]):
                continue
            for match in FIXTURE_TAG.finditer(upper):
                tag = match.group(0).upper()
                if len(tag) <= 1:
                    continue
                tags[tag] += 1
    return tags


def write_intake_outputs(project_folder: Path, out_dir: Path) -> tuple[Path, Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    project_files = find_project_files(project_folder)
    pdfs = find_pdf_candidates(project_folder)
    sheets = sheet_index_from_pdfs(pdfs[:15])

    dashboard_md = out_dir / "project_dashboard.md"
    project_files_csv = out_dir / "project_files.csv"
    sheets_csv = out_dir / "electrical_sheet_index.csv"

    with project_files_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["category", "role", "extension", "score", "size", "path"])
        for item in project_files:
            writer.writerow([item.category, item.role, item.extension, item.score, item.size, str(item.path)])

    with sheets_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["discipline", "sheet_number", "sheet_title", "confidence", "reason", "pdf_page", "pdf"])
        for sheet in sheets:
            writer.writerow(
                [
                    sheet.discipline,
                    sheet.sheet_number,
                    sheet.sheet_title,
                    sheet.confidence,
                    sheet.reason,
                    sheet.page,
                    sheet.pdf,
                ]
            )

    disciplines = Counter(sheet.discipline for sheet in sheets)
    file_categories = Counter(item.category for item in project_files)
    file_roles = Counter(item.role for item in project_files)
    schedule_like = [item for item in project_files if item.role == "schedule"]
    addenda = [item for item in project_files if item.category == "addenda"]
    drawing_sets = [item for item in project_files if item.category == "drawings"]
    specs = [item for item in project_files if item.category == "specifications"]

    with dashboard_md.open("w", encoding="utf-8") as handle:
        handle.write(f"# Project dashboard - {project_folder.name}\n\n")
        handle.write(f"Project folder: `{project_folder}`\n\n")

        handle.write("## Phase 1 status\n\n")
        handle.write("The agent organized the project folder for estimating. This is not a takeoff yet; it tells the estimator and the next agent phase where the estimating information probably lives.\n\n")

        handle.write("## Project file inventory\n\n")
        handle.write(f"- Total files classified: {len(project_files)}\n")
        handle.write(f"- Drawing sets: {len(drawing_sets)}\n")
        handle.write(f"- Specifications/project manuals: {len(specs)}\n")
        handle.write(f"- Addenda: {len(addenda)}\n")
        handle.write(f"- Schedule-like files: {len(schedule_like)}\n")
        handle.write(f"- Candidate electrical sheets: {len(sheets)}\n")
        handle.write("\n")

        handle.write("## File categories\n\n")
        for category, count in sorted(file_categories.items()):
            handle.write(f"- {category}: {count}\n")
        handle.write("\n")

        handle.write("## Estimating roles found\n\n")
        for role, count in sorted(file_roles.items()):
            handle.write(f"- {role}: {count}\n")

        handle.write("\n## Best drawing/spec/addendum candidates\n\n")
        handle.write("| Role | Score | File |\n")
        handle.write("|---|---:|---|\n")
        for item in project_files[:25]:
            if item.category in {"drawings", "specifications", "addenda", "livecount", "accubid"} or item.role == "schedule":
                handle.write(f"| {item.role} | {item.score} | {item.path} |\n")

        handle.write("\n## Candidate electrical sheets\n\n")
        handle.write("| Discipline | Sheet | Confidence | Title | Page | Reason |\n")
        handle.write("|---|---|---:|---|---:|---|\n")
        for sheet in sheets[:80]:
            handle.write(
                f"| {sheet.discipline} | {sheet.sheet_number} | {sheet.confidence:.2f} | "
                f"{sheet.sheet_title} | {sheet.page} | {sheet.reason} |\n"
            )
        if not sheets:
            handle.write("| review_required | none | 0.00 | No electrical sheets confidently identified from searchable PDF text. |  | Open the drawing set manually or use OCR/visual detection next. |\n")

        handle.write("\n## Estimator next actions\n\n")
        handle.write("1. Confirm the drawing set and latest addenda are correct.\n")
        handle.write("2. Confirm the electrical sheet index before symbol detection starts.\n")
        handle.write("3. Use the sheet index to run Drawing Intelligence on lighting, power, fire alarm, and low-voltage sheets.\n")
        handle.write("4. Do not start Accubid mapping until symbol counts and schedules are connected.\n\n")

        handle.write("## Primary outputs\n\n")
        handle.write("- `project_dashboard.md`\n")
        handle.write("- `project_files.csv`\n")
        handle.write("- `electrical_sheet_index.csv`\n")

    return dashboard_md, project_files_csv, sheets_csv
