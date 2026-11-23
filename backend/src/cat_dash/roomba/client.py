"""The port (RoombaClient) and its real adapter (MQTT over TLS, port 8883).

The i7+ accepts ONE local connection at a time and pushes its state on connect, so the
adapter connects, collects until it has a usable state, and disconnects (leaving the
iRobot app free). Needs `aiomqtt` (MQTT 3.1.1 era; pinned <3), imported lazily.
"""

from __future__ import annotations

import asyncio
import json
import logging
import ssl
from typing import Any, Protocol

_LOGGER = logging.getLogger(__name__)
PORT = 8883


class RoombaError(Exception):
    pass


class RoombaAuthError(RoombaError):
    pass


class RoombaTimeout(RoombaError):
    pass


class RoombaClient(Protocol):
    async def fetch_state(self, timeout: float = 15.0) -> dict[str, Any]:
        """Return the merged `state.reported` dict. Raises RoombaError subclasses."""
        ...


def merge(into: dict, update: dict) -> None:
    """Deep-merge a partial `reported` update (the robot sends deltas)."""
    for key, value in update.items():
        if isinstance(value, dict) and isinstance(into.get(key), dict):
            merge(into[key], value)
        else:
            into[key] = value


def is_usable(reported: dict) -> bool:
    return "batPct" in reported and "cleanMissionStatus" in reported


def tls_context() -> ssl.SSLContext:
    # The robot has a self-signed cert and old TLS/cipher support.
    # UNVERIFIED on a real i7+: dorita980 uses AES128-SHA256 by default.
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        ctx.set_ciphers("DEFAULT:@SECLEVEL=0")
    except ssl.SSLError:  # pragma: no cover
        _LOGGER.warning("Could not relax cipher security level")
    return ctx


class MqttRoombaClient:
    def __init__(self, host: str, blid: str, password: str, *, port: int = PORT) -> None:
        self._host, self._blid, self._password, self._port = host, blid, password, port

    async def fetch_state(self, timeout: float = 15.0) -> dict[str, Any]:
        try:
            return await asyncio.wait_for(self._collect(), timeout)
        except TimeoutError as err:
            raise RoombaTimeout(f"No usable state from {self._host} within {timeout}s") from err

    async def _collect(self) -> dict[str, Any]:
        import aiomqtt  # lazy: optional until configured

        reported: dict[str, Any] = {}
        try:
            async with aiomqtt.Client(
                hostname=self._host,
                port=self._port,
                identifier=self._blid,
                username=self._blid,
                password=self._password,
                tls_context=tls_context(),
                tls_insecure=True,
            ) as client:
                await client.subscribe("#")
                async for message in client.messages:
                    try:
                        payload = json.loads(message.payload)
                    except (TypeError, ValueError):
                        continue
                    update = (payload.get("state") or {}).get("reported")
                    if isinstance(update, dict):
                        merge(reported, update)
                    if is_usable(reported):
                        return reported
        except aiomqtt.MqttCodeError as err:
            if getattr(err, "rc", None) in (4, 5, 134, 135):
                raise RoombaAuthError("Roomba rejected the BLID/password") from err
            raise RoombaError(str(err)) from err
        except aiomqtt.MqttError as err:
            raise RoombaError(str(err)) from err
        raise RoombaError("Roomba closed the connection before sending state")
