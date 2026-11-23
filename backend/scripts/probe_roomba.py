"""Fetch the Roomba's state once over local MQTT, dump it (redacted) and print the parsed status.

    uv run python scripts/probe_roomba.py

Output goes to data/probe/roomba/ (git-ignored). Close the iRobot app first: the robot
accepts one local connection at a time.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from redact import dump, redact

from cat_dash.config import Settings
from cat_dash.roomba import MqttRoombaClient, RoombaError
from cat_dash.roomba.parse import parse_status

OUT = Path("data/probe/roomba")
# Network/identity fields in the robot's state, on top of redact.SENSITIVE.
EXTRA = {
    "netinfo",
    "wifistat",
    "hostname",
    "blid",
    "bssid",
    "dns1",
    "dns2",
    "gw",
    "mask",
    "addr",
    "robotname",
    "name",
    "uid",
    "deviceid",
    "hwpartsrev",  # contains the Wi-Fi MAC and board serials
    "wlan0hwaddr",
    "mobblid",
    "pmaps",
    "missionid",
    "batinfo",  # battery serials
    "svcendpoints",
    "batterytype",  # battery part code
    "cmdstr",  # embeds map ids
    "dock",  # dock id / serial-ish
}


def scrub(value):
    value = redact(value)
    if isinstance(value, dict):
        return {k: ("<redacted>" if k.lower() in EXTRA else scrub(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    return value


async def main() -> int:
    s = Settings()
    if not s.roomba_configured:
        print("Roomba not configured: see backend/.env.example")
        return 1
    client = MqttRoombaClient(s.roomba_host, s.roomba_blid, s.roomba_password_value())
    try:
        reported = await client.fetch_state(timeout=30)
    except RoombaError as err:
        print(f"{type(err).__name__}: {err}")
        return 2
    print("top-level fields:", ", ".join(sorted(reported)))
    dump(OUT, "reported", scrub(reported))
    status = parse_status(reported, device_id="<blid>", timezone=s.timezone)
    print(status.model_dump_json(indent=2, exclude={"device_id"}))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
