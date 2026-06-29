from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path


BLOCK_START = re.compile(r"^\s*([A-Za-z][A-Za-z0-9_ ]*) \{$")
FIELD_QUOTED = re.compile(r'^\s*([A-Za-z][A-Za-z0-9_]*)\("(.*)"\)$')
FIELD_RAW = re.compile(r"^\s*([A-Za-z][A-Za-z0-9_]*)\(([^()]*)\)$")


@dataclass(frozen=True)
class TpxDocument:
    page: int
    document_id: str
    description: str
    drawing_number: str
    relative_path: str


@dataclass(frozen=True)
class TpxPoint:
    page: int
    layer: str
    description: str
    x: float
    y: float


def parse_blocks(text: str, kind: str):
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        match = BLOCK_START.match(lines[index])
        if not match or match.group(1) != kind:
            index += 1
            continue
        depth = 1
        block = [lines[index]]
        index += 1
        while index < len(lines) and depth:
            line = lines[index]
            block.append(line)
            if line.strip().endswith("{"):
                depth += 1
            elif line.strip() == "}":
                depth -= 1
            index += 1
        yield block


def parse_fields(block: list[str]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for line in block:
        match = FIELD_QUOTED.match(line) or FIELD_RAW.match(line)
        if match:
            result.setdefault(match.group(1), []).append(match.group(2))
    return result


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def documents_from_text(text: str) -> list[TpxDocument]:
    documents: list[TpxDocument] = []
    for index, block in enumerate(parse_blocks(text, "Document")):
        fields = parse_fields(block)
        page_text = fields.get("ID", [str(index)])[0]
        try:
            page = int(page_text)
        except ValueError:
            page = index
        documents.append(
            TpxDocument(
                page=page,
                document_id=fields.get("ID", [""])[0],
                description=fields.get("Desc", [""])[0],
                drawing_number=fields.get("DwgNum", [""])[0],
                relative_path=fields.get("RelPath", [""])[0],
            )
        )
    return documents


def points_from_text(text: str, layer: str | None = None) -> list[TpxPoint]:
    points: list[TpxPoint] = []
    for block in parse_blocks(text, "Doxel"):
        fields = parse_fields(block)
        page_text = fields.get("Page", ["0"])[0]
        try:
            page = int(page_text)
        except ValueError:
            continue
        point_layer = fields.get("Layer", [""])[0]
        if layer is not None and point_layer != layer:
            continue
        description = fields.get("Desc", [""])[0]
        for item in fields.get("Item", []):
            values = [float(value) for value in item.split(",") if value != ""]
            for x, y in zip(values[::2], values[1::2]):
                points.append(
                    TpxPoint(
                        page=page,
                        layer=point_layer,
                        description=description,
                        x=x,
                        y=y,
                    )
                )
    return points


def fixture_counts_by_page(points: list[TpxPoint]) -> dict[int, Counter]:
    counts: dict[int, Counter] = defaultdict(Counter)
    for point in points:
        if point.layer == "FIXTURES":
            counts[point.page][point.description] += 1
    return dict(counts)


def read_tpx(path: Path) -> tuple[list[TpxDocument], list[TpxPoint]]:
    text = read_text(path)
    return documents_from_text(text), points_from_text(text)
