"""ECAD provider registry.

Author: Henry Dang
Email: phuongminh.dang@gmail.com
"""

from __future__ import annotations

from enum import Enum
from typing import Type

from kicad_mcp.library.credentials import CredentialStore, get_credential_store
from kicad_mcp.library.ecad.samacsys import SamacSysClient


class EcadProviderId(str, Enum):
    SAMACSYS = "samacsys"


_ECADA_CLIENT_TYPES: dict[EcadProviderId, Type[SamacSysClient]] = {
    EcadProviderId.SAMACSYS: SamacSysClient,
}


def list_ecad_provider_ids() -> list[str]:
    return [provider.value for provider in EcadProviderId]


def resolve_ecad_provider_id(name: str) -> EcadProviderId:
    normalized = name.strip().lower()
    for provider in EcadProviderId:
        if provider.value == normalized:
            return provider
    supported = ", ".join(list_ecad_provider_ids())
    raise ValueError(f"Unknown ECAD provider '{name}'. Supported providers: {supported}")


def get_ecad_client(
    name: str,
    credential_store: CredentialStore | None = None,
) -> SamacSysClient:
    provider_id = resolve_ecad_provider_id(name)
    store = credential_store or get_credential_store()
    client_type = _ECADA_CLIENT_TYPES[provider_id]
    return client_type(store)
