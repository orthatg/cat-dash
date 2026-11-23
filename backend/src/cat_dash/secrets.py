"""Device passwords stored in the macOS Keychain (via `keyring`).

Each entry is a generic password with service "cat-dash" and account
"<integration>:<login email>", e.g. "petlibro:me@example.com". They show up in
Keychain Access under the name "cat-dash".
"""

from __future__ import annotations

import logging

import keyring
from keyring.errors import KeyringError

_LOGGER = logging.getLogger(__name__)

SERVICE = "cat-dash"
INTEGRATIONS = ("litterrobot", "petlibro", "roomba")


def _account(integration: str, login: str) -> str:
    if integration not in INTEGRATIONS:
        raise ValueError(f"Unknown integration {integration!r}; expected one of {INTEGRATIONS}")
    return f"{integration}:{login}"


def get_password(integration: str, login: str | None) -> str | None:
    if not login:
        return None
    try:
        return keyring.get_password(SERVICE, _account(integration, login))
    except KeyringError as err:
        _LOGGER.warning("Could not read %s password from the Keychain: %s", integration, err)
        return None


def set_password(integration: str, login: str, password: str) -> None:
    keyring.set_password(SERVICE, _account(integration, login), password)


def delete_password(integration: str, login: str) -> bool:
    try:
        keyring.delete_password(SERVICE, _account(integration, login))
    except keyring.errors.PasswordDeleteError:
        return False
    return True
