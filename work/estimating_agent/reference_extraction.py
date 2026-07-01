from __future__ import annotations

import csv
import re
import zipfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

from pypdf import PdfReader

from .livecount_tpx import parse_blocks, parse_fields, read_text


REFERENCE_DOC_WORDS = ("estimate", "proposal", "quote", "summary", "scope", "takeoff")
REFERENCE_HEADINGS = ("DEMOLITION", "POWER", "FIXTURES", "TELE/DATA", "FIRE ALARM", "QUALIFICATIONS", "EXCLUSIONS")
REFERENCE_LINE = re.compile(
    r"\b(?P<qty>\d{1,5})\s+(?:ea\.?\s+|each\s+)?(?P<desc>[^.\n\r]{0,140}?(?:fixture|2x4\s+led|receptacle|tele/data|data\s+location|disconnect|fire\s+alarm)[^.\n\r]{0,120})",
    re.IGNORECASE,
)
PAREN_REFERENCE_LINE = re.compile(
    r"(?P<prefix>[^.\n\r]{0,120})\((?P<qty>\d{1,5})\)\s*(?P<desc>[^.\n\r]{0,140}?(?:fixture|2x4\s+led|receptacle|tele/data|data\s+location|disconnect|fire\s+alarm)[^.\n\r]{0,120})",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ReferenceQuantity:
    source_type: str
    category: str
    description: str
    quantity: float
    unit: str
    source_file: Path
    evidence: str


def _category_for_text(text: str) -> str:
    lower = text.lower()
    if any(word in lower for word in ("tele/data", "data location", "data locations", "telecom")):
        return "tele_data"
    if "receptacle" in lower:
        return "receptacle"
    if any(word in lower for word in ("fixture", "2x4 led", "luminaire", "light")):
        return "light_fixture"
    if "j-hook" in lower or "j hook" in lower:
        return "j_hook"
    if any(word in lower for word in ("conduit", "emt")):
        return "conduit"
    if "fire alarm" in lower:
        return "fire_alarm_device"
    return "other_reference_item"


def _pdf_text(path: Path, max_pages: int = 20) -> str:
    try:
        reader = PdfReader(str(path))
    except Exception:
        return ""
    parts: list[str] = []
    for page in reader.pages[:max_pages]:
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            continue
    return "\n".join(parts)


def _docx_text(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            xml = archive.read("word/document.xml")
    except Exception:
        return ""
    try:
        root = ElementTree.fromstring(xml)
    except Exception:
        return ""
    texts = []
    for node in root.iter():
        if node.tag.endswith("}t") and node.text:
            texts.append(node.text)
    return " ".join(texts)


def _looks_like_reference_doc(path: Path, text: str) -> bool:
    hay = f"{path.name} {text[:3000]}".lower()
    return any(word in hay for word in REFERENCE_DOC_WORDS) and any(heading.lower() in hay for heading in REFERENCE_HEADINGS)


def _extract_reference_quantities_from_text(path: Path, text: str) -> list[ReferenceQuantity]:
    rows: list[ReferenceQuantity] = []
    seen: set[tuple[str, str, float]] = set()
    matches: list[tuple[float, str, str]] = []
    for match in PAREN_REFERENCE_LINE.finditer(text):
        desc = f"{match.group('prefix')} {match.group('desc')}"
        matches.append((float(match.group("qty")), desc, match.group(0)))
    for match in REFERENCE_LINE.finditer(text):
        evidence = match.group(0).strip()
        if re.search(r"\bBid#\s+20\d{2}\b", evidence, re.IGNORECASE):
            continue
        matches.append((float(match.group("qty")), match.group("desc"), evidence))
    matches.sort(key=lambda item: ("bid#" in item[2].lower(), len(item[2])))
    for qty, desc_text, evidence in matches:
        desc = re.sub(r"\s+", " ", desc_text).strip(" -:\t)")
        desc = re.sub(r"^.*?\b(?:Demolition|Power|Fixtures|Tele/Data|Fire Alarm)\s*:\s*", "", desc, flags=re.IGNORECASE)
        if qty >= 1900 and re.search(r"\b(?:bid#|project|job)\b", evidence, re.IGNORECASE):
            continue
        category = _category_for_text(desc)
        if category == "other_reference_item":
            continue
        dedupe_key = (category, path.name.lower(), qty)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        rows.append(
            ReferenceQuantity(
                source_type="previous_estimate_reference",
                category=category,
                description=desc,
                quantity=qty,
                unit="each",
                source_file=path,
                evidence=match.group(0).strip(),
            )
        )
    return rows


def extract_previous_estimate_references(project_folder: Path, out_dir: Path) -> tuple[Path, Path, list[ReferenceQuantity]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    source_files: list[Path]
    if project_folder.is_file():
        source_files = [project_folder]
    else:
        source_files = [path for path in project_folder.rglob("*") if path.is_file() and path.suffix.lower() in {".pdf", ".docx"}]
    rows: list[ReferenceQuantity] = []
    for path in source_files:
        text = _pdf_text(path) if path.suffix.lower() == ".pdf" else _docx_text(path)
        if not text or not _looks_like_reference_doc(path, text):
            continue
        rows.extend(_extract_reference_quantities_from_text(path, text))
    return _write_reference_outputs(out_dir, "reference_scope", rows)


def _tpx_category(layer: str, description: str) -> str:
    hay = f"{layer} {description}".lower()
    if any(word in hay for word in ("data", "tele", "voice")):
        return "tele_data"
    if "receptacle" in hay or "device" in hay:
        return "receptacle"
    if "fixture" in hay or "light" in hay or layer.upper() == "FIXTURES":
        return "light_fixture"
    if "j-hook" in hay or "j hook" in hay:
        return "j_hook"
    if "conduit" in hay or "emt" in hay:
        return "conduit"
    return "other_livecount_item"


def extract_tpx_references(project_folder: Path, out_dir: Path) -> tuple[Path, Path, list[ReferenceQuantity]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    tpx_files = [project_folder] if project_folder.is_file() and project_folder.suffix.lower() == ".tpx" else []
    if project_folder.is_dir():
        tpx_files.extend(path for path in project_folder.rglob("*.tpx") if path.is_file())
    rows: list[ReferenceQuantity] = []
    for path in tpx_files:
        try:
            text = read_text(path)
        except Exception:
            continue
        counts: Counter[tuple[str, str, int]] = Counter()
        lengths: Counter[tuple[str, str, int]] = Counter()
        for block in parse_blocks(text, "Doxel"):
            fields = parse_fields(block)
            page_text = fields.get("Page", ["0"])[0]
            try:
                page = int(page_text)
            except ValueError:
                page = 0
            layer = fields.get("Layer", [""])[0]
            desc = fields.get("Desc", [""])[0] or "(blank description)"
            category = _tpx_category(layer, desc)
            point_count = 0
            for item in fields.get("Item", []):
                values = [value for value in item.split(",") if value.strip()]
                point_count += len(values) // 2
            if point_count:
                counts[(category, desc, page)] += point_count
            for key, values in fields.items():
                if "length" not in key.lower():
                    continue
                for value in values:
                    try:
                        lengths[(category, desc, page)] += int(float(value))
                    except ValueError:
                        pass
        for (category, desc, page), qty in counts.items():
            rows.append(
                ReferenceQuantity(
                    source_type="livecount_tpx_reference",
                    category=category,
                    description=desc,
                    quantity=float(qty),
                    unit="point_count",
                    source_file=path,
                    evidence=f"TPX page {page}; counted Item coordinate pairs",
                )
            )
        for (category, desc, page), qty in lengths.items():
            rows.append(
                ReferenceQuantity(
                    source_type="livecount_tpx_reference",
                    category=category if category != "other_livecount_item" else "conduit",
                    description=desc,
                    quantity=float(qty),
                    unit="length",
                    source_file=path,
                    evidence=f"TPX page {page}; length-like field total",
                )
            )
    return _write_reference_outputs(out_dir, "livecount_reference", rows)


def _write_reference_outputs(out_dir: Path, stem: str, rows: list[ReferenceQuantity]) -> tuple[Path, Path, list[ReferenceQuantity]]:
    csv_path = out_dir / f"{stem}.csv"
    md_path = out_dir / f"{stem}.md"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["source_type", "category", "description", "quantity", "unit", "source_file", "evidence"])
        for row in rows:
            writer.writerow([row.source_type, row.category, row.description, row.quantity, row.unit, str(row.source_file), row.evidence])
    totals: Counter[str] = Counter()
    for row in rows:
        totals[row.category] += row.quantity
    with md_path.open("w", encoding="utf-8") as handle:
        handle.write(f"# {stem.replace('_', ' ').title()}\n\n")
        handle.write("These quantities came from reference files, not AI drawing detection.\n\n")
        if totals:
            handle.write("## Totals by category\n\n")
            for category, qty in sorted(totals.items()):
                handle.write(f"- {category}: {qty:g}\n")
            handle.write("\n")
        else:
            handle.write("No reference quantities were extracted.\n\n")
        handle.write("## Extracted rows\n\n")
        for row in rows[:100]:
            handle.write(f"- {row.category}: {row.quantity:g} {row.unit} - {row.description} (`{row.source_file.name}`)\n")
    return csv_path, md_path, rows
