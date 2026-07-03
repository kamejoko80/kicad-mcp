"""Provider registry for component search backends.

Author: Henry Dang
Email: phuongminh.dang@gmail.com
"""

from __future__ import annotations

from typing import Type

from kicad_mcp.library.credentials import CredentialStore, ProviderId, get_credential_store
from kicad_mcp.library.providers.base import ComponentSearchProvider
from kicad_mcp.library.providers.digikey import DigiKeyProvider
from kicad_mcp.library.providers.lcsc import LCSCProvider
from kicad_mcp.library.providers.mouser import MouserProvider

_PROVIDER_TYPES: dict[ProviderId, Type[ComponentSearchProvider]] = {
    ProviderId.MOUSER: MouserProvider,
    ProviderId.DIGIKEY: DigiKeyProvider,
    ProviderId.LCSC: LCSCProvider,
}


def list_provider_ids() -> list[str]:
    return [provider.value for provider in ProviderId]


def resolve_provider_id(name: str) -> ProviderId:
    normalized = name.strip().lower()
    for provider in ProviderId:
        if provider.value == normalized:
            return provider
    supported = ", ".join(list_provider_ids())
    raise ValueError(f"Unknown provider '{name}'. Supported providers: {supported}")


def get_provider(
    name: str,
    credential_store: CredentialStore | None = None,
) -> ComponentSearchProvider:
    provider_id = resolve_provider_id(name)
    store = credential_store or get_credential_store()
    provider_type = _PROVIDER_TYPES[provider_id]
    return provider_type(store)
