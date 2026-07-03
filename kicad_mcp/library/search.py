"""Component library search MCP tools.

Author: Henry Dang
Email: phuongminh.dang@gmail.com
"""

from __future__ import annotations

import json
import logging

from kicad_mcp.library.credentials import get_credential_store
from kicad_mcp.library.ecad.registry import list_ecad_provider_ids
from kicad_mcp.library.providers.base import ProviderNotConfiguredError, ProviderNotImplementedError
from kicad_mcp.library.registry import get_provider, list_provider_ids, resolve_provider_id

logger = logging.getLogger("kicad-hardware-agent")


def _json_response(payload: dict) -> str:
    return json.dumps(payload, indent=2)


def register(mcp) -> None:
    @mcp.tool()
    def get_component_provider_status(provider: str = "") -> str:
        """
        Show credential status for component search providers (Mouser, DigiKey, LCSC).

        When provider is omitted, returns status for all registered providers.
        """
        store = get_credential_store()
        if provider.strip():
            try:
                provider_id = resolve_provider_id(provider)
            except ValueError as exc:
                return _json_response({"error": str(exc)})
            statuses = [store.get_provider_status(provider_id).to_dict()]
        else:
            statuses = [item.to_dict() for item in store.list_provider_statuses()]

        return _json_response(
            {
                "config_dir": str(store.config_dir),
                "credentials_file": str(store.credentials_file),
                "supported_providers": list_provider_ids(),
                "supported_ecad_providers": list_ecad_provider_ids(),
                "providers": statuses,
            }
        )

    @mcp.tool()
    def set_component_provider_credentials(
        provider: str,
        api_key: str = "",
        client_id: str = "",
        client_secret: str = "",
        access_token: str = "",
        persist: bool = False,
    ) -> str:
        """
        Configure distributor credentials for component search.

        Mouser uses a Search API key (api_key). DigiKey uses OAuth2 client_id and
        client_secret (Product Information V4). LCSC uses unofficial wmsc.lcsc.com
        endpoints and does not require credentials. Set persist=true to write credentials
        to the local kicad-mcp config directory.
        """
        store = get_credential_store()
        try:
            provider_id = resolve_provider_id(provider)
        except ValueError as exc:
            return _json_response({"error": str(exc)})

        try:
            if provider_id.value == "mouser":
                if not api_key.strip():
                    return _json_response(
                        {
                            "error": "api_key is required for provider 'mouser'.",
                        }
                    )
                store.set_mouser_api_key(api_key, persist=persist)
            elif provider_id.value == "digikey":
                store.set_digikey_credentials(
                    client_id=client_id,
                    client_secret=client_secret,
                    access_token=access_token,
                    persist=persist,
                )
            elif provider_id.value == "lcsc":
                return _json_response(
                    {
                        "message": (
                            "Provider 'lcsc' does not require credentials. "
                            "It uses unofficial LCSC wmsc.lcsc.com endpoints."
                        ),
                        "provider": store.get_provider_status(provider_id).to_dict(),
                    }
                )
        except ValueError as exc:
            return _json_response({"error": str(exc)})

        status = store.get_provider_status(provider_id).to_dict()
        return _json_response(
            {
                "message": f"Updated credentials for provider '{provider_id.value}'.",
                "persisted": persist,
                "provider": status,
            }
        )

    @mcp.tool()
    def clear_component_provider_credentials(
        provider: str,
        clear_persisted: bool = False,
    ) -> str:
        """
        Clear in-session distributor credentials.

        Set clear_persisted=true to also remove credentials saved on disk.
        Environment variables are never modified by this tool.
        """
        store = get_credential_store()
        try:
            provider_id = resolve_provider_id(provider)
        except ValueError as exc:
            return _json_response({"error": str(exc)})

        if provider_id.value == "mouser":
            store.clear_mouser_api_key(clear_persisted=clear_persisted)
        elif provider_id.value == "digikey":
            store.clear_digikey_credentials(clear_persisted=clear_persisted)
        elif provider_id.value == "lcsc":
            return _json_response(
                {
                    "message": "Provider 'lcsc' has no credentials to clear.",
                    "clear_persisted": clear_persisted,
                    "provider": store.get_provider_status(provider_id).to_dict(),
                }
            )

        status = store.get_provider_status(provider_id).to_dict()
        return _json_response(
            {
                "message": f"Cleared credentials for provider '{provider_id.value}'.",
                "clear_persisted": clear_persisted,
                "provider": status,
            }
        )

    @mcp.tool()
    def search_components_by_keyword(
        keyword: str,
        provider: str = "mouser",
        records: int = 10,
        starting_record: int = 0,
        search_options: str = "None",
    ) -> str:
        """
        Search distributor catalogs by keyword.

        provider: mouser (default), digikey, or lcsc.
        search_options (Mouser/DigiKey/LCSC): None, Rohs, InStock, RohsAndInStock.
        records: max 50 per API call.
        """
        logger.info("Keyword component search via %s: %s", provider, keyword)
        try:
            search_provider = get_provider(provider)
            result = search_provider.search_by_keyword(
                keyword,
                records=records,
                starting_record=starting_record,
                search_options=search_options,
            )
            return _json_response(result.to_dict())
        except ValueError as exc:
            return _json_response({"error": str(exc)})
        except ProviderNotConfiguredError as exc:
            return _json_response({"error": str(exc)})
        except ProviderNotImplementedError as exc:
            return _json_response({"error": str(exc)})
        except RuntimeError as exc:
            return _json_response({"error": str(exc)})

    @mcp.tool()
    def search_components_by_part_number(
        part_number: str,
        provider: str = "mouser",
        manufacturer: str = "",
        match_mode: str = "Exact",
    ) -> str:
        """
        Search distributor catalogs by part number.

        Accepts distributor or manufacturer part numbers (MPN).
        Separate up to 10 part numbers with '|'. Optional manufacturer narrows results.
        match_mode: Exact, BeginsWith, Contains.
        provider: mouser (default), digikey, or lcsc.
        """
        logger.info("Part-number component search via %s: %s", provider, part_number)
        try:
            search_provider = get_provider(provider)
            result = search_provider.search_by_part_number(
                part_number,
                manufacturer=manufacturer,
                match_mode=match_mode,
            )
            return _json_response(result.to_dict())
        except ValueError as exc:
            return _json_response({"error": str(exc)})
        except ProviderNotConfiguredError as exc:
            return _json_response({"error": str(exc)})
        except ProviderNotImplementedError as exc:
            return _json_response({"error": str(exc)})
        except RuntimeError as exc:
            return _json_response({"error": str(exc)})
