"""Credential storage for distributor component search APIs.

Supports environment variables, optional on-disk config, and in-session overrides.
Mouser uses API-key auth; DigiKey uses OAuth2 client credentials.

Author: Henry Dang
Email: phuongminh.dang@gmail.com
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class ProviderId(str, Enum):
    MOUSER = "mouser"
    DIGIKEY = "digikey"
    SAMACSYS = "samacsys"
    ULTRALIBRARIAN = "ultralibrarian"


PROVIDER_AUTH_TYPES: dict[ProviderId, str] = {
    ProviderId.MOUSER: "api_key",
    ProviderId.DIGIKEY: "oauth2",
    ProviderId.SAMACSYS: "basic_auth",
    ProviderId.ULTRALIBRARIAN: "session_login",
}

MOUSER_API_KEY_ENV_VARS = ("MOUSER_API_KEY", "MOUSER_SEARCH_API_KEY")
DIGIKEY_CLIENT_ID_ENV = "DIGIKEY_CLIENT_ID"
DIGIKEY_CLIENT_SECRET_ENV = "DIGIKEY_CLIENT_SECRET"
DIGIKEY_ACCESS_TOKEN_ENV = "DIGIKEY_ACCESS_TOKEN"
SAMACSYS_USERNAME_ENV_VARS = ("SAMACSYS_USERNAME", "SAMACSYS_CSE_USERNAME")
SAMACSYS_PASSWORD_ENV_VARS = ("SAMACSYS_PASSWORD", "SAMACSYS_CSE_PASSWORD")
ULTRALIBRARIAN_USERNAME_ENV_VARS = ("ULTRALIBRARIAN_USERNAME", "UL_USERNAME")
ULTRALIBRARIAN_PASSWORD_ENV_VARS = ("ULTRALIBRARIAN_PASSWORD", "UL_PASSWORD")


@dataclass
class ProviderCredentialStatus:
    provider: str
    display_name: str
    auth_type: str
    configured: bool
    source: str
    masked_credential: str | None = None
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "display_name": self.display_name,
            "auth_type": self.auth_type,
            "configured": self.configured,
            "source": self.source,
            "masked_credential": self.masked_credential,
            "notes": self.notes,
        }


def _mask_secret(value: str) -> str:
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def _resolve_config_dir() -> Path:
    override = os.environ.get("KICAD_MCP_CONFIG_DIR")
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "kicad-mcp"
    return Path.home() / ".config" / "kicad-mcp"


class CredentialStore:
    """Resolve and persist distributor API credentials."""

    def __init__(self, config_dir: Path | None = None) -> None:
        self._config_dir = config_dir or _resolve_config_dir()
        self._session_overrides: dict[str, dict[str, str]] = {}

    @property
    def config_dir(self) -> Path:
        return self._config_dir

    @property
    def credentials_file(self) -> Path:
        return self._config_dir / "credentials.json"

    def _load_file_credentials(self) -> dict[str, dict[str, str]]:
        path = self.credentials_file
        if not path.is_file():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        normalized: dict[str, dict[str, str]] = {}
        for provider, values in payload.items():
            if isinstance(provider, str) and isinstance(values, dict):
                normalized[provider] = {
                    str(key): str(value)
                    for key, value in values.items()
                    if value not in (None, "")
                }
        return normalized

    def _save_file_credentials(self, credentials: dict[str, dict[str, str]]) -> None:
        self._config_dir.mkdir(parents=True, exist_ok=True)
        self.credentials_file.write_text(
            json.dumps(credentials, indent=2),
            encoding="utf-8",
        )

    def _provider_bucket(
        self,
        provider: ProviderId,
        file_credentials: dict[str, dict[str, str]],
    ) -> dict[str, str]:
        merged = dict(file_credentials.get(provider.value, {}))
        merged.update(self._session_overrides.get(provider.value, {}))
        return merged

    def get_mouser_api_key(self) -> tuple[str | None, str]:
        session_key = self._session_overrides.get(ProviderId.MOUSER.value, {}).get("api_key")
        if session_key:
            return session_key, "session"

        for env_name in MOUSER_API_KEY_ENV_VARS:
            env_value = os.environ.get(env_name, "").strip()
            if env_value:
                return env_value, "environment"

        file_credentials = self._load_file_credentials()
        file_key = file_credentials.get(ProviderId.MOUSER.value, {}).get("api_key", "").strip()
        if file_key:
            return file_key, "file"

        return None, "none"

    def set_mouser_api_key(self, api_key: str, persist: bool = False) -> None:
        cleaned = api_key.strip()
        if not cleaned:
            raise ValueError("Mouser API key cannot be empty.")

        self._session_overrides.setdefault(ProviderId.MOUSER.value, {})["api_key"] = cleaned
        if persist:
            file_credentials = self._load_file_credentials()
            bucket = file_credentials.setdefault(ProviderId.MOUSER.value, {})
            bucket["api_key"] = cleaned
            self._save_file_credentials(file_credentials)

    def clear_mouser_api_key(self, clear_persisted: bool = False) -> None:
        self._session_overrides.pop(ProviderId.MOUSER.value, None)
        if clear_persisted:
            file_credentials = self._load_file_credentials()
            bucket = file_credentials.get(ProviderId.MOUSER.value, {})
            bucket.pop("api_key", None)
            if bucket:
                file_credentials[ProviderId.MOUSER.value] = bucket
            else:
                file_credentials.pop(ProviderId.MOUSER.value, None)
            if file_credentials:
                self._save_file_credentials(file_credentials)
            elif self.credentials_file.is_file():
                self.credentials_file.unlink(missing_ok=True)

    def get_digikey_credentials(self) -> tuple[dict[str, str], str]:
        session_values = self._session_overrides.get(ProviderId.DIGIKEY.value, {})
        if session_values:
            return dict(session_values), "session"

        env_values = {
            "client_id": os.environ.get(DIGIKEY_CLIENT_ID_ENV, "").strip(),
            "client_secret": os.environ.get(DIGIKEY_CLIENT_SECRET_ENV, "").strip(),
            "access_token": os.environ.get(DIGIKEY_ACCESS_TOKEN_ENV, "").strip(),
        }
        env_values = {key: value for key, value in env_values.items() if value}
        if env_values:
            return env_values, "environment"

        file_credentials = self._load_file_credentials()
        file_values = file_credentials.get(ProviderId.DIGIKEY.value, {})
        if file_values:
            return dict(file_values), "file"

        return {}, "none"

    def set_digikey_credentials(
        self,
        *,
        client_id: str = "",
        client_secret: str = "",
        access_token: str = "",
        persist: bool = False,
    ) -> None:
        values = {
            "client_id": client_id.strip(),
            "client_secret": client_secret.strip(),
            "access_token": access_token.strip(),
        }
        values = {key: value for key, value in values.items() if value}
        if not values:
            raise ValueError("Provide at least one DigiKey credential field.")

        self._session_overrides[ProviderId.DIGIKEY.value] = values
        if persist:
            file_credentials = self._load_file_credentials()
            bucket = file_credentials.setdefault(ProviderId.DIGIKEY.value, {})
            bucket.update(values)
            self._save_file_credentials(file_credentials)

    def clear_digikey_credentials(self, clear_persisted: bool = False) -> None:
        self._session_overrides.pop(ProviderId.DIGIKEY.value, None)
        if clear_persisted:
            file_credentials = self._load_file_credentials()
            file_credentials.pop(ProviderId.DIGIKEY.value, None)
            if file_credentials:
                self._save_file_credentials(file_credentials)
            elif self.credentials_file.is_file():
                self.credentials_file.unlink(missing_ok=True)

    def get_samacsys_credentials(self) -> tuple[str, str, str]:
        session_values = self._session_overrides.get(ProviderId.SAMACSYS.value, {})
        if session_values.get("username") and session_values.get("password"):
            return (
                session_values["username"],
                session_values["password"],
                "session",
            )

        env_username = ""
        env_password = ""
        for env_name in SAMACSYS_USERNAME_ENV_VARS:
            env_username = os.environ.get(env_name, "").strip()
            if env_username:
                break
        for env_name in SAMACSYS_PASSWORD_ENV_VARS:
            env_password = os.environ.get(env_name, "").strip()
            if env_password:
                break
        if env_username and env_password:
            return env_username, env_password, "environment"

        file_credentials = self._load_file_credentials()
        file_values = file_credentials.get(ProviderId.SAMACSYS.value, {})
        username = file_values.get("username", "").strip()
        password = file_values.get("password", "").strip()
        if username and password:
            return username, password, "file"

        return "", "", "none"

    def set_samacsys_credentials(
        self,
        username: str,
        password: str,
        persist: bool = False,
    ) -> None:
        cleaned_username = username.strip()
        cleaned_password = password.strip()
        if not cleaned_username or not cleaned_password:
            raise ValueError("SamacSys username and password are both required.")

        self._session_overrides[ProviderId.SAMACSYS.value] = {
            "username": cleaned_username,
            "password": cleaned_password,
        }
        if persist:
            file_credentials = self._load_file_credentials()
            bucket = file_credentials.setdefault(ProviderId.SAMACSYS.value, {})
            bucket["username"] = cleaned_username
            bucket["password"] = cleaned_password
            self._save_file_credentials(file_credentials)

    def clear_samacsys_credentials(self, clear_persisted: bool = False) -> None:
        self._session_overrides.pop(ProviderId.SAMACSYS.value, None)
        if clear_persisted:
            file_credentials = self._load_file_credentials()
            file_credentials.pop(ProviderId.SAMACSYS.value, None)
            if file_credentials:
                self._save_file_credentials(file_credentials)
            elif self.credentials_file.is_file():
                self.credentials_file.unlink(missing_ok=True)

    def get_ultralibrarian_credentials(self) -> tuple[str, str, str]:
        session_values = self._session_overrides.get(ProviderId.ULTRALIBRARIAN.value, {})
        if session_values.get("username") and session_values.get("password"):
            return (
                session_values["username"],
                session_values["password"],
                "session",
            )

        env_username = ""
        env_password = ""
        for env_name in ULTRALIBRARIAN_USERNAME_ENV_VARS:
            env_username = os.environ.get(env_name, "").strip()
            if env_username:
                break
        for env_name in ULTRALIBRARIAN_PASSWORD_ENV_VARS:
            env_password = os.environ.get(env_name, "").strip()
            if env_password:
                break
        if env_username and env_password:
            return env_username, env_password, "environment"

        file_credentials = self._load_file_credentials()
        file_values = file_credentials.get(ProviderId.ULTRALIBRARIAN.value, {})
        username = file_values.get("username", "").strip()
        password = file_values.get("password", "").strip()
        if username and password:
            return username, password, "file"

        return "", "", "none"

    def set_ultralibrarian_credentials(
        self,
        username: str,
        password: str,
        persist: bool = False,
    ) -> None:
        cleaned_username = username.strip()
        cleaned_password = password.strip()
        if not cleaned_username or not cleaned_password:
            raise ValueError("Ultra Librarian username and password are both required.")

        self._session_overrides[ProviderId.ULTRALIBRARIAN.value] = {
            "username": cleaned_username,
            "password": cleaned_password,
        }
        if persist:
            file_credentials = self._load_file_credentials()
            bucket = file_credentials.setdefault(ProviderId.ULTRALIBRARIAN.value, {})
            bucket["username"] = cleaned_username
            bucket["password"] = cleaned_password
            self._save_file_credentials(file_credentials)

    def clear_ultralibrarian_credentials(self, clear_persisted: bool = False) -> None:
        self._session_overrides.pop(ProviderId.ULTRALIBRARIAN.value, None)
        if clear_persisted:
            file_credentials = self._load_file_credentials()
            file_credentials.pop(ProviderId.ULTRALIBRARIAN.value, None)
            if file_credentials:
                self._save_file_credentials(file_credentials)
            elif self.credentials_file.is_file():
                self.credentials_file.unlink(missing_ok=True)

    def get_provider_status(self, provider: ProviderId) -> ProviderCredentialStatus:
        display_names = {
            ProviderId.MOUSER: "Mouser",
            ProviderId.DIGIKEY: "DigiKey",
            ProviderId.SAMACSYS: "SamacSys Component Search Engine",
            ProviderId.ULTRALIBRARIAN: "Ultra Librarian",
        }
        auth_type = PROVIDER_AUTH_TYPES[provider]

        if provider == ProviderId.ULTRALIBRARIAN:
            username, _password, source = self.get_ultralibrarian_credentials()
            configured = bool(username)
            masked = _mask_secret(username) if username else None
            return ProviderCredentialStatus(
                provider=provider.value,
                display_name=display_names[provider],
                auth_type=auth_type,
                configured=configured,
                source=source,
                masked_credential=masked,
                notes=(
                    "Register a free account at https://www.ultralibrarian.com/. "
                    f"Set {ULTRALIBRARIAN_USERNAME_ENV_VARS[0]} and "
                    f"{ULTRALIBRARIAN_PASSWORD_ENV_VARS[0]}, or use "
                    "set_ecad_provider_credentials(provider='ultralibrarian', ...)."
                ),
            )

        if provider == ProviderId.SAMACSYS:
            username, _password, source = self.get_samacsys_credentials()
            configured = bool(username)
            masked = _mask_secret(username) if username else None
            return ProviderCredentialStatus(
                provider=provider.value,
                display_name=display_names[provider],
                auth_type=auth_type,
                configured=configured,
                source=source,
                masked_credential=masked,
                notes=(
                    "Register a free account at https://componentsearchengine.com/register. "
                    f"Set {SAMACSYS_USERNAME_ENV_VARS[0]} and {SAMACSYS_PASSWORD_ENV_VARS[0]}, "
                    "or use set_ecad_provider_credentials(provider='samacsys', ...)."
                ),
            )

        if provider == ProviderId.MOUSER:
            api_key, source = self.get_mouser_api_key()
            configured = bool(api_key)
            masked = _mask_secret(api_key) if api_key else None
            notes = (
                "Register a Search API key at Mouser (My Account -> APIs). "
                f"Set {MOUSER_API_KEY_ENV_VARS[0]} or use set_component_provider_credentials."
            )
            return ProviderCredentialStatus(
                provider=provider.value,
                display_name=display_names[provider],
                auth_type=auth_type,
                configured=configured,
                source=source,
                masked_credential=masked,
                notes=notes,
            )

        digikey_values, source = self.get_digikey_credentials()
        configured = bool(digikey_values.get("access_token") or (
            digikey_values.get("client_id") and digikey_values.get("client_secret")
        ))
        masked = None
        token = digikey_values.get("access_token")
        if token:
            masked = _mask_secret(token)
        elif digikey_values.get("client_id"):
            masked = _mask_secret(digikey_values["client_id"])

        return ProviderCredentialStatus(
            provider=provider.value,
            display_name=display_names[provider],
            auth_type=auth_type,
            configured=configured,
            source=source,
            masked_credential=masked,
            notes=(
                "Register a Production or Sandbox app at https://developer.digikey.com/ "
                f"and subscribe to Product Information V4. Set {DIGIKEY_CLIENT_ID_ENV} and "
                f"{DIGIKEY_CLIENT_SECRET_ENV}, or use "
                "set_component_provider_credentials(provider='digikey', ...). "
                "Set DIGIKEY_SANDBOX=true to use the sandbox API host."
            ),
        )

    def list_provider_statuses(self) -> list[ProviderCredentialStatus]:
        return [self.get_provider_status(provider) for provider in ProviderId]


_default_store: CredentialStore | None = None


def get_credential_store() -> CredentialStore:
    global _default_store
    if _default_store is None:
        _default_store = CredentialStore()
    return _default_store
