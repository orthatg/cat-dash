"""On-demand status with a short cache so page loads don't hammer the robot."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime

from .client import RoombaClient
from .models import RoombaStatus
from .parse import parse_status


class RoombaService:
    def __init__(
        self,
        client: RoombaClient,
        *,
        device_id: str,
        timezone: str,
        cache_seconds: float = 30.0,
        timeout: float = 15.0,
    ) -> None:
        self._client, self._device_id, self._tz = client, device_id, timezone
        self._cache_seconds, self._timeout = cache_seconds, timeout
        self._lock = asyncio.Lock()  # the robot allows one connection: serialize
        self._cached: tuple[float, RoombaStatus] | None = None

    async def status(self, *, refresh: bool = False) -> RoombaStatus:
        async with self._lock:
            if self._cached and not refresh:
                age = time.monotonic() - self._cached[0]
                if age < self._cache_seconds:
                    return self._cached[1]
            reported = await self._client.fetch_state(self._timeout)
            status = parse_status(
                reported, device_id=self._device_id, timezone=self._tz, now=datetime.now(UTC)
            )
            self._cached = (time.monotonic(), status)
            return status
