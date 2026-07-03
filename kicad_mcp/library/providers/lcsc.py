"""LCSC component search via unofficial wmsc.lcsc.com endpoints.

Uses LCSC's own backend (product detail + encrypted global search v3).
No official API key is required.

Author: Henry Dang
Email: phuongminh.dang@gmail.com
"""

from __future__ import annotations

import base64
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from gmssl.sm2 import CryptSM2

from kicad_mcp.library.credentials import CredentialStore, ProviderCredentialStatus, ProviderId
from kicad_mcp.library.models import ComponentRecord, PriceBreak, SearchResult
from kicad_mcp.library.providers.base import ComponentSearchProvider

LCSC_HOME_URL = "https://www.lcsc.com/"
WMSC_API_BASE = "https://wmsc.lcsc.com/ftps/wm/"
WMSC_CURRENCY_URL = "https://wmsc.lcsc.com/wmsc/home/currency?currencyCode=USD"
WMSC_SEARCH_URL = f"{WMSC_API_BASE}search/v3/global"
WMSC_PRODUCT_DETAIL_URL = f"{WMSC_API_BASE}product/detail"

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
}

KEYWORD_SEARCH_OPTIONS = {"None", "Rohs", "InStock", "RohsAndInStock"}
PART_SEARCH_OPTIONS = {"Exact", "BeginsWith", "Contains"}
MAX_RECORDS = 50
MAX_PART_NUMBERS = 10
LCSC_CODE_PATTERN = re.compile(r"^C?\d+$", re.IGNORECASE)
ENCRYPT_KEY_PATTERN = re.compile(r'encryptPublicHexKey:"([a-f0-9]+)"')


def _format_lcsc_code(lcsc_id: Any) -> str:
    if lcsc_id in (None, ""):
        return ""
    text = str(lcsc_id).strip()
    if text.upper().startswith("C") and text[1:].isdigit():
        return text.upper()
    try:
        return f"C{int(text)}"
    except (TypeError, ValueError):
        return text


def _is_lcsc_code(text: str) -> bool:
    return bool(LCSC_CODE_PATTERN.match(text.strip()))


class _LCSCSession:
    def __init__(self) -> None:
        self._sm2: CryptSM2 | None = None

    def _ensure_crypto(self) -> CryptSM2:
        if self._sm2 is not None:
            return self._sm2

        currency_request = urllib.request.Request(
            WMSC_CURRENCY_URL,
            headers=REQUEST_HEADERS,
            method="GET",
        )
        with urllib.request.urlopen(currency_request, timeout=30):
            pass

        home_request = urllib.request.Request(LCSC_HOME_URL, headers=REQUEST_HEADERS, method="GET")
        with urllib.request.urlopen(home_request, timeout=30) as response:
            homepage = response.read().decode("utf-8", errors="replace")

        match = ENCRYPT_KEY_PATTERN.search(homepage)
        if not match:
            raise RuntimeError(
                "LCSC API setup failed: encryptPublicHexKey not found on lcsc.com homepage."
            )

        self._sm2 = CryptSM2(None, match.group(1), mode=1)
        return self._sm2

    @staticmethod
    def _read_json(response: Any) -> dict[str, Any]:
        raw = response.read().decode("utf-8")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError("LCSC API returned invalid JSON.") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError("LCSC API returned an unexpected payload.")
        return parsed

    @classmethod
    def _api_result(cls, payload: dict[str, Any]) -> dict[str, Any] | None:
        code = payload.get("code")
        if code != 200:
            message = payload.get("msg") or "Unknown LCSC API error."
            raise RuntimeError(f"LCSC API error {code}: {message}")
        result = payload.get("result")
        return result if isinstance(result, dict) else None

    def _request(
        self,
        url: str,
        *,
        method: str = "GET",
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        headers = dict(REQUEST_HEADERS)
        data: bytes | None = None
        if json_body is not None:
            headers["Content-Type"] = "application/json"
            headers["Origin"] = LCSC_HOME_URL.rstrip("/")
            headers["Referer"] = LCSC_HOME_URL
            data = json.dumps(json_body).encode("utf-8")

        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = self._read_json(response)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"LCSC API HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"LCSC API request failed: {exc.reason}") from exc

        return self._api_result(payload)

    def product_detail(self, product_code: str) -> dict[str, Any] | None:
        code = _format_lcsc_code(product_code)
        if not code:
            return None
        query = urllib.parse.urlencode({"productCode": code})
        return self._request(f"{WMSC_PRODUCT_DETAIL_URL}?{query}")

    def search(self, keyword: str) -> dict[str, Any] | None:
        cleaned = keyword.strip()
        if not cleaned:
            return None

        sm2 = self._ensure_crypto()
        encrypted = sm2.encrypt(base64.b64encode(cleaned.encode("utf-8")))
        body = {
            "keyword": f"{{secret}}04{encrypted.hex()}",
            "currentPage": 1,
            "pageSize": MAX_RECORDS,
        }
        return self._request(WMSC_SEARCH_URL, method="POST", json_body=body)


class LCSCProvider(ComponentSearchProvider):
    provider_id = ProviderId.LCSC
    display_name = "LCSC"

    def __init__(self, credential_store: CredentialStore) -> None:
        super().__init__(credential_store)
        self._session = _LCSCSession()

    def credential_status(self) -> ProviderCredentialStatus:
        return self.credential_store.get_provider_status(ProviderId.LCSC)

    @staticmethod
    def _description(product: dict[str, Any]) -> str:
        for key in ("productIntroEn", "productDescEn", "productNameEn", "productKeyAttributes"):
            value = product.get(key)
            if value:
                return str(value).strip()
        return ""

    @staticmethod
    def _datasheet_url(product: dict[str, Any]) -> str:
        pdf_url = product.get("pdfUrl")
        if isinstance(pdf_url, str) and pdf_url.strip():
            return pdf_url.strip()
        pdf_link = product.get("pdfLinkUrl")
        if isinstance(pdf_link, str) and pdf_link.strip():
            return pdf_link.strip()
        return ""

    @staticmethod
    def _image_url(product: dict[str, Any]) -> str:
        for key in ("productImageUrlBig", "productImageUrl"):
            value = product.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        images = product.get("productImages")
        if isinstance(images, list) and images:
            first = images[0]
            if isinstance(first, str) and first.strip():
                return first.strip()
        return ""

    @staticmethod
    def _stock_quantity(product: dict[str, Any]) -> str:
        stock = product.get("stockNumber")
        if stock is not None and stock != "":
            return str(stock)
        domestic = product.get("domesticStockVO")
        if isinstance(domestic, dict) and domestic.get("total") is not None:
            return str(domestic["total"])
        return ""

    @staticmethod
    def _availability_label(stock_quantity: str) -> str:
        if not stock_quantity:
            return ""
        try:
            quantity = int(float(stock_quantity))
        except (TypeError, ValueError):
            return stock_quantity
        if quantity > 0:
            return f"{quantity} In Stock"
        return "Out of Stock"

    @staticmethod
    def _rohs_status(product: dict[str, Any]) -> str:
        rohs = product.get("isEnvironment")
        if rohs is True:
            return "RoHS Compliant"
        if rohs is False:
            return "Not RoHS Compliant"
        return ""

    @staticmethod
    def _lifecycle_status(product: dict[str, Any]) -> str:
        basic = product.get("isBasic")
        if basic is True:
            return "JLCPCB Basic Part"
        if basic is False:
            return "Extended Part"
        return ""

    @staticmethod
    def _price_breaks(product: dict[str, Any]) -> list[PriceBreak]:
        price_breaks: list[PriceBreak] = []
        raw_prices = product.get("productPriceList")
        if not isinstance(raw_prices, list):
            return price_breaks

        for entry in raw_prices:
            if not isinstance(entry, dict):
                continue
            ladder = entry.get("ladder", 1)
            try:
                quantity = int(ladder)
            except (TypeError, ValueError):
                quantity = 1

            currency_symbol = str(entry.get("currencySymbol") or "$").strip()
            currency = "USD" if currency_symbol == "$" else currency_symbol

            price_value = entry.get("currencyPrice", entry.get("usdPrice", entry.get("productPrice")))
            if isinstance(price_value, (int, float)):
                price_text = f"{currency_symbol}{price_value}"
            else:
                price_text = str(price_value or "")

            if not price_text:
                continue

            price_breaks.append(
                PriceBreak(quantity=quantity, price=price_text, currency=currency)
            )

        return price_breaks

    @classmethod
    def _normalize_product(cls, product: dict[str, Any]) -> ComponentRecord:
        lcsc_code = _format_lcsc_code(product.get("productCode"))
        stock_quantity = cls._stock_quantity(product)

        return ComponentRecord(
            provider=ProviderId.LCSC.value,
            distributor_part_number=lcsc_code,
            manufacturer_part_number=str(product.get("productModel") or "").strip(),
            manufacturer=str(product.get("brandNameEn") or "").strip(),
            description=cls._description(product),
            category=str(product.get("encapStandard") or "").strip(),
            datasheet_url=cls._datasheet_url(product),
            product_url=f"https://www.lcsc.com/product-detail/{lcsc_code}.html"
            if lcsc_code
            else "",
            image_url=cls._image_url(product),
            availability=cls._availability_label(stock_quantity),
            stock_quantity=stock_quantity,
            lifecycle_status=cls._lifecycle_status(product),
            min_order_qty=str(product.get("minBuyNumber") or ""),
            order_multiple=str(product.get("split") or ""),
            rohs_status=cls._rohs_status(product),
            price_breaks=cls._price_breaks(product),
        )

    @staticmethod
    def _stock_value(stock_quantity: str) -> int:
        try:
            return int(float(stock_quantity))
        except (TypeError, ValueError):
            return 0

    @classmethod
    def _matches_part_query(
        cls,
        product: dict[str, Any],
        query: str,
        *,
        manufacturer: str,
        match_mode: str,
    ) -> bool:
        lcsc_code = _format_lcsc_code(product.get("productCode"))
        candidates = [
            str(product.get("productModel") or "").strip(),
            lcsc_code,
            lcsc_code.lstrip("C"),
        ]
        normalized_query = query.strip()
        normalized_manufacturer = manufacturer.strip().lower()

        if normalized_manufacturer:
            item_manufacturer = str(product.get("brandNameEn") or "").lower()
            if normalized_manufacturer not in item_manufacturer:
                return False

        if match_mode == "Exact":
            lowered = normalized_query.lower()
            return any(candidate.lower() == lowered for candidate in candidates if candidate)

        if match_mode == "BeginsWith":
            lowered = normalized_query.lower()
            return any(
                candidate.lower().startswith(lowered) for candidate in candidates if candidate
            )

        lowered = normalized_query.lower()
        return any(lowered in candidate.lower() for candidate in candidates if candidate)

    def _collect_search_products(self, result: dict[str, Any] | None) -> list[dict[str, Any]]:
        if not result:
            return []

        products: list[dict[str, Any]] = []
        seen_codes: set[str] = set()

        def add_product(item: dict[str, Any] | None) -> None:
            if not isinstance(item, dict):
                return
            code = _format_lcsc_code(item.get("productCode"))
            if not code or code in seen_codes:
                return
            seen_codes.add(code)
            products.append(item)

        tip = result.get("tipProductDetailUrlVO")
        if isinstance(tip, dict) and tip.get("productCode"):
            detail = self._session.product_detail(str(tip["productCode"]))
            if detail:
                add_product(detail)
                return products

        for key in ("exactMatchResult",):
            entries = result.get(key)
            if isinstance(entries, list):
                for item in entries:
                    add_product(item)

        search_block = result.get("productSearchResultVO")
        if isinstance(search_block, dict):
            product_list = search_block.get("productList")
            if isinstance(product_list, list):
                for item in product_list:
                    add_product(item)

        return products

    def _lookup_by_lcsc_code(self, product_code: str) -> list[dict[str, Any]]:
        detail = self._session.product_detail(product_code)
        return [detail] if detail else []

    def _lookup_by_query(
        self,
        query: str,
        *,
        search_type: str,
        manufacturer: str = "",
        match_mode: str = "Exact",
    ) -> tuple[list[dict[str, Any]], list[str]]:
        warnings: list[str] = []

        if _is_lcsc_code(query):
            return self._lookup_by_lcsc_code(query), warnings

        result = self._session.search(query)
        products = self._collect_search_products(result)

        if search_type == "part_number":
            products = [
                product
                for product in products
                if self._matches_part_query(
                    product,
                    query,
                    manufacturer=manufacturer,
                    match_mode=match_mode,
                )
            ]

        total_count = None
        if isinstance(result, dict):
            raw_total = result.get("totalCount")
            if isinstance(raw_total, int) and raw_total > len(products):
                warnings.append(
                    f"LCSC reported {raw_total} matches but only {len(products)} were returned "
                    "by the unofficial search API."
                )

        return products, warnings

    def _apply_search_options(
        self,
        products: list[dict[str, Any]],
        search_options: str,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        if search_options == "None":
            return products, []

        warnings: list[str] = []
        filtered = products

        if search_options in {"InStock", "RohsAndInStock"}:
            filtered = [
                product
                for product in filtered
                if self._stock_value(self._stock_quantity(product)) > 0
            ]

        if search_options in {"Rohs", "RohsAndInStock"}:
            rohs_filtered = [product for product in filtered if product.get("isEnvironment") is True]
            if not rohs_filtered and filtered:
                warnings.append(
                    "RoHS filter requested but LCSC response did not include RoHS metadata "
                    "for matching parts; returning unfiltered stock results."
                )
            else:
                filtered = rohs_filtered

        return filtered, warnings

    def _search(
        self,
        query: str,
        *,
        search_type: str,
        records: int,
        starting_record: int = 0,
        search_options: str = "None",
        manufacturer: str = "",
        match_mode: str = "Exact",
    ) -> SearchResult:
        bounded_records = max(1, min(records, MAX_RECORDS))
        offset = max(0, starting_record)

        products, lookup_warnings = self._lookup_by_query(
            query,
            search_type=search_type,
            manufacturer=manufacturer,
            match_mode=match_mode,
        )
        products, filter_warnings = self._apply_search_options(products, search_options)
        warnings = lookup_warnings + filter_warnings

        page = products[offset : offset + bounded_records]
        records_out = [self._normalize_product(item) for item in page]

        return SearchResult(
            provider=self.provider_id.value,
            query=query,
            search_type=search_type,
            total_results=len(products),
            records=records_out,
            warnings=warnings,
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

        return self._search(
            cleaned_keyword,
            search_type="keyword",
            records=records,
            starting_record=starting_record,
            search_options=search_options,
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
                errors=[f"LCSC search accepts at most {MAX_PART_NUMBERS} part numbers per request."],
            )

        if len(part_numbers) == 1:
            return self._search(
                part_numbers[0],
                search_type="part_number",
                records=MAX_RECORDS,
                manufacturer=manufacturer,
                match_mode=match_mode,
            )

        combined_records: list[ComponentRecord] = []
        warnings: list[str] = []
        errors: list[str] = []
        seen_lcsc: set[str] = set()

        for part in part_numbers:
            result = self._search(
                part,
                search_type="part_number",
                records=MAX_RECORDS,
                manufacturer=manufacturer,
                match_mode=match_mode,
            )
            warnings.extend(result.warnings)
            errors.extend(result.errors)
            for record in result.records:
                if record.distributor_part_number in seen_lcsc:
                    continue
                seen_lcsc.add(record.distributor_part_number)
                combined_records.append(record)

        return SearchResult(
            provider=self.provider_id.value,
            query="|".join(part_numbers),
            search_type="part_number",
            total_results=len(combined_records),
            records=combined_records,
            errors=errors,
            warnings=warnings,
        )
