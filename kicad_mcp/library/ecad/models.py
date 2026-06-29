"""ECAD library provider models.

Author: Henry Dang
Email: phuongminh.dang@gmail.com
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class EcadPartMatch:
    provider: str
    part_id: str
    part_number: str
    manufacturer: str
    description: str = ""
    has_symbol: bool = False
    has_footprint: bool = False
    has_3d_model: bool = False
    downloadable: bool = False
    part_view_url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EcadSearchResult:
    provider: str
    query: str
    total_results: int
    matches: list[EcadPartMatch] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["downloadable_count"] = sum(
            1 for match in self.matches if match.downloadable
        )
        return payload


@dataclass
class EcadDownloadResult:
    provider: str
    part_id: str
    part_number: str
    manufacturer: str
    zip_path: str
    output_dir: str
    extracted_files: list[str] = field(default_factory=list)
    library_name: str = ""
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
