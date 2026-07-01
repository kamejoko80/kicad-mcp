"""Schematic page discovery for PDF export.

Author: Henry Dang
Email: phuongminh.dang@gmail.com
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

_SHEET_BLOCK_PATTERN = re.compile(r"\(sheet\b", re.MULTILINE)
_SHEETNAME_PATTERN = re.compile(r'\(property "Sheetname" "([^"]+)"')
_SHEETFILE_PATTERN = re.compile(r'\(property "Sheetfile" "([^"]+)"')
_ROOT_PAGE_PATTERN = re.compile(
    r'\(sheet_instances\s+\(path\s+"/"\s+\(page\s+"(\d+)"\)',
    re.MULTILINE,
)
_INSTANCE_PAGE_PATTERN = re.compile(
    r'\(instances\s+\(project\s+"([^"]+)"[\s\S]*?\(page\s+"(\d+)"\)',
    re.MULTILINE,
)


@dataclass(frozen=True)
class SchematicPage:
    page_number: int
    sheet_name: str
    sheet_file: str
    schematic_path: str

    def to_dict(self) -> dict[str, object]:
        return {
            "page_number": self.page_number,
            "sheet_name": self.sheet_name,
            "sheet_file": self.sheet_file,
            "schematic_path": self.schematic_path,
        }


def list_schematic_pages(entry_schematic: str, project_name: str) -> list[SchematicPage]:
    """List PDF page numbers and sheet names reachable from an entry schematic."""
    entry_schematic = os.path.normpath(entry_schematic)
    project_dir = os.path.dirname(entry_schematic)
    pages: dict[int, SchematicPage] = {}

    def add_page(page_number: int, sheet_name: str, sheet_file: str, schematic_path: str) -> None:
        if page_number in pages:
            return
        pages[page_number] = SchematicPage(
            page_number=page_number,
            sheet_name=sheet_name,
            sheet_file=sheet_file,
            schematic_path=os.path.normpath(schematic_path),
        )

    def walk(schematic_path: str, *, is_entry: bool) -> None:
        try:
            with open(schematic_path, encoding="utf-8") as handle:
                content = handle.read()
        except OSError:
            return

        if is_entry:
            root_match = _ROOT_PAGE_PATTERN.search(content)
            if root_match:
                basename = os.path.basename(schematic_path)
                stem = os.path.splitext(basename)[0]
                add_page(
                    int(root_match.group(1)),
                    stem,
                    basename,
                    schematic_path,
                )

        for block_start in _SHEET_BLOCK_PATTERN.finditer(content):
            block = _extract_balanced_block(content, block_start.start())
            if not block:
                continue
            sheet_name_match = _SHEETNAME_PATTERN.search(block)
            sheet_file_match = _SHEETFILE_PATTERN.search(block)
            if not sheet_name_match or not sheet_file_match:
                continue
            sheet_name = sheet_name_match.group(1).strip()
            sheet_file = sheet_file_match.group(1).strip()
            page_number = _page_number_for_project(block, project_name)
            if page_number is None:
                continue
            child_path = os.path.normpath(os.path.join(project_dir, sheet_file))
            add_page(page_number, sheet_name, sheet_file, child_path)
            if os.path.isfile(child_path):
                walk(child_path, is_entry=False)

    walk(entry_schematic, is_entry=True)
    return [pages[key] for key in sorted(pages)]


def resolve_page_name(pages: list[SchematicPage], page_name: str) -> SchematicPage:
    cleaned = page_name.strip()
    if not cleaned:
        raise ValueError("page_name cannot be empty.")

    normalized = cleaned.casefold()
    if normalized in {"all", "*"}:
        raise ValueError("page_name cannot be 'all'; omit it to export all pages.")

    for page in pages:
        candidates = {
            page.sheet_name.casefold(),
            os.path.splitext(page.sheet_file)[0].casefold(),
            os.path.basename(page.schematic_path).casefold(),
            os.path.splitext(os.path.basename(page.schematic_path))[0].casefold(),
        }
        if normalized in candidates:
            return page

    available = ", ".join(page.sheet_name for page in pages)
    raise ValueError(
        f"Schematic page '{page_name}' was not found. Available sheet names: {available}"
    )


def resolve_schematic_path(
    project_dir: str,
    schematic_path: str,
    root_schematic: str | None,
) -> str:
    if schematic_path.strip():
        candidate = os.path.normpath(schematic_path.strip())
        if not os.path.isabs(candidate):
            candidate = os.path.normpath(os.path.join(project_dir, candidate))
        if not os.path.isfile(candidate):
            raise ValueError(f"Schematic file not found: {candidate}")
        return candidate

    if root_schematic and os.path.isfile(root_schematic):
        return os.path.normpath(root_schematic)

    raise ValueError("No schematic file found to export.")


def default_pdf_output_path(
    project_dir: str,
    project_name: str,
    *,
    page_name: str = "",
    page_number: int | None = None,
) -> str:
    export_dir = os.path.join(project_dir, "mcp_exports", "pdf")
    if page_name.strip():
        safe_page = re.sub(r"[^\w.\-]+", "_", page_name.strip())
        filename = f"{project_name}_{safe_page}.pdf"
    elif page_number is not None:
        filename = f"{project_name}_page{page_number}.pdf"
    else:
        filename = f"{project_name}.pdf"
    return os.path.normpath(os.path.join(export_dir, filename))


def resolve_output_path(
    project_dir: str,
    output_path: str,
    default_path: str,
) -> str:
    if output_path.strip():
        candidate = os.path.normpath(output_path.strip())
        if not os.path.isabs(candidate):
            candidate = os.path.normpath(os.path.join(project_dir, candidate))
        parent = os.path.dirname(candidate)
        if parent:
            os.makedirs(parent, exist_ok=True)
        return candidate

    parent = os.path.dirname(default_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    return default_path


def _page_number_for_project(sheet_block: str, project_name: str) -> int | None:
    for match in _INSTANCE_PAGE_PATTERN.finditer(sheet_block):
        if match.group(1) != project_name:
            continue
        return int(match.group(2))
    return None


def _extract_balanced_block(content: str, start_index: int) -> str:
    depth = 0
    started = False
    for index in range(start_index, len(content)):
        char = content[index]
        if char == "(":
            depth += 1
            started = True
        elif char == ")":
            depth -= 1
            if started and depth == 0:
                return content[start_index : index + 1]
    return ""
