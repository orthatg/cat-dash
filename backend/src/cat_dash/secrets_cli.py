"""Manage Cat Dash device passwords in the macOS Keychain.

    uv run cat-dash-secrets set litterrobot     # prompts (hidden input)
    uv run cat-dash-secrets set petlibro
    uv run cat-dash-secrets check               # shows which are found (never the value)
    uv run cat-dash-secrets delete petlibro

The login email comes from backend/.env (CATDASH_LITTERROBOT_USERNAME /
CATDASH_PETLIBRO_EMAIL).
"""

from __future__ import annotations

import argparse
import getpass
import sys

from . import secrets
from .config import Settings


def _login(settings: Settings, integration: str) -> str | None:
    return (
        settings.litterrobot_username if integration == "litterrobot" else settings.petlibro_email
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cat-dash-secrets", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("set", "delete"):
        p = sub.add_parser(name)
        p.add_argument("integration", choices=secrets.INTEGRATIONS)
    sub.add_parser("check")
    args = parser.parse_args(argv)
    settings = Settings()

    if args.command == "check":
        for integration in secrets.INTEGRATIONS:
            login = _login(settings, integration)
            if not login:
                print(f"{integration}: login email not set in .env")
            elif secrets.get_password(integration, login):
                print(f"{integration}: password found in Keychain for {login}")
            else:
                print(f"{integration}: no Keychain password for {login}")
        return 0

    login = _login(settings, args.integration)
    if not login:
        print(f"Set the {args.integration} login email in backend/.env first.", file=sys.stderr)
        return 1

    if args.command == "set":
        password = getpass.getpass(f"{args.integration} password for {login}: ")
        if not password:
            print("Empty password; nothing saved.", file=sys.stderr)
            return 1
        if args.integration == "petlibro" and len(password) > 18:
            print("Warning: Petlibro is reported to reject passwords over 18 characters.")
        secrets.set_password(args.integration, login, password)
        print(f"Saved to Keychain (service 'cat-dash', account '{args.integration}:{login}').")
        return 0

    if secrets.delete_password(args.integration, login):
        print("Deleted.")
        return 0
    print("Nothing to delete.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
