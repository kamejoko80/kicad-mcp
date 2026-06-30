"""DigiKey Product Information API v4 provider.

Docs: https://developer.digikey.com/products/product-information-v4/productsearch

Author: Henry Dang
Email: phuongminh.dang@gmail.com
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from kicad_mcp.library.credentials import CredentialStore, ProviderCredentialStatus, ProviderId
from kicad_mcp.library.models import ComponentRecord, PriceBreak, SearchResult
from kicad_mcp.library.providers.base import ComponentSearchProvider, ProviderNotConfiguredError

PRODUCTION_API_BASE = "https://api.digikey.com"
SANDBOX_API_BASE = "https://sandbox-api.digikey.com"
KEYWORD_SEARCH_OPTIONS = {"None", "Rohs", "InStock", "RohsAndInStock"}
PART_SEARCH_OPTIONS = {"Exact", "BeginsWith", "Contains"}
MAX_RECORDS = 50
MAX_PART_NUMBERS = 10
MAX_PRICING_ENRICHMENTS = 25
DEFAULT_LOCALE_SITE = "US"
DEFAULT_LOCALE_LANGUAGE = "en"
DEFAULT_LOCALE_CURRENCY = "USD"


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _uses_sandbox() -> bool:
    flag = os.environ.get("DIGIKEY_SANDBOX", "").strip().lower()
    return flag in {"1", "true", "yes", "on"}


class DigiKeyProvider(ComponentSearchProvider):
    provider_id = ProviderId.DIGIKEY
    display_name = "DigiKey"

    def __init__(self, credential_store: CredentialStore) -> None:
        super().__init__(credential_store)
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0

    @property
    def api_base(self) -> str:
        return SANDBOX_API_BASE if _uses_sandbox() else PRODUCTION_API_BASE

    def credential_status(self) -> ProviderCredentialStatus:
        return self.credential_store.get_provider_status(ProviderId.DIGIKEY)

    def _require_client_credentials(self) -> tuple[str, str]:
        values, _source = self.credential_store.get_digikey_credentials()
        client_id = values.get("client_id", "").strip()
        client_secret = values.get("client_secret", "").strip()
        access_token = values.get("access_token", "").strip()

        if client_id and client_secret:
            return client_id, client_secret
        if access_token:
            return client_id or "configured-token", client_secret

        raise ProviderNotConfiguredError(
            "DigiKey credentials are not configured. Set DIGIKEY_CLIENT_ID and "
            "DIGIKEY_CLIENT_SECRET, or call set_component_provider_credentials("
            "provider='digikey', client_id='...', client_secret='...')."
        )

    def _locale_headers(self) -> dict[str, str]:
        return {
            "X-DIGIKEY-Locale-Site": os.environ.get(
                "DIGIKEY_LOCALE_SITE",
                DEFAULT_LOCALE_SITE,
            ).strip()
            or DEFAULT_LOCALE_SITE,
            "X-DIGIKEY-Locale-Language": os.environ.get(
                "DIGIKEY_LOCALE_LANGUAGE",
                DEFAULT_LOCALE_LANGUAGE,
            ).strip()
            or DEFAULT_LOCALE_LANGUAGE,
            "X-DIGIKEY-Locale-Currency": os.environ.get(
                "DIGIKEY_LOCALE_CURRENCY",
                DEFAULT_LOCALE_CURRENCY,
            ).strip()
            or DEFAULT_LOCALE_CURRENCY,
        }

    def _fetch_access_token(self, client_id: str, client_secret: str) -> str:
        body = urllib.parse.urlencode(
            {
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "client_credentials",
            }
        ).encode("utf-8")
        url = f"{self.api_base}/v1/oauth2/token"
        request = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"DigiKey OAuth HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"DigiKey OAuth request failed: {exc.reason}") from exc

        token = _clean(payload.get("access_token"))
        if not token:
            raise RuntimeError("DigiKey OAuth response did not include an access_token.")

        expires_in = payload.get("expires_in", 0)
        try:
            lifetime = max(60, int(expires_in) - 30)
        except (TypeError, ValueError):
            lifetime = 3000
        self._access_token = token
        self._token_expires_at = time.time() + lifetime
        return token

    def _get_access_token(self) -> tuple[str, str]:
        values, _source = self.credential_store.get_digikey_credentials()
        client_id = values.get("client_id", "").strip()
        client_secret = values.get("client_secret", "").strip()
        access_token = values.get("access_token", "").strip()

        if not client_id and not client_secret and not access_token:
            raise ProviderNotConfiguredError(
                "DigiKey credentials are not configured. Set DIGIKEY_CLIENT_ID and "
                "DIGIKEY_CLIENT_SECRET, or call set_component_provider_credentials("
                "provider='digikey', client_id='...', client_secret='...')."
            )

        if client_id and client_secret:
            if self._access_token and time.time() < self._token_expires_at:
                return client_id, self._access_token
            return client_id, self._fetch_access_token(client_id, client_secret)

        if access_token:
            return client_id or "configured-token", access_token

        raise ProviderNotConfiguredError(
            "DigiKey client_secret is required unless a pre-issued access_token is provided."
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        client_id, access_token = self._get_access_token()
        url = f"{self.api_base}{path}"
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",
            "X-DIGIKEY-Client-Id": client_id,
            **self._locale_headers(),
        }
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"DigiKey API HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"DigiKey API request failed: {exc.reason}") from exc

        if not raw.strip():
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError("DigiKey API returned invalid JSON.") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError("DigiKey API returned an unexpected payload.")
        return parsed

    @staticmethod
    def _map_search_options(search_options: str) -> list[str]:
        mapping = {
            "None": [],
            "Rohs": ["RoHSCompliant"],
            "InStock": ["InStock"],
            "RohsAndInStock": ["RoHSCompliant", "InStock"],
        }
        return mapping.get(search_options, [])

    @staticmethod
    def _format_price(value: Any, currency: str = "USD") -> str:
        if isinstance(value, (int, float)):
            return f"${value:.4f}".rstrip("0").rstrip(".")
        cleaned = _clean(value)
        if cleaned.startswith("$"):
            return cleaned
        return cleaned or ""

    @staticmethod
    def _status_text(value: Any) -> str:
        if isinstance(value, dict):
            return _clean(value.get("Status", ""))
        return _clean(value)

    @staticmethod
    def _flatten_details_product(payload: dict[str, Any]) -> dict[str, Any]:
        product = payload.get("Product") or payload
        if not isinstance(product, dict):
            return {}

        description = product.get("Description") or {}
        manufacturer = product.get("Manufacturer") or {}
        flattened: dict[str, Any] = {
            "ManufacturerProductNumber": product.get("ManufacturerProductNumber"),
            "ManufacturerName": manufacturer.get("Name") if isinstance(manufacturer, dict) else "",
            "ProductDescription": (
                description.get("ProductDescription") if isinstance(description, dict) else ""
            ),
            "DetailedDescription": (
                description.get("DetailedDescription") if isinstance(description, dict) else ""
            ),
            "UnitPrice": product.get("UnitPrice"),
            "ProductUrl": product.get("ProductUrl"),
            "PrimaryDatasheetUrl": product.get("DatasheetUrl"),
            "PrimaryPhotoUrl": product.get("PhotoUrl"),
            "QuantityAvailable": product.get("QuantityAvailable"),
            "ProductStatus": product.get("ProductStatus"),
            "MinimumOrderQuantity": product.get("MinimumOrderQuantity"),
            "Category": product.get("Category"),
        }

        variations = product.get("ProductVariations") or []
        if variations and isinstance(variations[0], dict):
            variation = variations[0]
            flattened["DigiKeyProductNumber"] = variation.get("DigiKeyProductNumber")
            flattened["StandardPricing"] = variation.get("StandardPricing")
            flattened["PackageType"] = variation.get("PackageType")
            if variation.get("QuantityAvailableforPackageType") is not None:
                flattened["QuantityAvailable"] = variation.get("QuantityAvailableforPackageType")
            if variation.get("MinimumOrderQuantity") is not None:
                flattened["MinimumOrderQuantity"] = variation.get("MinimumOrderQuantity")

        return flattened

    def _fetch_product_details(self, product_number: str) -> dict[str, Any]:
        encoded = urllib.parse.quote(product_number.strip(), safe="")
        payload = self._request("GET", f"/products/v4/search/{encoded}/productdetails")
        return self._flatten_details_product(payload)

    @staticmethod
    def _merge_product(base: dict[str, Any], details: dict[str, Any]) -> dict[str, Any]:
        merged = dict(base)
        for key, value in details.items():
            if value in (None, "", [], {}):
                continue
            if key == "StandardPricing" or not merged.get(key):
                merged[key] = value
        return merged

    def _enrich_products_with_pricing(self, products: list[dict[str, Any]]) -> list[dict[str, Any]]:
        enriched: list[dict[str, Any]] = []
        for product in products[:MAX_PRICING_ENRICHMENTS]:
            part_key = _clean(product.get("ManufacturerProductNumber")) or _clean(
                product.get("DigiKeyProductNumber")
            )
            if not part_key:
                enriched.append(product)
                continue
            try:
                details = self._fetch_product_details(part_key)
                enriched.append(self._merge_product(product, details))
            except RuntimeError:
                enriched.append(product)
        enriched.extend(products[MAX_PRICING_ENRICHMENTS:])
        return enriched

    @staticmethod
    def _normalize_product(product: dict[str, Any]) -> ComponentRecord:
        price_breaks: list[PriceBreak] = []
        for item in product.get("StandardPricing") or []:
            if not isinstance(item, dict):
                continue
            try:
                quantity = int(item.get("BreakQuantity", 0))
            except (TypeError, ValueError):
                quantity = 0
            price_breaks.append(
                PriceBreak(
                    quantity=quantity,
                    price=DigiKeyProvider._format_price(item.get("UnitPrice", "")),
                    currency=DEFAULT_LOCALE_CURRENCY,
                )
            )

        if not price_breaks:
            unit_price = product.get("UnitPrice")
            if unit_price not in (None, "", 0):
                price_breaks.append(
                    PriceBreak(
                        quantity=1,
                        price=DigiKeyProvider._format_price(unit_price),
                        currency=DEFAULT_LOCALE_CURRENCY,
                    )
                )

        category = product.get("Category") or {}
        category_name = _clean(category.get("Name", "")) if isinstance(category, dict) else ""
        package = product.get("PackageType") or {}
        package_name = _clean(package.get("Name", "")) if isinstance(package, dict) else ""

        stock_qty = product.get("QuantityAvailable", "")
        availability = _clean(product.get("StockNote", ""))
        if not availability and stock_qty not in ("", None):
            availability = f"{stock_qty} In Stock"

        description = _clean(product.get("ProductDescription", ""))
        detailed = _clean(product.get("DetailedDescription", ""))
        if detailed and detailed not in description:
            description = f"{description} {detailed}".strip()

        return ComponentRecord(
            provider=ProviderId.DIGIKEY.value,
            distributor_part_number=_clean(product.get("DigiKeyProductNumber", "")),
            manufacturer_part_number=_clean(product.get("ManufacturerProductNumber", "")),
            manufacturer=_clean(product.get("ManufacturerName", "")),
            description=description,
            category=category_name or package_name,
            datasheet_url=_clean(product.get("PrimaryDatasheetUrl", "")),
            product_url=_clean(product.get("ProductUrl", "")),
            image_url=_clean(product.get("PrimaryPhotoUrl", "")),
            availability=availability,
            stock_quantity=_clean(stock_qty),
            lead_time=_clean(product.get("ManufacturerLeadWeeks", "")),
            lifecycle_status=DigiKeyProvider._status_text(product.get("ProductStatus")),
            min_order_qty=_clean(product.get("MinimumOrderQuantity", "")),
            order_multiple="",
            rohs_status=_clean(product.get("RohsStatus", "")),
            price_breaks=price_breaks,
        )

    def _collect_products(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        products: list[dict[str, Any]] = []
        seen: set[str] = set()

        for key in ("ExactMatches", "Products"):
            for item in payload.get(key) or []:
                if not isinstance(item, dict):
                    continue
                dkpn = _clean(item.get("DigiKeyProductNumber", ""))
                marker = dkpn or json.dumps(item, sort_keys=True)
                if marker in seen:
                    continue
                seen.add(marker)
                products.append(item)
        return products

    def _filter_products(
        self,
        products: list[dict[str, Any]],
        *,
        manufacturer: str = "",
        match_mode: str = "Exact",
        part_number: str = "",
    ) -> list[dict[str, Any]]:
        filtered = products
        cleaned_mfr = manufacturer.strip()
        if cleaned_mfr:
            mfr_lower = cleaned_mfr.casefold()
            filtered = [
                product
                for product in filtered
                if mfr_lower in _clean(product.get("ManufacturerName", "")).casefold()
            ]

        cleaned_part = part_number.strip()
        if cleaned_part and match_mode == "Exact":
            part_lower = cleaned_part.casefold()
            exact_matches = [
                product
                for product in filtered
                if _clean(product.get("ManufacturerProductNumber", "")).casefold() == part_lower
                or _clean(product.get("DigiKeyProductNumber", "")).casefold() == part_lower
            ]
            if exact_matches:
                return exact_matches

        if cleaned_part and match_mode == "BeginsWith":
            prefix = cleaned_part.casefold()
            filtered = [
                product
                for product in filtered
                if _clean(product.get("ManufacturerProductNumber", "")).casefold().startswith(prefix)
                or _clean(product.get("DigiKeyProductNumber", "")).casefold().startswith(prefix)
            ]
        elif cleaned_part and match_mode == "Contains":
            needle = cleaned_part.casefold()
            filtered = [
                product
                for product in filtered
                if needle in _clean(product.get("ManufacturerProductNumber", "")).casefold()
                or needle in _clean(product.get("DigiKeyProductNumber", "")).casefold()
                or needle in _clean(product.get("ProductDescription", "")).casefold()
            ]

        return filtered

    def _build_search_body(
        self,
        keywords: str,
        *,
        records: int,
        offset: int,
        search_options: str,
        match_mode: str,
    ) -> dict[str, Any]:
        bounded_records = max(1, min(records, MAX_RECORDS))
        bounded_offset = max(0, offset)
        filter_options: dict[str, Any] = {}
        search_option_values = self._map_search_options(search_options)
        if search_option_values:
            filter_options["SearchOptions"] = search_option_values

        body: dict[str, Any] = {
            "Keywords": keywords,
            "Limit": bounded_records,
            "Offset": bounded_offset,
        }
        if filter_options:
            body["FilterOptionsRequest"] = filter_options
        return body

    def _keyword_search(
        self,
        keywords: str,
        *,
        records: int,
        offset: int,
        search_options: str,
        match_mode: str,
        manufacturer: str = "",
    ) -> SearchResult:
        payload = self._request(
            "POST",
            "/products/v4/search/keyword",
            body=self._build_search_body(
                keywords,
                records=records,
                offset=offset,
                search_options=search_options,
                match_mode=match_mode,
            ),
        )
        products = self._collect_products(payload)
        products = self._filter_products(
            products,
            manufacturer=manufacturer,
            match_mode=match_mode,
            part_number=keywords if match_mode == "Exact" else "",
        )
        products = self._enrich_products_with_pricing(products)
        records_out = [self._normalize_product(product) for product in products]

        total = payload.get("ProductsCount")
        try:
            total_results = int(total)
        except (TypeError, ValueError):
            total_results = len(records_out)

        errors: list[str] = []
        if not records_out:
            errors.append("No matching products found on DigiKey.")

        return SearchResult(
            provider=self.provider_id.value,
            query=keywords,
            search_type="keyword",
            total_results=total_results,
            records=records_out,
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

        try:
            return self._keyword_search(
                cleaned_keyword,
                records=records,
                offset=starting_record,
                search_options=search_options,
                match_mode="Contains",
            )
        except (ProviderNotConfiguredError, RuntimeError) as exc:
            return SearchResult(
                provider=self.provider_id.value,
                query=cleaned_keyword,
                search_type="keyword",
                total_results=0,
                errors=[str(exc)],
            )

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
                errors=[f"DigiKey accepts at most {MAX_PART_NUMBERS} part numbers per request."],
            )

        all_records: list[ComponentRecord] = []
        errors: list[str] = []
        for item in part_numbers:
            try:
                result = self._keyword_search(
                    item,
                    records=MAX_RECORDS,
                    offset=0,
                    search_options="None",
                    match_mode=match_mode,
                    manufacturer=manufacturer,
                )
            except (ProviderNotConfiguredError, RuntimeError) as exc:
                errors.append(f"{item}: {exc}")
                continue
            all_records.extend(result.records)
            errors.extend(
                f"{item}: {message}"
                for message in result.errors
                if message != "No matching products found on DigiKey."
            )

        query = cleaned_part
        if manufacturer.strip():
            query = f"{cleaned_part} ({manufacturer.strip()})"

        if not all_records and not errors:
            errors.append("No matching products found on DigiKey.")

        return SearchResult(
            provider=self.provider_id.value,
            query=query,
            search_type="part_number",
            total_results=len(all_records),
            records=all_records,
            errors=errors,
        )
