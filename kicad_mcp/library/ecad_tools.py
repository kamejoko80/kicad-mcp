"""SamacSys / ECAD library MCP tools.

Author: Henry Dang
Email: phuongminh.dang@gmail.com
"""

from __future__ import annotations

import json
import logging

from kicad_mcp.library.credentials import ProviderId, get_credential_store
from kicad_mcp.library.ecad.registry import get_ecad_client, list_ecad_provider_ids, resolve_ecad_provider_id
from kicad_mcp.library.ecad.samacsys import SamacSysLibraryUnavailableError, SamacSysNotConfiguredError
from kicad_mcp.library.ecad.ultralibrarian import (
    UltraLibrarianClient,
    UltraLibrarianLibraryUnavailableError,
    UltraLibrarianNotConfiguredError,
    UltraLibrarianPlaywrightNotInstalledError,
)

logger = logging.getLogger("kicad-hardware-agent")


def _json_response(payload: dict) -> str:
    return json.dumps(payload, indent=2)


def _ecad_provider_ids() -> list[ProviderId]:
    return [ProviderId.SAMACSYS, ProviderId.ULTRALIBRARIAN]


def register(mcp) -> None:
    @mcp.tool()
    def get_ecad_provider_status(provider: str = "") -> str:
        """
        Show credential status for ECAD library providers (SamacSys, Ultra Librarian).

        When provider is omitted, returns status for all registered ECAD providers.
        """
        store = get_credential_store()
        if provider.strip():
            try:
                provider_id = resolve_ecad_provider_id(provider)
            except ValueError as exc:
                return _json_response({"error": str(exc)})
            statuses = [store.get_provider_status(ProviderId(provider_id.value)).to_dict()]
        else:
            statuses = [
                store.get_provider_status(provider_id).to_dict()
                for provider_id in _ecad_provider_ids()
            ]

        return _json_response(
            {
                "config_dir": str(store.config_dir),
                "credentials_file": str(store.credentials_file),
                "supported_providers": list_ecad_provider_ids(),
                "providers": statuses,
            }
        )

    @mcp.tool()
    def set_ecad_provider_credentials(
        provider: str,
        username: str = "",
        password: str = "",
        persist: bool = False,
    ) -> str:
        """
        Configure ECAD provider credentials.

        SamacSys uses componentsearchengine.com login. Ultra Librarian uses
        ultralibrarian.com login. Set persist=true to save credentials to the
        local kicad-mcp config directory.
        """
        store = get_credential_store()
        try:
            provider_id = resolve_ecad_provider_id(provider)
        except ValueError as exc:
            return _json_response({"error": str(exc)})

        try:
            if provider_id.value == "samacsys":
                store.set_samacsys_credentials(username, password, persist=persist)
            elif provider_id.value == "ultralibrarian":
                store.set_ultralibrarian_credentials(username, password, persist=persist)
        except ValueError as exc:
            return _json_response({"error": str(exc)})

        status = store.get_provider_status(ProviderId(provider_id.value)).to_dict()
        return _json_response(
            {
                "message": f"Updated {status['display_name']} credentials.",
                "persisted": persist,
                "provider": status,
            }
        )

    @mcp.tool()
    def clear_ecad_provider_credentials(
        provider: str,
        clear_persisted: bool = False,
    ) -> str:
        """
        Clear in-session ECAD provider credentials.

        Set clear_persisted=true to also remove credentials saved on disk.
        Environment variables are never modified by this tool.
        """
        store = get_credential_store()
        try:
            provider_id = resolve_ecad_provider_id(provider)
        except ValueError as exc:
            return _json_response({"error": str(exc)})

        if provider_id.value == "samacsys":
            store.clear_samacsys_credentials(clear_persisted=clear_persisted)
        elif provider_id.value == "ultralibrarian":
            store.clear_ultralibrarian_credentials(clear_persisted=clear_persisted)

        status = store.get_provider_status(ProviderId(provider_id.value)).to_dict()
        return _json_response(
            {
                "message": f"Cleared credentials for provider '{provider_id.value}'.",
                "clear_persisted": clear_persisted,
                "provider": status,
            }
        )

    @mcp.tool()
    def debug_ultralibrarian_session(attempt_login: bool = False) -> str:
        """
        Diagnose Ultra Librarian SSO/session state without downloading a part.

        Returns connectivity probes, cookie names, whether the app search page looks
        logged-in, and optional login trace when attempt_login=true.
        No passwords or tokens are included in the report.
        """
        store = get_credential_store()
        status = store.get_provider_status(ProviderId.ULTRALIBRARIAN).to_dict()
        client = UltraLibrarianClient(store)
        try:
            report = client.diagnose_session(attempt_login=attempt_login)
            report["credential_status"] = status
            return _json_response(report)
        except RuntimeError as exc:
            return _json_response(
                {
                    "error": str(exc),
                    "credential_status": status,
                }
            )

    @mcp.tool()
    def search_ecad_components(
        query: str,
        provider: str = "samacsys",
        manufacturer: str = "",
        limit: int = 10,
    ) -> str:
        """
        Search an ECAD provider for KiCad symbol/footprint models.

        Supported providers: samacsys, ultralibrarian.
        Returns part IDs and part-view URLs for exact part-number matches only.
        Provide manufacturer to resolve a specific MPN.
        """
        logger.info("ECAD search via %s: %s", provider, query)
        try:
            client = get_ecad_client(provider)
            result = client.search_components(query, manufacturer=manufacturer, limit=limit)
            return _json_response(result.to_dict())
        except ValueError as exc:
            return _json_response({"error": str(exc)})

    @mcp.tool()
    def download_ecad_component_library(
        part_number: str = "",
        manufacturer: str = "",
        part_id: str = "",
        part_view_url: str = "",
        provider: str = "samacsys",
        output_dir: str = "",
        extract: bool = True,
        overwrite: bool = False,
    ) -> str:
        """
        Download a KiCad component library ZIP from an ECAD provider.

        Supported providers: samacsys, ultralibrarian.
        Requires provider credentials. Provide part_number plus optional manufacturer,
        or part_id directly. For Ultra Librarian, pass part_view_url from
        search_ecad_components to skip a second search. Ultra Librarian downloads require
        Playwright (headless Chromium) and export KiCad v6+ with functional symbol ordering
        and metric footprint units.
        When extract=true, writes symbol (.kicad_sym), footprint (.pretty), and 3D
        model files under output_dir.
        """
        logger.info(
            "ECAD download via %s: part_number=%s manufacturer=%s part_id=%s",
            provider,
            part_number,
            manufacturer,
            part_id,
        )
        try:
            client = get_ecad_client(provider)
            kwargs = {
                "part_number": part_number,
                "manufacturer": manufacturer,
                "part_id": part_id,
                "output_dir": output_dir,
                "extract": extract,
                "overwrite": overwrite,
            }
            if provider.strip().lower() == "ultralibrarian":
                kwargs["part_view_url"] = part_view_url
            result = client.download_component_library(**kwargs)
            return _json_response(result.to_dict())
        except (
            SamacSysNotConfiguredError,
            UltraLibrarianNotConfiguredError,
        ) as exc:
            return _json_response({"error": str(exc)})
        except (
            SamacSysLibraryUnavailableError,
            UltraLibrarianLibraryUnavailableError,
        ) as exc:
            return _json_response({"error": str(exc)})
        except ValueError as exc:
            return _json_response({"error": str(exc)})
        except RuntimeError as exc:
            return _json_response({"error": str(exc)})
        except UltraLibrarianPlaywrightNotInstalledError as exc:
            return _json_response({"error": str(exc)})
