"""Shared component search data models.

Author: Henry Dang
Email: phuongminh.dang@gmail.com
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class PriceBreak:
    quantity: int
    price: str
    currency: str = "USD"


@dataclass
class ComponentRecord:
    """Normalized component record across distributor providers."""

    provider: str
    distributor_part_number: str
    manufacturer_part_number: str
    manufacturer: str
    description: str
    category: str = ""
    datasheet_url: str = ""
    product_url: str = ""
    image_url: str = ""
    availability: str = ""
    stock_quantity: str = ""
    lead_time: str = ""
    lifecycle_status: str = ""
    min_order_qty: str = ""
    order_multiple: str = ""
    rohs_status: str = ""
    price_breaks: list[PriceBreak] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["price_breaks"] = [asdict(item) for item in self.price_breaks]
        return payload


@dataclass
class SearchResult:
    provider: str
    query: str
    search_type: str
    total_results: int
    records: list[ComponentRecord] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "query": self.query,
            "search_type": self.search_type,
            "total_results": self.total_results,
            "result_count": len(self.records),
            "records": [record.to_dict() for record in self.records],
            "errors": self.errors,
            "warnings": self.warnings,
        }
