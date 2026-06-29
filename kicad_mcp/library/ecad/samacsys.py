"""SamacSys Component Search Engine client.

Uses the same HTTP Basic authentication flow as the official Library Loader:
  GET https://componentsearchengine.com/ga/model.php?partID={id}

Author: Henry Dang
Email: phuongminh.dang@gmail.com
"""

from __future__ import annotations

import base64
import io
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

from kicad_mcp import __version__
from kicad_mcp.library.credentials import CredentialStore, get_credential_store
from kicad_mcp.library.ecad.models import EcadDownloadResult, EcadPartMatch, EcadSearchResult

CSE_BASE_URL = "https://componentsearchengine.com"
CSE_MS_BASE_URL = "https://ms.componentsearchengine.com"
DOWNLOAD_PATH = "/ga/model.php"
USER_AGENT = f"kicad-mcp/{__version__} SamacSys-ECAD"
PROVIDER_NAME = "samacsys"

_PART_ID_PATTERN = re.compile(r"name=['\"]partID['\"][^>]*value=['\"](\d+)['\"]", re.I)
_PART_ID_URL_PATTERN = re.compile(r"partID=(\d+)", re.I)
_PART_VIEW_PATTERN = re.compile(r"/part-view/([^/?#'\"]+)/([^/?#'\"]+)")
_SEARCH_LINK_PATTERN = re.compile(
    r"""href=['"](/part-view/[^'"]+)['"]""",
    re.I,
)


class SamacSysNotConfiguredError(RuntimeError):
    """Raised when SamacSys credentials are missing."""


class SamacSysLibraryUnavailableError(RuntimeError):
    """Raised when SamacSys has no downloadable library for a part."""

    def __init__(self, part_number: str, manufacturer: str = "") -> None:
        suffix = f" ({manufacturer})" if manufacturer.strip() else ""
        message = (
            f"No downloadable KiCad library is available on SamacSys for part "
            f"'{part_number.strip()}'{suffix}."
        )
        super().__init__(message)
        self.part_number = part_number.strip()
        self.manufacturer = manufacturer.strip()


class SamacSysClient:
    """Search and download KiCad libraries from componentsearchengine.com."""

    def __init__(self, credential_store: CredentialStore | None = None) -> None:
        self.credential_store = credential_store or get_credential_store()

    def _require_credentials(self) -> tuple[str, str]:
        username, password, _source = self.credential_store.get_samacsys_credentials()
        if not username or not password:
            raise SamacSysNotConfiguredError(
                "SamacSys credentials are not configured. Register a free account at "
                "https://componentsearchengine.com/register then set SAMACSYS_USERNAME "
                "and SAMACSYS_PASSWORD or call set_ecad_provider_credentials(provider='samacsys', ...)."
            )
        return username, password

    def _basic_token(self, username: str, password: str) -> str:
        payload = f"{username}:{password}".encode("utf-8")
        return base64.b64encode(payload).decode("ascii")

    def _request(
        self,
        url: str,
        *,
        require_auth: bool = False,
        accept: str = "text/html,application/xhtml+xml,*/*",
    ) -> tuple[int, dict[str, str], bytes]:
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": accept,
            "Accept-Language": "en-US,en;q=0.9",
        }
        if require_auth:
            username, password = self._require_credentials()
            headers["Authorization"] = f"Basic {self._basic_token(username, password)}"

        request = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                response_headers = {
                    key.lower(): value
                    for key, value in response.headers.items()
                }
                return response.status, response_headers, response.read()
        except urllib.error.HTTPError as exc:
            body = exc.read()
            if exc.code in {401, 403} and require_auth:
                raise RuntimeError(
                    "SamacSys authentication failed. Verify username/password and accept "
                    "the latest terms at https://componentsearchengine.com/."
                ) from exc
            detail = body[:240].decode("utf-8", errors="replace")
            raise RuntimeError(f"SamacSys HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"SamacSys request failed: {exc.reason}") from exc

    def verify_credentials(self) -> bool:
        username, password, _source = self.credential_store.get_samacsys_credentials()
        if not username or not password:
            return False
        url = f"{CSE_BASE_URL}{DOWNLOAD_PATH}?partID="
        status, _headers, _body = self._request(url, require_auth=True)
        return 200 <= status < 400

    @staticmethod
    def _decode_part_view_path(path: str) -> tuple[str, str]:
        cleaned = path.strip("/")
        if not cleaned.startswith("part-view/"):
            raise ValueError(f"Invalid part-view path: {path}")
        _, part_number, manufacturer = cleaned.split("/", 2)
        return (
            urllib.parse.unquote(part_number),
            urllib.parse.unquote(manufacturer),
        )

    @staticmethod
    def _part_view_url(part_number: str, manufacturer: str) -> str:
        encoded_part = urllib.parse.quote(part_number.strip(), safe="")
        encoded_mfr = urllib.parse.quote(manufacturer.strip(), safe="")
        return f"{CSE_BASE_URL}/part-view/{encoded_part}/{encoded_mfr}"

    @staticmethod
    def _is_exact_part_match(query: str, part_number: str) -> bool:
        return query.strip().casefold() == part_number.strip().casefold()

    @staticmethod
    def _is_model_request_page(html: str) -> bool:
        lowered = html.lower()
        return (
            "what cad models would you like us to build" in lowered
            or "schematic symbol is unavailable for download" in lowered
        )

    @staticmethod
    def _no_library_result(query: str, manufacturer: str = "") -> EcadSearchResult:
        error = str(SamacSysLibraryUnavailableError(query, manufacturer))
        return EcadSearchResult(
            provider=PROVIDER_NAME,
            query=query,
            total_results=0,
            errors=[error],
        )

    def _finalize_match(self, match: EcadPartMatch | None) -> EcadPartMatch | None:
        if match is None:
            return None
        match.downloadable = self._valid_part_id(match.part_id)
        return match

    @staticmethod
    def _valid_part_id(part_id: str) -> bool:
        cleaned = part_id.strip()
        return cleaned.isdigit() and int(cleaned) > 0

    @staticmethod
    def _extract_part_ids(html: str) -> list[str]:
        values = _PART_ID_PATTERN.findall(html)
        values.extend(_PART_ID_URL_PATTERN.findall(html))
        seen: set[str] = set()
        ordered: list[str] = []
        for value in values:
            if not SamacSysClient._valid_part_id(value) or value in seen:
                continue
            seen.add(value)
            ordered.append(value)
        return ordered

    @staticmethod
    def _extract_description(html: str) -> str:
        match = re.search(
            r"<meta\s+name=['\"]description['\"]\s+content=['\"]([^'\"]+)['\"]",
            html,
            re.I,
        )
        if match:
            return match.group(1).strip()
        heading = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.I | re.S)
        if heading:
            text = re.sub(r"<[^>]+>", " ", heading.group(1))
            return " ".join(text.split())
        return ""

    @staticmethod
    def _extract_asset_flags(html: str) -> tuple[bool, bool, bool]:
        lowered = html.lower()
        has_symbol = "symbol.php" in lowered or "schematic symbol" in lowered
        has_footprint = "footprint.php" in lowered or "pcb footprint" in lowered
        has_3d = "3d model" in lowered or "3dmodel" in lowered
        return has_symbol, has_footprint, has_3d

    def _match_from_part_view(
        self,
        part_number: str,
        manufacturer: str,
        html: str,
    ) -> EcadPartMatch | None:
        if self._is_model_request_page(html):
            return None
        part_ids = self._extract_part_ids(html)
        if not part_ids:
            return None
        has_symbol, has_footprint, has_3d = self._extract_asset_flags(html)
        return self._finalize_match(
            EcadPartMatch(
                provider=PROVIDER_NAME,
                part_id=part_ids[0],
                part_number=part_number,
                manufacturer=manufacturer,
                description=self._extract_description(html),
                has_symbol=has_symbol,
                has_footprint=has_footprint,
                has_3d_model=has_3d,
                part_view_url=self._part_view_url(part_number, manufacturer),
            )
        )

    def _resolve_via_ms_entry(
        self,
        part_number: str,
        manufacturer: str,
    ) -> EcadPartMatch | None:
        query = urllib.parse.urlencode(
            {
                "mna": manufacturer,
                "mpn": part_number,
                "pna": "mouser",
                "vrq": "multi",
                "fmt": "zip",
                "lang": "en-GB",
            }
        )
        url = f"{CSE_MS_BASE_URL}/entry_u_newDesign.php?{query}"
        _status, _headers, body = self._request(url)
        html = body.decode("utf-8", errors="replace")
        if self._is_model_request_page(html):
            return None
        part_ids = self._extract_part_ids(html)
        if not part_ids:
            return None
        has_symbol, has_footprint, has_3d = self._extract_asset_flags(html)
        return self._finalize_match(
            EcadPartMatch(
                provider=PROVIDER_NAME,
                part_id=part_ids[0],
                part_number=part_number,
                manufacturer=manufacturer,
                description=self._extract_description(html),
                has_symbol=has_symbol,
                has_footprint=has_footprint,
                has_3d_model=has_3d,
                part_view_url=self._part_view_url(part_number, manufacturer),
            )
        )

    def _resolve_downloadable_match(
        self,
        part_number: str,
        manufacturer: str,
    ) -> EcadPartMatch:
        cleaned_part = part_number.strip()
        cleaned_mfr = manufacturer.strip()
        if not cleaned_part:
            raise ValueError("part_number cannot be empty.")
        if not cleaned_mfr:
            raise ValueError("manufacturer is required to resolve a downloadable library.")

        url = self._part_view_url(cleaned_part, cleaned_mfr)
        try:
            _status, _headers, body = self._request(url)
            html = body.decode("utf-8", errors="replace")
            match = self._match_from_part_view(cleaned_part, cleaned_mfr, html)
            if match and match.downloadable:
                return match
        except RuntimeError:
            pass

        match = self._resolve_via_ms_entry(cleaned_part, cleaned_mfr)
        if match and match.downloadable:
            return match

        raise SamacSysLibraryUnavailableError(cleaned_part, cleaned_mfr)

    def resolve_part(
        self,
        part_number: str,
        manufacturer: str = "",
    ) -> EcadPartMatch:
        cleaned_part = part_number.strip()
        cleaned_mfr = manufacturer.strip()
        if not cleaned_part:
            raise ValueError("part_number cannot be empty.")

        if cleaned_mfr:
            return self._resolve_downloadable_match(cleaned_part, cleaned_mfr)

        search = self.search_components(cleaned_part, limit=1)
        if search.matches and search.matches[0].downloadable:
            return search.matches[0]
        if search.errors:
            raise SamacSysLibraryUnavailableError(cleaned_part)
        raise SamacSysLibraryUnavailableError(cleaned_part)

    def _collect_exact_search_candidates(
        self,
        query: str,
        html: str,
    ) -> list[tuple[str, str]]:
        candidates: list[tuple[str, str]] = []
        seen_keys: set[tuple[str, str]] = set()

        for link in _SEARCH_LINK_PATTERN.findall(html):
            try:
                part_number, mfr = self._decode_part_view_path(link)
            except ValueError:
                continue
            if not self._is_exact_part_match(query, part_number):
                continue
            key = (part_number.casefold(), mfr.casefold())
            if key in seen_keys:
                continue
            seen_keys.add(key)
            candidates.append((part_number, mfr))

        for part_number, mfr in _PART_VIEW_PATTERN.findall(html):
            decoded_part = urllib.parse.unquote(part_number)
            if not self._is_exact_part_match(query, decoded_part):
                continue
            decoded_mfr = urllib.parse.unquote(mfr)
            key = (decoded_part.casefold(), decoded_mfr.casefold())
            if key in seen_keys:
                continue
            seen_keys.add(key)
            candidates.append((decoded_part, decoded_mfr))

        return candidates

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

        cleaned_mfr = manufacturer.strip()
        if cleaned_mfr:
            try:
                match = self._resolve_downloadable_match(cleaned_query, cleaned_mfr)
            except SamacSysLibraryUnavailableError:
                return self._no_library_result(cleaned_query, cleaned_mfr)
            except ValueError as exc:
                return EcadSearchResult(
                    provider=PROVIDER_NAME,
                    query=cleaned_query,
                    total_results=0,
                    errors=[str(exc)],
                )
            return EcadSearchResult(
                provider=PROVIDER_NAME,
                query=cleaned_query,
                total_results=1,
                matches=[match],
            )

        search_url = (
            f"{CSE_BASE_URL}/search?"
            + urllib.parse.urlencode({"term": cleaned_query})
        )
        try:
            _status, _headers, body = self._request(search_url)
        except RuntimeError as exc:
            return EcadSearchResult(
                provider=PROVIDER_NAME,
                query=cleaned_query,
                total_results=0,
                errors=[str(exc)],
            )

        html = body.decode("utf-8", errors="replace")
        candidates = self._collect_exact_search_candidates(cleaned_query, html)
        if not candidates:
            return self._no_library_result(cleaned_query)

        matches: list[EcadPartMatch] = []
        for part_number, mfr in candidates:
            try:
                match = self._resolve_downloadable_match(part_number, mfr)
            except SamacSysLibraryUnavailableError:
                continue
            matches.append(match)
            if len(matches) >= max(1, limit):
                break

        if not matches:
            return self._no_library_result(cleaned_query)

        return EcadSearchResult(
            provider=PROVIDER_NAME,
            query=cleaned_query,
            total_results=len(matches),
            matches=matches,
        )

    @staticmethod
    def _default_download_dir() -> Path:
        override = os.environ.get("KICAD_MCP_SAMACSYS_DOWNLOAD_DIR")
        if override:
            return Path(override).expanduser()
        return get_credential_store().config_dir / "samacsys-downloads"

    @staticmethod
    def _filename_from_headers(headers: dict[str, str], fallback: str) -> str:
        disposition = headers.get("content-disposition", "")
        match = re.search(r'filename="?([^";]+)"?', disposition, re.I)
        if match:
            return match.group(1).strip()
        return fallback

    def download_component_library(
        self,
        *,
        part_number: str = "",
        manufacturer: str = "",
        part_id: str = "",
        output_dir: str = "",
        extract: bool = True,
        overwrite: bool = False,
    ) -> EcadDownloadResult:
        if part_id.strip():
            resolved = EcadPartMatch(
                provider=PROVIDER_NAME,
                part_id=part_id.strip(),
                part_number=part_number.strip() or part_id.strip(),
                manufacturer=manufacturer.strip(),
            )
        else:
            resolved = self.resolve_part(part_number, manufacturer)

        if not resolved.downloadable or not self._valid_part_id(resolved.part_id):
            raise SamacSysLibraryUnavailableError(
                resolved.part_number or part_number,
                resolved.manufacturer or manufacturer,
            )

        download_url = f"{CSE_BASE_URL}{DOWNLOAD_PATH}?partID={resolved.part_id}"
        status, headers, body = self._request(
            download_url,
            require_auth=True,
            accept="application/zip,application/octet-stream,*/*",
        )
        if not (200 <= status < 300):
            raise RuntimeError(f"SamacSys download failed with HTTP {status}.")

        content_type = headers.get("content-type", "")
        if body[:2] != b"PK" and "zip" not in content_type.lower():
            snippet = body[:240].decode("utf-8", errors="replace")
            raise RuntimeError(
                "SamacSys did not return a ZIP archive. You may need to sign in on "
                "componentsearchengine.com and accept updated terms. "
                f"Response preview: {snippet}"
            )

        target_root = Path(output_dir).expanduser() if output_dir else self._default_download_dir()
        target_root.mkdir(parents=True, exist_ok=True)

        safe_name = re.sub(r"[^\w.\-]+", "_", resolved.part_number or resolved.part_id)
        zip_name = self._filename_from_headers(headers, f"LIB_{safe_name}.zip")
        zip_path = target_root / zip_name
        if zip_path.exists() and not overwrite:
            raise RuntimeError(f"Output file already exists: {zip_path}")

        zip_path.write_bytes(body)
        extracted_files: list[str] = []
        library_name = zip_path.stem.replace("LIB_", "", 1) or safe_name

        if extract:
            extracted_files = self._extract_kicad_assets(body, target_root, library_name)

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

    @staticmethod
    def _extract_kicad_assets(
        zip_bytes: bytes,
        output_root: Path,
        library_name: str,
    ) -> list[str]:
        extracted: list[str] = []
        library_root = output_root / library_name
        footprint_dir = library_root / f"{library_name}.pretty"
        model_dir = library_root / f"{library_name}.3dshapes"
        footprint_dir.mkdir(parents=True, exist_ok=True)
        model_dir.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                name = info.filename.replace("\\", "/")
                lower_name = name.lower()
                data = archive.read(info)

                if lower_name.endswith(".kicad_sym"):
                    destination = library_root / Path(name).name
                elif lower_name.endswith(".kicad_mod"):
                    destination = footprint_dir / Path(name).name
                elif lower_name.endswith((".stp", ".step", ".wrl")):
                    destination = model_dir / Path(name).name
                elif "/kicad/" in lower_name and lower_name.endswith(".lib"):
                    destination = library_root / Path(name).name
                elif "/kicad/" in lower_name and lower_name.endswith(".dcm"):
                    destination = library_root / Path(name).name
                elif "/3d/" in lower_name and lower_name.endswith((".stp", ".step", ".wrl")):
                    destination = model_dir / Path(name).name
                else:
                    continue

                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(data)
                extracted.append(str(destination))

        return extracted
