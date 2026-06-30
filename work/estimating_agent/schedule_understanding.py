from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

from .project_intake import find_pdf_candidates


@dataclass(frozen=True)
class FixtureScheduleEntry:
    tag: str
    description: str
    source_pdf: Path
    page: int
    confidence: float
    reason: str


SCHEDULE_TITLE_WORDS = (
    "LIGHTING FIXTURE SCHEDULE",
    "LIGHT FIXTURE SCHEDULE",
    "LUMINAIRE SCHEDULE",
    "FIXTURE SCHEDULE",
    "FIRE ALARM DEVICE SCHEDULE",
    "FIRE ALARM SCHEDULE",
)

SCHEDULE_ROW_TAG = re.compile(r"(?<![A-Z0-9])(?:[A-Z]\d{1,2}[A-Z]?|EM\d?[A-Z]?|EMS|EXIT|EX|X\d*[A-Z]?|SD|HD|DD|PS|PULL|HS|H/S|FACP|FAAP|NAC|MM|MON|CM|CTRL)(?![a-z])", re.IGNORECASE)


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _tag_from_item(item: str) -> str:
    marker = "LIGHT FIXTURE TAG "
    upper = (item or "").upper()
    if upper.startswith(marker):
        return upper[len(marker) :].strip()
    return upper.strip()


def tags_from_takeoff_items(takeoff_items_csv: Path) -> list[str]:
    tags: set[str] = set()
    for row in _read_csv(takeoff_items_csv):
        tag = (row.get("tag") or _tag_from_item(row.get("item", ""))).upper().strip()
        if tag and re.match(r"^[A-Z]{1,4}\d{0,2}[A-Z]?$|^EXIT$|^PULL$|^FACP$|^FAAP$|^H/S$", tag):
            tags.add(tag)
    return sorted(tags, key=lambda value: (-len(value), value))


def _outline_schedule_pages(pdf: Path) -> list[int]:
    try:
        reader = PdfReader(str(pdf))
        outline = reader.outline
    except Exception:
        return []

    pages: list[int] = []

    def walk(items: list[object]) -> None:
        for item in items:
            if isinstance(item, list):
                walk(item)
                continue
            title = getattr(item, "title", str(item)).upper()
            if any(word in title for word in SCHEDULE_TITLE_WORDS):
                try:
                    page = reader.get_destination_page_number(item) + 1
                except Exception:
                    continue
                pages.append(page)

    if isinstance(outline, list):
        walk(outline)
    return sorted(set(pages))


def _page_text(pdf: Path, page_number: int) -> str:
    try:
        reader = PdfReader(str(pdf))
        if page_number < 1 or page_number > len(reader.pages):
            return ""
        return reader.pages[page_number - 1].extract_text() or ""
    except Exception:
        return ""


def _candidate_schedule_texts(project_folder: Path, max_pages: int = 160) -> list[tuple[Path, int, str, str]]:
    """Return likely fixture schedule page text as pdf, page, text, reason."""
    candidates: list[tuple[Path, int, str, str]] = []
    pdfs = [candidate.path for candidate in find_pdf_candidates(project_folder, limit=12) if candidate.kind in {"drawings", "specs", "addendum"}]
    seen: set[tuple[str, int]] = set()

    for pdf in pdfs:
        for page in _outline_schedule_pages(pdf):
            key = (str(pdf).lower(), page)
            if key in seen:
                continue
            seen.add(key)
            text = _page_text(pdf, page)
            if text:
                candidates.append((pdf, page, text, "PDF bookmark/outline identified fixture schedule page"))

    if candidates:
        return candidates

    for pdf in pdfs:
        try:
            reader = PdfReader(str(pdf))
        except Exception:
            continue
        for page_number, page in enumerate(reader.pages[:max_pages], 1):
            key = (str(pdf).lower(), page_number)
            if key in seen:
                continue
            try:
                text = page.extract_text() or ""
            except Exception:
                text = ""
            upper = text.upper()
            if any(word in upper for word in SCHEDULE_TITLE_WORDS):
                seen.add(key)
                candidates.append((pdf, page_number, text, "page text contains schedule title"))
    return candidates


def _clean_description(text: str, limit: int = 260) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip(" -|:,")
    cleaned = re.sub(r"^(TAG|DESCRIPTION|MANUFACTURER/SERIES|MODEL)\b", "", cleaned, flags=re.I).strip(" -|:,")
    cleaned = _improve_schedule_readability(cleaned)
    return cleaned[:limit].strip()


def _improve_schedule_readability(text: str) -> str:
    """Make PDF-extracted schedule rows easier to review without pretending to fully parse the table."""
    replacements = {
        "TROFFERLITHONIA": "TROFFER - LITHONIA",
        "DOWNLIGHTGOTHAM": "DOWNLIGHT - GOTHAM",
        "RATEDGOTHAM": "RATED - GOTHAM",
        "LINEARMARK": "LINEAR - MARK",
        "MIRRORELECTRIC": "MIRROR - ELECTRIC",
        "RATEDEVERBRITE": "RATED - EVERBRITE",
        "ARCHITECTURALS": "ARCHITECTURAL - ",
        "WHITERECESSED": "WHITE - RECESSED",
        "WHITESURFACE": "WHITE - SURFACE",
        "CLEARRECESSED": "CLEAR - RECESSED",
        "RECESSEDCEILING": "RECESSED - CEILING",
        "SURFACECEILING": "SURFACE - CEILING",
        "GRIDMRI": "GRID - MRI",
        "GRIDMEDS": "GRID - MEDS",
        "GRIDOFFICES": "GRID - OFFICES",
        "GRIDGENERAL": "GRID - GENERAL",
        "GRIDCORRIDORS": "GRID - CORRIDORS",
        "GYPSUMGENERAL": "GYPSUM - GENERAL",
        "GYPSUMMRI": "GYPSUM - MRI",
        "GYPSUMLOBBY": "GYPSUM - LOBBY",
        "GYPSUMWAITING": "GYPSUM - WAITING",
        "WALLTOILETS": "WALL - TOILETS",
        "WALLRESPITE": "WALL - RESPITE",
        "PENDANTRN": "PENDANT - RN",
        "PENDANTELECTRICAL": "PENDANT - ELECTRICAL",
    }
    cleaned = text
    for before, after in replacements.items():
        cleaned = re.sub(before, after, cleaned, flags=re.I)
    # Add a little breathing room around common electrical schedule values.
    cleaned = re.sub(r"(?<=\d)(?=K,\s*\d{2}CRI)", " ", cleaned, flags=re.I)
    cleaned = re.sub(r"(?<=CRI)(?=\d{3,4})", " ", cleaned, flags=re.I)
    cleaned = re.sub(r"(?<=\d)(?=WHITE\b|CLEAR\b|TBD\b)", " ", cleaned, flags=re.I)
    cleaned = re.sub(r"(?<=\d)(?=RECESSED\b|SURFACE\b|PENDANT\b)", " ", cleaned, flags=re.I)
    cleaned = re.sub(r"(?<=\w)(?=Dim to)", " ", cleaned, flags=re.I)
    cleaned = re.sub(r"(?<=\dW)(?=/F)", "", cleaned, flags=re.I)
    cleaned = re.sub(r"(?<=\d)(?=W/F)", " ", cleaned, flags=re.I)
    cleaned = re.sub(r"(?<=[a-z])(?=[A-Z]{2,}(?:\s|$))", " ", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned.strip()


def _fixture_schedule_section(text: str) -> str:
    upper = text.upper()
    table_header = re.search(r"LIGHTING\s+FIXTURE\s+SCHEDULE\s*TAG\s*DESCRIPTION", upper)
    if table_header:
        start = table_header.start()
    else:
        starts = [upper.rfind(word) for word in SCHEDULE_TITLE_WORDS if upper.rfind(word) >= 0]
        if not starts:
            return text
        start = min(starts)
    section = text[start:]
    section_upper = section.upper()
    note_match = re.search(r"\b(?:SCHEDULE NOTES|LIGHTING FIXTURE SCHEDULE NOTES|FIXTURE SCHEDULE NOTES|FIRE ALARM SCHEDULE NOTES)\b", section_upper)
    if note_match:
        return section[: note_match.start()]
    return section


def _tag_positions(text: str, tags: list[str]) -> list[tuple[int, str]]:
    upper = text.upper()
    raw: list[tuple[int, int, str]] = []
    # Schedule tables extracted from PDFs often glue the tag to the first
    # description word, e.g. A34" LED DOWNLIGHT or A4LED ILLUMINATED MIRROR.
    # Use a left boundary only, then suppress overlaps by preferring longer
    # tags so A1A wins over A1.
    for tag in sorted({tag.upper() for tag in tags}, key=lambda value: (-len(value), value)):
        pattern = re.compile(rf"(?<![A-Z0-9]){re.escape(tag)}")
        for match in pattern.finditer(upper):
            raw.append((match.start(), match.end(), tag))

    kept: list[tuple[int, int, str]] = []
    for start, end, tag in sorted(raw, key=lambda item: (item[0], -(item[1] - item[0]))):
        if any(not (end <= old_start or start >= old_end) for old_start, old_end, _ in kept):
            continue
        kept.append((start, end, tag))

    first_by_tag: dict[str, int] = {}
    for start, _end, tag in kept:
        first_by_tag.setdefault(tag, start)
    return sorted((start, tag) for tag, start in first_by_tag.items())


def _schedule_boundary_tags(text: str, requested_tags: list[str]) -> list[str]:
    found = {match.group(0).upper() for match in SCHEDULE_ROW_TAG.finditer(text.upper())}
    return sorted(found | {tag.upper() for tag in requested_tags}, key=lambda value: (-len(value), value))


def extract_fixture_schedule_entries(project_folder: Path, tags: list[str]) -> list[FixtureScheduleEntry]:
    if not tags:
        return []
    entries_by_tag: dict[str, FixtureScheduleEntry] = {}

    for pdf, page, text, source_reason in _candidate_schedule_texts(project_folder):
        text = _fixture_schedule_section(text)
        requested = {tag.upper() for tag in tags}
        positions = _tag_positions(text, _schedule_boundary_tags(text, tags))
        if not positions:
            continue
        for index, (start, tag) in enumerate(positions):
            if tag not in requested:
                continue
            if tag in entries_by_tag:
                continue
            end = positions[index + 1][0] if index + 1 < len(positions) else min(len(text), start + 500)
            segment = text[start + len(tag) : end]
            description = _clean_description(segment)
            if not description:
                continue
            entries_by_tag[tag] = FixtureScheduleEntry(
                tag=tag,
                description=description,
                source_pdf=pdf,
                page=page,
                confidence=0.72 if "bookmark" in source_reason.lower() else 0.62,
                reason=source_reason,
            )
    return [entries_by_tag[tag] for tag in sorted(entries_by_tag)]


def write_fixture_schedule_outputs(project_folder: Path, takeoff_items_csv: Path, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    tags = tags_from_takeoff_items(takeoff_items_csv)
    entries = extract_fixture_schedule_entries(project_folder, tags)
    entries_csv = out_dir / "fixture_schedule_entries.csv"
    summary_md = out_dir / "fixture_schedule_understanding.md"

    with entries_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["tag", "schedule_description", "schedule_confidence", "schedule_source_pdf", "schedule_source_page", "schedule_reason"])
        for entry in entries:
            writer.writerow([entry.tag, entry.description, entry.confidence, str(entry.source_pdf), entry.page, entry.reason])

    with summary_md.open("w", encoding="utf-8") as handle:
        handle.write("# Schedule understanding\n\n")
        handle.write("This internal step connects detected tags to likely fixture/device schedule descriptions when the project drawings/specs expose searchable text.\n\n")
        handle.write(f"- Takeoff tags checked: {len(tags)}\n")
        handle.write(f"- Schedule entries matched: {len(entries)}\n\n")
        if entries:
            handle.write("## Matched entries\n\n")
            for entry in entries[:40]:
                handle.write(f"- {entry.tag}: {entry.description} (page {entry.page})\n")
        else:
            handle.write("No schedule entries were matched. The estimator should check whether the schedule is scanned, missing, or named differently.\n")

    return summary_md, entries_csv
