"""API key lookup. Only the agent service reads the key; it never reaches the UI."""

from __future__ import annotations

import os

KEYRING_SERVICE = "mavmind"
KEYRING_USER = "anthropic_api_key"


def find_api_key() -> str | None:
    """ANTHROPIC_API_KEY, else the OS keychain (Windows Credential Manager, macOS Keychain, Secret Service)."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    try:
        import keyring  # optional extra: pip install mavmind-agent[keyring]
    except ImportError:
        return None
    try:
        return keyring.get_password(KEYRING_SERVICE, KEYRING_USER)
    except Exception:  # noqa: BLE001 - no keyring backend available
        return None


def store_api_key(key: str) -> None:
    import keyring

    keyring.set_password(KEYRING_SERVICE, KEYRING_USER, key)
