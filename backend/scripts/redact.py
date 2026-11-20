"""Shared helper for probe scripts: scrub secrets/PII before writing dumps."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SENSITIVE = {
    "token",
    "accesstoken",
    "idtoken",
    "refreshtoken",
    "password",
    "email",
    "userid",
    "userEmail",
    "ssid",
    "wifissid",
    "mac",
    "macaddress",
    "ip",
    "phone",
    "address",
    "latitude",
    "longitude",
    "tutkinfo",
    "cameraauthinfo",
    "uid",
}
SENSITIVE = {key.lower() for key in SENSITIVE}


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: ("<redacted>" if k.lower() in SENSITIVE else redact(v)) for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def dump(out_dir: Path, name: str, data: Any) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{name}.json"
    path.write_text(json.dumps(redact(data), indent=2, default=str))
    print(f"  wrote {path}")
