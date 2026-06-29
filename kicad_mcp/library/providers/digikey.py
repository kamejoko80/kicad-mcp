"""DigiKey component search provider placeholder.

DigiKey uses OAuth2 client credentials / authorization code flows. This module
defines the provider contract so future OAuth token management can plug in
without changing MCP tool signatures.

Author: Henry Dang
Email: phuongminh.dang@gmail.com
"""

from __future__ import annotations

from kicad_mcp.library.credentials import ProviderCredentialStatus, ProviderId
from kicad_mcp.library.models import SearchResult
from kicad_mcp.library.providers.base import ComponentSearchProvider, ProviderNotImplementedError


class DigiKeyProvider(ComponentSearchProvider):
    provider_id = ProviderId.DIGIKEY
    display_name = "DigiKey"

    def credential_status(self) -> ProviderCredentialStatus:
        return self.credential_store.get_provider_status(ProviderId.DIGIKEY)

    def search_by_keyword(
        self,
        keyword: str,
        *,
        records: int = 10,
        starting_record: int = 0,
        search_options: str = "None",
    ) -> SearchResult:
        raise ProviderNotImplementedError(
            "DigiKey component search is not implemented yet. "
            "Credential fields are reserved for upcoming OAuth2 support."
        )

    def search_by_part_number(
        self,
        part_number: str,
        *,
        manufacturer: str = "",
        match_mode: str = "Exact",
    ) -> SearchResult:
        raise ProviderNotImplementedError(
            "DigiKey component search is not implemented yet. "
            "Credential fields are reserved for upcoming OAuth2 support."
        )
