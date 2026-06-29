"""Mouser Search API provider.

Docs: https://api.mouser.com/api/docs/ui/index

Author: Henry Dang
Email: phuongminh.dang@gmail.com
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from kicad_mcp.library.credentials import CredentialStore, ProviderCredentialStatus, ProviderId
from kicad_mcp.library.models import ComponentRecord, PriceBreak, SearchResult
from kicad_mcp.library.providers.base import ComponentSearchProvider, ProviderNotConfiguredError

MOUSER_API_BASE = "https://api.mouser.com/api/v2"
KEYWORD_SEARCH_OPTIONS = {"None", "Rohs", "InStock", "RohsAndInStock"}
PART_SEARCH_OPTIONS = {"Exact", "BeginsWith", "Contains"}
PART_NUMBER_SEARCH_OPTIONS = {"None", "Exact"}
MAX_RECORDS = 50
MAX_PART_NUMBERS = 10


class MouserProvider(ComponentSearchProvider):
    provider_id = ProviderId.MOUSER
    display_name = "Mouser"

    def __init__(self, credential_store: CredentialStore) -> None:
        super().__init__(credential_store)

    def credential_status(self) -> ProviderCredentialStatus:
        return self.credential_store.get_provider_status(ProviderId.MOUSER)

    def _require_api_key(self) -> str:
        api_key, _source = self.credential_store.get_mouser_api_key()
        if not api_key:
            raise ProviderNotConfiguredError(
                "Mouser API key is not configured. Set MOUSER_API_KEY or call "
                "set_component_provider_credentials(provider='mouser', api_key='...')."
            )
        return api_key

    def _post(self, endpoint: str, body: dict[str, Any]) -> dict[str, Any]:
        api_key = self._require_api_key()
        url = f"{MOUSER_API_BASE}/{endpoint.lstrip('/')}?apiKey={api_key}"
        payload = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Mouser API HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Mouser API request failed: {exc.reason}") from exc

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Mouser API returned invalid JSON.") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError("Mouser API returned an unexpected payload.")
        return parsed

    @staticmethod
    def _extract_errors(payload: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        for item in payload.get("Errors") or []:
            if isinstance(item, dict):
                message = item.get("Message") or item.get("ResourceKey") or str(item)
                code = item.get("Code")
                if code:
                    errors.append(f"{code}: {message}")
                else:
                    errors.append(str(message))
            else:
                errors.append(str(item))
        return errors

    @staticmethod
    def _normalize_part(part: dict[str, Any]) -> ComponentRecord:
        price_breaks: list[PriceBreak] = []
        for item in part.get("PriceBreaks") or []:
            if not isinstance(item, dict):
                continue
            quantity = item.get("Quantity")
            try:
                quantity_int = int(quantity)
            except (TypeError, ValueError):
                quantity_int = 0
            price_breaks.append(
                PriceBreak(
                    quantity=quantity_int,
                    price=str(item.get("Price", "")),
                    currency=str(item.get("Currency", "USD")),
                )
            )

        return ComponentRecord(
            provider=ProviderId.MOUSER.value,
            distributor_part_number=str(part.get("MouserPartNumber", "")),
            manufacturer_part_number=str(part.get("ManufacturerPartNumber", "")),
            manufacturer=str(part.get("Manufacturer", "")),
            description=str(part.get("Description", "")),
            category=str(part.get("Category", "")),
            datasheet_url=str(part.get("DataSheetUrl", "")),
            product_url=str(part.get("ProductDetailUrl", "")),
            image_url=str(part.get("ImagePath", "")),
            availability=str(part.get("Availability", "")),
            stock_quantity=str(part.get("AvailabilityInStock", "")),
            lead_time=str(part.get("LeadTime", "")),
            lifecycle_status=str(part.get("LifecycleStatus", "")),
            min_order_qty=str(part.get("Min", "")),
            order_multiple=str(part.get("Mult", "")),
            rohs_status=str(part.get("RohsStatus") or part.get("ROHSStatus", "")),
            price_breaks=price_breaks,
        )

    def _build_result(
        self,
        *,
        query: str,
        search_type: str,
        payload: dict[str, Any],
    ) -> SearchResult:
        errors = self._extract_errors(payload)
        search_results = payload.get("SearchResults") or {}
        parts = search_results.get("Parts") or []
        records = [
            self._normalize_part(part)
            for part in parts
            if isinstance(part, dict)
        ]
        total = search_results.get("NumberOfResult")
        try:
            total_results = int(total)
        except (TypeError, ValueError):
            total_results = len(records)

        return SearchResult(
            provider=self.provider_id.value,
            query=query,
            search_type=search_type,
            total_results=total_results,
            records=records,
            errors=errors,
        )

    def search_by_keyword(
        self,
        keyword: str,
        *,
        records: int = 10,
        starting_record: int = 0,
        search_options: str = "None",
    ) -> SearchResult:
        cleaned_keyword = keyword.strip()
        if not cleaned_keyword:
            return SearchResult(
                provider=self.provider_id.value,
                query=keyword,
                search_type="keyword",
                total_results=0,
                errors=["Keyword cannot be empty."],
            )

        if search_options not in KEYWORD_SEARCH_OPTIONS:
            return SearchResult(
                provider=self.provider_id.value,
                query=cleaned_keyword,
                search_type="keyword",
                total_results=0,
                errors=[f"Invalid search_options. Use one of: {sorted(KEYWORD_SEARCH_OPTIONS)}"],
            )

        bounded_records = max(1, min(records, MAX_RECORDS))
        page_number = max(1, (max(0, starting_record) // bounded_records) + 1)
        request_body: dict[str, Any] = {
            "keyword": cleaned_keyword,
            "records": bounded_records,
            "pageNumber": page_number,
            "searchOptions": search_options,
        }
        body = {"SearchByKeywordMfrNameRequest": request_body}
        payload = self._post("search/keywordandmanufacturer", body)
        return self._build_result(query=cleaned_keyword, search_type="keyword", payload=payload)

    def search_by_part_number(
        self,
        part_number: str,
        *,
        manufacturer: str = "",
        match_mode: str = "Exact",
    ) -> SearchResult:
        cleaned_part = part_number.strip()
        if not cleaned_part:
            return SearchResult(
                provider=self.provider_id.value,
                query=part_number,
                search_type="part_number",
                total_results=0,
                errors=["Part number cannot be empty."],
            )

        if match_mode not in PART_SEARCH_OPTIONS:
            return SearchResult(
                provider=self.provider_id.value,
                query=cleaned_part,
                search_type="part_number",
                total_results=0,
                errors=[f"Invalid match_mode. Use one of: {sorted(PART_SEARCH_OPTIONS)}"],
            )

        part_numbers = [item.strip() for item in cleaned_part.split("|") if item.strip()]
        if not part_numbers:
            return SearchResult(
                provider=self.provider_id.value,
                query=cleaned_part,
                search_type="part_number",
                total_results=0,
                errors=["Part number cannot be empty."],
            )
        if len(part_numbers) > MAX_PART_NUMBERS:
            return SearchResult(
                provider=self.provider_id.value,
                query=cleaned_part,
                search_type="part_number",
                total_results=0,
                errors=[f"Mouser accepts at most {MAX_PART_NUMBERS} part numbers per request."],
            )

        joined_parts = "|".join(part_numbers)
        cleaned_manufacturer = manufacturer.strip()
        if match_mode == "Exact":
            part_search_options = "Exact"
        else:
            part_search_options = "None"

        if cleaned_manufacturer and match_mode == "Exact":
            endpoint = "search/partnumberandmanufacturer"
            body = {
                "SearchByPartMfrNameRequest": {
                    "mouserPartNumber": joined_parts,
                    "manufacturerName": cleaned_manufacturer,
                    "partSearchOptions": part_search_options,
                }
            }
            query = f"{joined_parts} ({cleaned_manufacturer})"
            payload = self._post(endpoint, body)
            return self._build_result(query=query, search_type="part_number", payload=payload)

        keyword = joined_parts if match_mode == "Exact" else cleaned_part
        request_body: dict[str, Any] = {
            "keyword": keyword,
            "records": MAX_RECORDS,
            "pageNumber": 1,
            "searchOptions": "None",
        }
        if cleaned_manufacturer:
            request_body["manufacturerName"] = cleaned_manufacturer
        body = {"SearchByKeywordMfrNameRequest": request_body}
        query = f"{keyword} ({cleaned_manufacturer})" if cleaned_manufacturer else keyword
        payload = self._post("search/keywordandmanufacturer", body)
        return self._build_result(query=query, search_type="part_number", payload=payload)
