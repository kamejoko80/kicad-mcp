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

logger = logging.getLogger("kicad-hardware-agent")


def _json_response(payload: dict) -> str:
    return json.dumps(payload, indent=2)


def register(mcp) -> None:
    @mcp.tool()
    def get_ecad_provider_status(provider: str = "") -> str:
        """
        Show credential status for ECAD library providers (SamacSys Component Search Engine).

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
                store.get_provider_status(ProviderId.SAMACSYS).to_dict(),
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

        SamacSys Component Search Engine uses the same username/password as
        https://componentsearchengine.com/. Set persist=true to save credentials
        to the local kicad-mcp config directory.
        """
        store = get_credential_store()
        try:
            provider_id = resolve_ecad_provider_id(provider)
        except ValueError as exc:
            return _json_response({"error": str(exc)})

        if provider_id.value != "samacsys":
            return _json_response({"error": f"Unsupported ECAD provider '{provider_id.value}'."})

        try:
            store.set_samacsys_credentials(username, password, persist=persist)
        except ValueError as exc:
            return _json_response({"error": str(exc)})

        status = store.get_provider_status(ProviderId.SAMACSYS).to_dict()
        return _json_response(
            {
                "message": "Updated SamacSys credentials.",
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

        status = store.get_provider_status(ProviderId.SAMACSYS).to_dict()
        return _json_response(
            {
                "message": f"Cleared credentials for provider '{provider_id.value}'.",
                "clear_persisted": clear_persisted,
                "provider": status,
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
        Search SamacSys Component Search Engine for KiCad symbol/footprint models.

        Returns part IDs and part-view URLs for exact part-number matches only.
        Provide manufacturer to resolve a specific MPN. When no downloadable library
        exists on SamacSys, returns zero matches with an explanatory error.
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
        provider: str = "samacsys",
        output_dir: str = "",
        extract: bool = True,
        overwrite: bool = False,
    ) -> str:
        """
        Download a KiCad component library ZIP from SamacSys Component Search Engine.

        Requires SamacSys credentials (componentsearchengine.com login). Provide
        part_number plus optional manufacturer, or part_id directly. When extract=true,
        writes symbol (.kicad_sym), footprint (.pretty), and 3D model files under output_dir.
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
            result = client.download_component_library(
                part_number=part_number,
                manufacturer=manufacturer,
                part_id=part_id,
                output_dir=output_dir,
                extract=extract,
                overwrite=overwrite,
            )
            return _json_response(result.to_dict())
        except SamacSysNotConfiguredError as exc:
            return _json_response({"error": str(exc)})
        except SamacSysLibraryUnavailableError as exc:
            return _json_response({"error": str(exc)})
        except ValueError as exc:
            return _json_response({"error": str(exc)})
        except RuntimeError as exc:
            return _json_response({"error": str(exc)})
