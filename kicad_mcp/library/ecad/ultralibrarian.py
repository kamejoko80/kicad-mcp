"""Ultra Librarian ECAD client.

Search uses anonymous HTTP requests. Download uses Playwright with a two-phase flow
matching the Ultra Librarian web UI:

1. SSO login from the home page (#Email / #Password), capturing browser storage state.
2. Authenticated search + multi-step export UI (Download Now -> KiCAD accordion ->
   KiCad v6+ -> export options -> a#submit-export).

Author: Henry Dang
Email: phuongminh.dang@gmail.com
"""

from __future__ import annotations

import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

from kicad_mcp import __version__
from kicad_mcp.library.credentials import CredentialStore, get_credential_store
from kicad_mcp.library.ecad.models import EcadDownloadResult, EcadPartMatch, EcadSearchResult
from kicad_mcp.library.ecad.samacsys import SamacSysClient

APP_BASE_URL = "https://app.ultralibrarian.com"
LOGIN_PATH = "/Account/Login"
SEARCH_PATH = "/Search"
MODERN_SEARCH_PATH = "/search"
USER_AGENT = f"kicad-mcp/{__version__} UltraLibrarian-ECAD"
PROVIDER_NAME = "ultralibrarian"

KICAD_V6_EXPORT_ID = "42"
SYMBOL_ORDER_FUNCTIONAL = "1-2"
FOOTPRINT_UNIT_METRIC = "2-2"

PLAYWRIGHT_TIMEOUT_ENV = "KICAD_MCP_ULTRALIBRARIAN_PLAYWRIGHT_TIMEOUT"
DEFAULT_PLAYWRIGHT_TIMEOUT_MS = 240_000
DEFAULT_SEARCH_TIMEOUT = 45.0

PLAYWRIGHT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
SYMBOL_ORDER_LABELS = ("Functional", "Sequential")
FOOTPRINT_UNIT_LABEL = "Metric (mm)"
FINAL_DOWNLOAD_SELECTOR = "a#submit-export"

DOWNLOAD_BUTTON_SELECTORS = (
    FINAL_DOWNLOAD_SELECTOR,
    "#download-button",
    "#btnDownload",
    "#btnDownloadCAD",
    "#submitExport",
    "#submit-export",
    "button#downloadBtn",
    "button:has-text('Download Selected')",
    "button:has-text('Download CAD')",
    "button:has-text('Download')",
    "input[type='submit'][value*='Download' i]",
    "form#export-submission-form button[type='submit']",
    "form.export-submission-form button[type='submit']",
    "a:has-text('Download')",
)

_DETAILS_LINK_PATTERN = re.compile(
    r'href="(?P<path>/details/(?P<uuid>[0-9a-f-]+)/(?P<mfr>[^/]+)/(?P<mpn>[^"?]+)\?uid=(?P<uid>\d+))"',
    re.I,
)
_KICAD_V6_EXPORT_PATTERN = re.compile(
    r'id="KiCADv6"[^>]*value="(\d+)"',
    re.I,
)
_PART_UNIQUE_ID_PATTERN = re.compile(
    r'name="PartUniqueId"[^>]*value="([^"]+)"',
    re.I,
)
_DESCRIPTION_PATTERN = re.compile(
    r'<meta\s+name=["\']description["\']\s+content=["\']([^"\']+)["\']',
    re.I,
)

logger = logging.getLogger("kicad-hardware-agent")


class UltraLibrarianNotConfiguredError(RuntimeError):
    """Raised when Ultra Librarian credentials are missing."""


class UltraLibrarianPlaywrightNotInstalledError(RuntimeError):
    """Raised when Playwright is not installed."""


class UltraLibrarianLibraryUnavailableError(RuntimeError):
    """Raised when Ultra Librarian has no downloadable library for a part."""

    def __init__(self, part_number: str, manufacturer: str = "") -> None:
        suffix = f" ({manufacturer})" if manufacturer.strip() else ""
        message = (
            f"No downloadable KiCad library is available on Ultra Librarian for part "
            f"'{part_number.strip()}'{suffix}."
        )
        super().__init__(message)
        self.part_number = part_number.strip()
        self.manufacturer = manufacturer.strip()


def _playwright_timeout_ms() -> int:
    raw = os.environ.get(PLAYWRIGHT_TIMEOUT_ENV, "").strip()
    if not raw:
        return DEFAULT_PLAYWRIGHT_TIMEOUT_MS
    try:
        return max(30_000, int(float(raw) * 1000))
    except ValueError:
        return DEFAULT_PLAYWRIGHT_TIMEOUT_MS


def _headless_enabled() -> bool:
    raw = os.environ.get("KICAD_MCP_ULTRALIBRARIAN_PLAYWRIGHT_HEADLESS", "true").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _require_playwright():
    try:
        from playwright.sync_api import sync_playwright

        return sync_playwright
    except ImportError as exc:
        raise UltraLibrarianPlaywrightNotInstalledError(
            "Playwright is required for Ultra Librarian downloads. Run: "
            "uv sync --extra playwright && uv run playwright install chromium"
        ) from exc


class UltraLibrarianClient:
    """Search and download KiCad libraries from app.ultralibrarian.com."""

    def __init__(self, credential_store: CredentialStore | None = None) -> None:
        self.credential_store = credential_store or get_credential_store()
        self._browser_trace: list[str] = []

    def _log_trace(self, message: str) -> None:
        self._browser_trace.append(message)
        logger.info("Ultra Librarian: %s", message)

    def _require_credentials(self) -> tuple[str, str]:
        username, password, _source = self.credential_store.get_ultralibrarian_credentials()
        if not username or not password:
            raise UltraLibrarianNotConfiguredError(
                "Ultra Librarian credentials are not configured. Register a free account at "
                "https://www.ultralibrarian.com/ then set ULTRALIBRARIAN_USERNAME and "
                "ULTRALIBRARIAN_PASSWORD or call "
                "set_ecad_provider_credentials(provider='ultralibrarian', ...)."
            )
        return username, password

    @staticmethod
    def _search_urls(query: str) -> list[str]:
        encoded = urllib.parse.urlencode({"queryText": query.strip()})
        modern = f"{APP_BASE_URL}{MODERN_SEARCH_PATH}?{encoded}"
        legacy = (
            f"{APP_BASE_URL}{SEARCH_PATH}?"
            + urllib.parse.urlencode({"q": query.strip()})
        )
        return [modern, legacy]

    def _fetch_search_html(self, query: str) -> tuple[str, list[str]]:
        errors: list[str] = []
        for url in self._search_urls(query):
            try:
                body, _final_url = self._fetch_url(url)
                return body.decode("utf-8", errors="replace"), errors
            except RuntimeError as exc:
                errors.append(str(exc))

        try:
            html = self._fetch_search_html_playwright(query)
            return html, errors
        except RuntimeError as exc:
            errors.append(str(exc))
            raise RuntimeError("; ".join(errors)) from exc

    def _fetch_search_html_playwright(self, query: str) -> str:
        sync_playwright = _require_playwright()
        timeout_ms = min(_playwright_timeout_ms(), 90_000)
        last_error = ""
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=_headless_enabled(),
                args=["--disable-dev-shm-usage"],
            )
            page = browser.new_page()
            page.set_default_timeout(timeout_ms)
            try:
                for url in self._search_urls(query):
                    try:
                        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                        return page.content()
                    except Exception as exc:
                        last_error = str(exc)
            finally:
                browser.close()
        raise RuntimeError(last_error or "Playwright search failed.")

    @staticmethod
    def _fetch_url(
        url: str,
        *,
        timeout: float = DEFAULT_SEARCH_TIMEOUT,
        retries: int = 2,
    ) -> tuple[bytes, str]:
        last_error: RuntimeError | None = None
        for attempt in range(retries + 1):
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml,*/*",
                    "Accept-Language": "en-US,en;q=0.9",
                },
                method="GET",
            )
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    return response.read(), response.geturl()
            except urllib.error.HTTPError as exc:
                detail = exc.read()[:240].decode("utf-8", errors="replace")
                raise RuntimeError(f"Ultra Librarian HTTP {exc.code}: {detail}") from exc
            except TimeoutError as exc:
                last_error = RuntimeError(
                    f"Ultra Librarian search request timed out after {timeout:.0f}s: {url}"
                )
            except urllib.error.URLError as exc:
                reason = exc.reason
                if isinstance(reason, TimeoutError):
                    last_error = RuntimeError(
                        f"Ultra Librarian search request timed out after {timeout:.0f}s: {url}"
                    )
                else:
                    raise RuntimeError(f"Ultra Librarian search request failed: {reason}") from exc
            if last_error is not None and attempt < retries:
                time.sleep(1.0 + attempt)
                continue
            if last_error is not None:
                raise last_error
        raise RuntimeError(f"Ultra Librarian search request failed: {url}")

    @staticmethod
    def _is_exact_part_match(query: str, part_number: str) -> bool:
        return query.strip().casefold() == urllib.parse.unquote(part_number).strip().casefold()

    @staticmethod
    def _decode_component(value: str) -> str:
        return urllib.parse.unquote(value.replace("+", " ")).strip()

    @staticmethod
    def _details_url(part_uuid: str, manufacturer: str, part_number: str, uid: str) -> str:
        encoded_mfr = urllib.parse.quote(manufacturer.strip(), safe="")
        encoded_mpn = urllib.parse.quote(part_number.strip(), safe="")
        query = urllib.parse.urlencode({"uid": uid.strip()}) if uid.strip() else ""
        base = (
            f"{APP_BASE_URL}/details/{part_uuid.strip()}/"
            f"{encoded_mfr}/{encoded_mpn}"
        )
        return f"{base}?{query}" if query else base

    @staticmethod
    def _no_library_result(query: str, manufacturer: str = "") -> EcadSearchResult:
        error = str(UltraLibrarianLibraryUnavailableError(query, manufacturer))
        return EcadSearchResult(
            provider=PROVIDER_NAME,
            query=query,
            total_results=0,
            errors=[error],
        )

    def _collect_exact_search_candidates(self, query: str, html: str) -> list[dict[str, str]]:
        candidates: list[dict[str, str]] = []
        seen: set[tuple[str, str, str]] = set()
        for match in _DETAILS_LINK_PATTERN.finditer(html):
            part_number = self._decode_component(match.group("mpn"))
            manufacturer = self._decode_component(match.group("mfr"))
            if not self._is_exact_part_match(query, part_number):
                continue
            key = (
                part_number.casefold(),
                manufacturer.casefold(),
                match.group("uuid").casefold(),
            )
            if key in seen:
                continue
            seen.add(key)
            candidates.append(
                {
                    "path": match.group("path"),
                    "uuid": match.group("uuid"),
                    "manufacturer": manufacturer,
                    "part_number": part_number,
                    "uid": match.group("uid"),
                }
            )
        return candidates

    @staticmethod
    def _extract_description(html: str) -> str:
        match = _DESCRIPTION_PATTERN.search(html)
        if match:
            return match.group(1).strip()
        return ""

    @staticmethod
    def _extract_kicad_export_id(html: str) -> str:
        match = _KICAD_V6_EXPORT_PATTERN.search(html)
        return match.group(1) if match else ""

    @staticmethod
    def _extract_part_unique_id(html: str) -> str:
        match = _PART_UNIQUE_ID_PATTERN.search(html)
        return match.group(1).strip() if match else ""

    def _fetch_details_page(self, candidate: dict[str, str]) -> tuple[str, str]:
        url = urllib.parse.urljoin(APP_BASE_URL, candidate["path"])
        body, final_url = self._fetch_url(url)
        return body.decode("utf-8", errors="replace"), final_url

    def _match_from_details(
        self,
        candidate: dict[str, str],
        html: str,
    ) -> EcadPartMatch | None:
        export_id = self._extract_kicad_export_id(html)
        part_unique_id = self._extract_part_unique_id(html) or candidate["uuid"]
        if not export_id:
            return None
        return EcadPartMatch(
            provider=PROVIDER_NAME,
            part_id=part_unique_id,
            part_number=candidate["part_number"],
            manufacturer=candidate["manufacturer"],
            description=self._extract_description(html),
            has_symbol=True,
            has_footprint=True,
            has_3d_model="ThreeDModel" in html or "3D Model Available" in html,
            downloadable=True,
            part_view_url=self._details_url(
                candidate["uuid"],
                candidate["manufacturer"],
                candidate["part_number"],
                candidate["uid"],
            ),
        )

    def _resolve_downloadable_match(
        self,
        part_number: str,
        manufacturer: str = "",
    ) -> EcadPartMatch:
        search = self.search_components(part_number, manufacturer=manufacturer, limit=1)
        if search.matches and search.matches[0].downloadable:
            return search.matches[0]
        raise UltraLibrarianLibraryUnavailableError(part_number, manufacturer)

    def resolve_part(
        self,
        part_number: str,
        manufacturer: str = "",
    ) -> EcadPartMatch:
        cleaned_part = part_number.strip()
        if not cleaned_part:
            raise ValueError("part_number cannot be empty.")
        return self._resolve_downloadable_match(cleaned_part, manufacturer)

    def search_components(
        self,
        query: str,
        *,
        manufacturer: str = "",
        limit: int = 10,
    ) -> EcadSearchResult:
        cleaned_query = query.strip()
        if not cleaned_query:
            return EcadSearchResult(
                provider=PROVIDER_NAME,
                query=query,
                total_results=0,
                errors=["Query cannot be empty."],
            )

        try:
            html, _errors = self._fetch_search_html(cleaned_query)
        except RuntimeError as exc:
            return EcadSearchResult(
                provider=PROVIDER_NAME,
                query=cleaned_query,
                total_results=0,
                errors=[str(exc)],
            )
        candidates = self._collect_exact_search_candidates(cleaned_query, html)
        if manufacturer.strip():
            cleaned_mfr = manufacturer.strip().casefold()
            candidates = [
                candidate
                for candidate in candidates
                if candidate["manufacturer"].casefold() == cleaned_mfr
            ]

        if not candidates:
            return self._no_library_result(cleaned_query, manufacturer)

        matches: list[EcadPartMatch] = []
        for candidate in candidates:
            try:
                details_html, _details_url = self._fetch_details_page(candidate)
            except RuntimeError:
                continue
            match = self._match_from_details(candidate, details_html)
            if match and match.downloadable:
                matches.append(match)
            if len(matches) >= max(1, limit):
                break

        if not matches:
            return self._no_library_result(cleaned_query, manufacturer)

        return EcadSearchResult(
            provider=PROVIDER_NAME,
            query=cleaned_query,
            total_results=len(matches),
            matches=matches,
        )

    @staticmethod
    def _default_download_dir() -> Path:
        override = os.environ.get("KICAD_MCP_ULTRALIBRARIAN_DOWNLOAD_DIR")
        if override:
            return Path(override).expanduser()
        return get_credential_store().config_dir / "ultralibrarian-downloads"

    def verify_credentials(self) -> bool:
        username, password, _source = self.credential_store.get_ultralibrarian_credentials()
        if not username or not password:
            return False
        try:
            sync_playwright = _require_playwright()
            timeout_ms = min(_playwright_timeout_ms(), 60_000)
            self._browser_trace = []
            with sync_playwright() as playwright:
                _perform_sso_login(
                    playwright,
                    username,
                    password,
                    self._log_trace,
                    timeout_ms,
                )
                return True
        except Exception:
            return False

    def diagnose_session(self, *, attempt_login: bool = False) -> dict[str, object]:
        username, _password, source = self.credential_store.get_ultralibrarian_credentials()
        report: dict[str, object] = {
            "provider": PROVIDER_NAME,
            "download_method": "playwright",
            "credentials_configured": bool(username),
            "credential_source": source,
            "playwright_timeout_seconds": _playwright_timeout_ms() / 1000,
            "headless": _headless_enabled(),
            "browser_trace": [],
        }
        try:
            _require_playwright()
            report["playwright_installed"] = True
        except UltraLibrarianPlaywrightNotInstalledError as exc:
            report["playwright_installed"] = False
            report["recommendation"] = str(exc)
            return report

        if attempt_login:
            self._browser_trace = []
            ok = self.verify_credentials()
            report["login_attempt"] = "success" if ok else "failed"
            report["browser_trace"] = list(self._browser_trace)
        else:
            report["recommendation"] = (
                "Run debug_ultralibrarian_session(attempt_login=true) to test SSO login."
            )
        return report

    def download_component_library(
        self,
        *,
        part_number: str = "",
        manufacturer: str = "",
        part_id: str = "",
        part_view_url: str = "",
        output_dir: str = "",
        extract: bool = True,
        overwrite: bool = False,
    ) -> EcadDownloadResult:
        cleaned_url = part_view_url.strip()
        cleaned_part_id = part_id.strip()
        cleaned_part = part_number.strip()
        cleaned_mfr = manufacturer.strip()

        if cleaned_url:
            resolved = EcadPartMatch(
                provider=PROVIDER_NAME,
                part_id=cleaned_part_id or cleaned_part,
                part_number=cleaned_part or cleaned_part_id,
                manufacturer=cleaned_mfr,
                downloadable=True,
                part_view_url=cleaned_url,
            )
        elif cleaned_part_id and cleaned_part and cleaned_mfr:
            resolved = EcadPartMatch(
                provider=PROVIDER_NAME,
                part_id=cleaned_part_id,
                part_number=cleaned_part,
                manufacturer=cleaned_mfr,
                downloadable=True,
                part_view_url=self._details_url(cleaned_part_id, cleaned_mfr, cleaned_part, ""),
            )
        elif cleaned_part_id and cleaned_part:
            resolved = self.resolve_part(cleaned_part, cleaned_mfr)
            resolved.part_id = cleaned_part_id
        else:
            resolved = self.resolve_part(cleaned_part, cleaned_mfr)

        if not resolved.downloadable:
            raise UltraLibrarianLibraryUnavailableError(
                resolved.part_number or part_number,
                resolved.manufacturer or manufacturer,
            )

        if not resolved.part_view_url:
            raise RuntimeError("Ultra Librarian part view URL is missing; run search first.")

        username, password = self._require_credentials()
        sync_playwright = _require_playwright()
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        target_root = Path(output_dir).expanduser() if output_dir else self._default_download_dir()
        target_root.mkdir(parents=True, exist_ok=True)
        safe_name = re.sub(r"[^\w.\-]+", "_", resolved.part_number or resolved.part_id)
        zip_path = target_root / f"ul_{safe_name}.zip"
        if zip_path.exists() and not overwrite:
            raise RuntimeError(f"Output file already exists: {zip_path}")

        timeout_ms = _playwright_timeout_ms()
        self._browser_trace = []

        with sync_playwright() as playwright:
            try:
                auth_state = _perform_sso_login(
                    playwright,
                    username,
                    password,
                    self._log_trace,
                    timeout_ms,
                )
                _download_part_library(
                    playwright,
                    auth_state,
                    resolved.part_number,
                    resolved.part_view_url,
                    self._log_trace,
                    timeout_ms,
                    zip_path,
                )
                self._log_trace(f"Saved ZIP to {zip_path}")
            except PlaywrightTimeoutError as exc:
                raise RuntimeError(
                    "Ultra Librarian Playwright download timed out. "
                    f"Steps: {' -> '.join(self._browser_trace)}. "
                    "Increase KICAD_MCP_ULTRALIBRARIAN_PLAYWRIGHT_TIMEOUT."
                ) from exc
            except Exception as exc:
                if self._browser_trace:
                    raise RuntimeError(
                        "Ultra Librarian download failed. "
                        f"Steps: {' -> '.join(self._browser_trace)}. "
                        f"Error: {exc}"
                    ) from exc
                raise

        zip_bytes = zip_path.read_bytes()
        if zip_bytes[:2] != b"PK":
            raise RuntimeError(
                "Ultra Librarian did not save a ZIP archive. "
                f"Steps: {' -> '.join(self._browser_trace)}"
            )

        extracted_files: list[str] = []
        library_name = zip_path.stem.replace("ul_", "", 1) or safe_name
        if extract:
            extracted_files = SamacSysClient._extract_kicad_assets(
                zip_bytes,
                target_root,
                library_name,
            )

        return EcadDownloadResult(
            provider=PROVIDER_NAME,
            part_id=resolved.part_id,
            part_number=resolved.part_number,
            manufacturer=resolved.manufacturer,
            zip_path=str(zip_path),
            output_dir=str(target_root),
            extracted_files=extracted_files,
            library_name=library_name,
        )


def _launch_browser(playwright):
    return playwright.chromium.launch(
        headless=_headless_enabled(),
        args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
        ],
    )


def _new_browser_context(browser, *, storage_state=None, accept_downloads: bool = False):
    options: dict[str, object] = {
        "user_agent": PLAYWRIGHT_USER_AGENT,
        "viewport": {"width": 1920, "height": 1080},
    }
    if storage_state is not None:
        options["storage_state"] = storage_state
    if accept_downloads:
        options["accept_downloads"] = True
    return browser.new_context(**options)


def _perform_sso_login(
    playwright,
    username: str,
    password: str,
    log: Callable[[str], None],
    timeout_ms: int,
) -> dict:
    """Authenticate via the Ultra Librarian home-page SSO flow."""
    browser = _launch_browser(playwright)
    context = _new_browser_context(browser)
    page = context.new_page()
    page.set_default_timeout(timeout_ms)
    try:
        log("Navigating to Ultra Librarian home")
        page.goto(f"{APP_BASE_URL}/", wait_until="commit", timeout=timeout_ms)
        page.wait_for_selector("body", timeout=min(timeout_ms, 15_000))

        log("Clicking UI login button")
        login_btn = (
            page.locator("a[href*='login']")
            .or_(page.locator("text=Log In"))
            .or_(page.locator("text=Login"))
            .first
        )
        login_btn.wait_for(state="visible", timeout=min(timeout_ms, 15_000))
        login_btn.click()
        page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)

        log("Waiting for login form")
        _wait_for_login_form(page, timeout_ms)

        log("Filling SSO credentials")
        email_field = (
            page.locator("#Email")
            .or_(page.locator("input[placeholder='Email']"))
            .or_(page.locator("input[type='email']"))
            .or_(page.locator('input[name="Username"]'))
            .first
        )
        email_field.wait_for(state="visible", timeout=min(timeout_ms, 15_000))
        email_field.focus()
        email_field.fill(username)

        password_field = (
            page.locator("#Password")
            .or_(page.locator("input[placeholder='Password']"))
            .or_(page.locator("input[type='password']"))
            .or_(page.locator('input[name="Password"]'))
            .first
        )
        password_field.wait_for(state="visible", timeout=min(timeout_ms, 15_000))
        password_field.focus()
        password_field.fill(password)

        log("Submitting SSO login")
        submit_button = (
            page.locator("button:has-text('Login')")
            .or_(page.locator("input[value='Login']"))
            .or_(page.locator("button[type='submit']"))
            .first
        )
        submit_button.click()

        log("Waiting for post-login redirect")
        _wait_for_post_login(page, timeout_ms)
        auth_state = context.storage_state()
        log("SSO authentication succeeded")
        return auth_state
    finally:
        context.close()
        browser.close()


def _login_form_ready(page) -> bool:
    selectors = (
        "#Email",
        'input[name="Username"]',
        "input[placeholder='Email']",
        "input[type='email']",
    )
    for selector in selectors:
        locator = page.locator(selector)
        if locator.count() == 0:
            continue
        try:
            if locator.first.is_visible():
                return True
        except Exception:
            return True
    return False


def _wait_for_login_form(page, timeout_ms: int) -> None:
    deadline = time.monotonic() + min(timeout_ms, 45_000) / 1000
    last_url = page.url
    while time.monotonic() < deadline:
        last_url = page.url
        if _login_form_ready(page):
            return
        page.wait_for_timeout(500)
    raise RuntimeError(
        f"Ultra Librarian login form did not appear within {min(timeout_ms, 45_000) / 1000:.0f}s "
        f"(last URL: {last_url})."
    )


def _wait_for_post_login(page, timeout_ms: int) -> None:
    """Wait until SSO finishes and the Ultra Librarian app is reachable."""
    deadline = time.monotonic() + min(timeout_ms, 45_000) / 1000
    last_url = page.url
    while time.monotonic() < deadline:
        last_url = page.url
        lowered = last_url.lower()
        if "sso.ultralibrarian.com" in lowered:
            page.wait_for_timeout(500)
            continue
        if "app.ultralibrarian.com" not in lowered:
            page.wait_for_timeout(500)
            continue
        if _on_login_page(page):
            page.wait_for_timeout(500)
            continue
        if "/search" in lowered or lowered.rstrip("/").endswith("ultralibrarian.com"):
            return
        login_btn = page.locator("a[href*='login']").or_(page.locator("text=Log In")).first
        if login_btn.count() == 0 or not login_btn.is_visible():
            return
        page.wait_for_timeout(500)
    raise RuntimeError(
        f"Ultra Librarian SSO login did not complete within {min(timeout_ms, 45_000) / 1000:.0f}s "
        f"(last URL: {last_url})."
    )


def _open_part_details_page(
    page,
    part_number: str,
    part_view_url: str,
    log: Callable[[str], None],
    timeout_ms: int,
) -> None:
    cleaned_part = part_number.strip()
    search_url = (
        f"{APP_BASE_URL}{MODERN_SEARCH_PATH}?"
        + urllib.parse.urlencode({"queryText": cleaned_part})
    )
    log(f"Searching for {cleaned_part}")
    page.goto(search_url, wait_until="domcontentloaded", timeout=timeout_ms)

    part_link = page.locator(f"text={cleaned_part}").first
    try:
        part_link.wait_for(state="visible", timeout=min(timeout_ms, 20_000))
        part_link.click()
        return
    except Exception:
        if part_view_url.strip():
            log("Search result link not found; opening details URL")
            page.goto(part_view_url.strip(), wait_until="domcontentloaded", timeout=timeout_ms)
            return
        raise RuntimeError(
            f"Ultra Librarian search did not show a clickable result for '{cleaned_part}'."
        )


def _select_export_dropdowns(page, log: Callable[[str], None]) -> None:
    dropdowns = page.locator("select")
    count = dropdowns.count()
    symbol_set = False
    metric_set = False
    for index in range(count):
        dropdown = dropdowns.nth(index)
        html_content = dropdown.inner_html()
        if not symbol_set:
            for label in SYMBOL_ORDER_LABELS:
                if label in html_content:
                    dropdown.select_option(label=label)
                    log(f"Set symbol ordering={label}")
                    symbol_set = True
                    break
        if not metric_set and FOOTPRINT_UNIT_LABEL in html_content:
            dropdown.select_option(label=FOOTPRINT_UNIT_LABEL)
            log(f"Set footprint unit={FOOTPRINT_UNIT_LABEL}")
            metric_set = True


def _run_export_download_ui(
    page,
    log: Callable[[str], None],
    timeout_ms: int,
    zip_path: Path,
) -> None:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    log("Opening CAD format configuration panel")
    page.wait_for_selector("select", timeout=min(timeout_ms, 25_000))
    page.wait_for_timeout(4000)

    first_download_btn = page.locator("button:has-text('Download Now')").first
    first_download_btn.click(force=True)

    log("Expanding KiCAD accordion")
    for header_selector in ("text=KiCAD v6+", "text=KiCAD"):
        kicad_header = page.locator(header_selector).first
        if kicad_header.count() == 0:
            continue
        try:
            kicad_header.wait_for(state="visible", timeout=min(timeout_ms, 15_000))
            kicad_header.click(force=True)
            page.wait_for_timeout(2000)
            break
        except Exception:
            continue

    kicad_checkbox = page.locator("input#KiCADv6")
    kicad_checkbox.wait_for(state="attached", timeout=min(timeout_ms, 15_000))
    if not kicad_checkbox.is_checked():
        selected = False
        try:
            page.locator("label[for='KiCADv6']").click(
                force=True,
                timeout=min(timeout_ms, 10_000),
            )
            selected = kicad_checkbox.is_checked()
        except Exception:
            selected = False
        if not selected:
            kicad_checkbox.evaluate(
                "el => { el.checked = true; "
                "el.dispatchEvent(new Event('change', { bubbles: true })); }"
            )
    if not kicad_checkbox.is_checked():
        raise RuntimeError(
            "Could not select KiCad v6+ export format on Ultra Librarian details page."
        )
    export_value = kicad_checkbox.get_attribute("value") or ""
    if export_value and export_value != KICAD_V6_EXPORT_ID:
        raise RuntimeError(
            f"Unexpected KiCad export id '{export_value}' (expected {KICAD_V6_EXPORT_ID})."
        )
    log("Selected KiCad v6+ export")

    _select_export_dropdowns(page, log)
    page.wait_for_timeout(2000)

    log("Triggering final export download")
    final_download_btn = page.locator(FINAL_DOWNLOAD_SELECTOR)
    final_download_btn.wait_for(state="visible", timeout=min(timeout_ms, 15_000))
    try:
        with page.expect_download(timeout=min(timeout_ms, 60_000)) as download_info:
            final_download_btn.click(force=True)
        download = download_info.value
        suggested = download.suggested_filename
        target = zip_path
        if suggested and suggested.lower().endswith(".zip"):
            target = zip_path.with_name(suggested)
        download.save_as(str(target))
        if target != zip_path and target.exists():
            target.replace(zip_path)
        return
    except PlaywrightTimeoutError:
        log("No browser download event; trying /Export/Download response fallback")

    with page.expect_response(
        lambda response: "/Export/Download" in response.url and response.status == 200,
        timeout=min(timeout_ms, 60_000),
    ) as response_info:
        final_download_btn.click(force=True)
    body = response_info.value.body()
    if body[:2] != b"PK":
        raise RuntimeError("Ultra Librarian /Export/Download response was not a ZIP archive.")
    zip_path.write_bytes(body)


def _download_part_library(
    playwright,
    auth_state: dict,
    part_number: str,
    part_view_url: str,
    log: Callable[[str], None],
    timeout_ms: int,
    zip_path: Path,
) -> None:
    browser = _launch_browser(playwright)
    context = _new_browser_context(
        browser,
        storage_state=auth_state,
        accept_downloads=True,
    )
    page = context.new_page()
    page.set_default_timeout(timeout_ms)
    page.set_default_navigation_timeout(timeout_ms)
    try:
        _open_part_details_page(page, part_number, part_view_url, log, timeout_ms)
        _run_export_download_ui(page, log, timeout_ms, zip_path)
    finally:
        context.close()
        browser.close()


def _has_visible_login_link(page) -> bool:
    login_link = page.locator("#loginLink, a#loginLink, a[href*='/Account/Login']")
    if login_link.count() == 0:
        return False
    try:
        return login_link.first.is_visible()
    except Exception:
        return True


def _on_login_page(page) -> bool:
    url = page.url.lower()
    if "sso.ultralibrarian.com" in url and "/account/login" in url:
        return True
    if page.locator("#Email").count() > 0 and page.locator("#Password").count() > 0:
        return True
    return False


def _on_details_path(page) -> bool:
    path = urllib.parse.urlparse(page.url).path.lower()
    return "/details/" in path


def _has_export_form(page) -> bool:
    if page.locator("#KiCADv6").count() == 0:
        return False
    if page.locator("#export-submission-form, form.export-submission-form").count() > 0:
        return True
    return page.locator("select[name^='export_options']").count() > 0


def _on_authenticated_details(page) -> bool:
    if not _on_details_path(page):
        return False
    if _on_login_page(page) or _has_visible_login_link(page):
        return False
    return _has_export_form(page)
