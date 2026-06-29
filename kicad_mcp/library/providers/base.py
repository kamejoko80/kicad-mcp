"""Abstract component search provider contract.

Author: Henry Dang
Email: phuongminh.dang@gmail.com
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from kicad_mcp.library.credentials import CredentialStore, ProviderCredentialStatus, ProviderId
from kicad_mcp.library.models import SearchResult


class ProviderNotConfiguredError(RuntimeError):
    """Raised when a provider is selected but credentials are missing."""


class ProviderNotImplementedError(RuntimeError):
    """Raised when a provider is registered but not yet implemented."""


class ComponentSearchProvider(ABC):
    provider_id: ProviderId
    display_name: str

    def __init__(self, credential_store: CredentialStore) -> None:
        self.credential_store = credential_store

    @abstractmethod
    def credential_status(self) -> ProviderCredentialStatus:
        """Return credential status for this provider."""

    @abstractmethod
    def search_by_keyword(
        self,
        keyword: str,
        *,
        records: int = 10,
        starting_record: int = 0,
        search_options: str = "None",
    ) -> SearchResult:
        """Search components by free-text keyword."""

    @abstractmethod
    def search_by_part_number(
        self,
        part_number: str,
        *,
        manufacturer: str = "",
        match_mode: str = "Exact",
    ) -> SearchResult:
        """Search components by distributor or manufacturer part number."""
