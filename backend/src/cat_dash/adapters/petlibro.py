"""Petlibro feeder integration (polling; the API has no push channel)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ..hub import Hub
from ..petlibro import PetlibroAuthError, PetlibroClient, parse
from ..store import Store

_LOGGER = logging.getLogger(__name__)
NAME = "petlibro"
DEVICE_LIST_INTERVAL = timedelta(hours=1)
# First run pulls this much history (feeds + cat visits); later polls only fetch
# records since the last one seen, with a small overlap (duplicates are ignored).
BACKFILL = timedelta(days=30)
OVERLAP = timedelta(minutes=10)


class PetlibroAdapter:
    def __init__(
        self,
        hub: Hub,
        store: Store,
        client: PetlibroClient,
        *,
        timezone: str,
        poll_seconds: int = 60,
        token_path: Path | None = None,
    ) -> None:
        self._hub = hub
        self._store = store
        self._client = client
        self._timezone = timezone
        self._poll = max(30, poll_seconds)  # don't hammer an unofficial API
        self._token_path = token_path
        self._devices: list[dict] = []
        self._devices_at: datetime | None = None
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._token_path and self._token_path.exists():
            self._client.token = self._token_path.read_text().strip() or None
        self._task = asyncio.create_task(self._run(), name="petlibro")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
        await self._client.aclose()

    async def _run(self) -> None:
        delay = self._poll
        while True:
            try:
                await self.poll_once()
                self._hub.set_error(NAME, None)
                delay = self._poll
            except asyncio.CancelledError:
                raise
            except PetlibroAuthError as err:
                # Wrong credentials won't fix themselves; back off hard.
                _LOGGER.error("Petlibro auth failed: %s", err)
                self._hub.set_error(NAME, f"Login failed: {err}")
                delay = 1800
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Petlibro poll failed, retrying in %ss: %s", delay, err)
                self._hub.set_error(NAME, str(err) or type(err).__name__)
                delay = min(delay * 2, 900)
            await asyncio.sleep(delay)

    async def poll_once(self) -> None:
        now = datetime.now(UTC)
        if self._devices_at is None or now - self._devices_at > DEVICE_LIST_INTERVAL:
            self._devices = await self._client.list_devices()
            self._devices_at = now
            self._save_token()
            _LOGGER.info("Petlibro devices: %d", len(self._devices))
        for device in self._devices:
            if device.get("deviceSn"):
                await self._poll_device(device, now)

    async def _poll_device(self, device: dict, now: datetime) -> None:
        serial = str(device["deviceSn"])
        cursor_key = f"petlibro:{serial}:records_until"
        cursor = await self._store.get_state(cursor_key)
        since = datetime.fromisoformat(cursor) - OVERLAP if cursor else now - BACKFILL
        calls = {
            "real_info": self._client.real_info(serial),
            "data_real_info": self._client.data_real_info(serial),
            "grain_status": self._client.grain_status(serial),
            "records": self._client.records_between(serial, since, now),
            "plans": self._client.feeding_plans(serial),
        }
        results = await asyncio.gather(*calls.values(), return_exceptions=True)
        data: dict[str, Any] = {}
        for key, result in zip(calls, results, strict=True):
            if isinstance(result, PetlibroAuthError):
                raise result
            if isinstance(result, Exception):
                _LOGGER.warning("Petlibro %s %s failed: %s", serial, key, result)
                result = None
            data[key] = result
        if data["real_info"] is None:
            raise RuntimeError(f"Petlibro realInfo unavailable for {serial}")

        records = data["records"]
        if records is not None:
            await self._store.add_feed_events(parse.feed_events(serial, records))
            await self._store.add_pet_visits(parse.pet_visits(serial, records))
            newest = max(
                (int(r["recordTime"]) for r in records if r.get("recordTime")), default=None
            )
            if newest:
                await self._store.set_state(
                    cursor_key, datetime.fromtimestamp(newest / 1000, tz=UTC).isoformat()
                )
            elif not cursor:
                await self._store.set_state(cursor_key, now.isoformat())

        status = parse.feeder_status(
            device,
            real_info=data["real_info"] or {},
            data_real_info=data["data_real_info"] or {},
            grain_status=data["grain_status"] or {},
            records=records or [],
            plans=data["plans"],
            now=now,
            timezone=self._timezone,
            last_feed=await self._store.latest_feed_event(serial),
        )
        self._hub.update_feeder(status)

    def _save_token(self) -> None:
        if self._token_path and self._client.token:
            self._token_path.parent.mkdir(parents=True, exist_ok=True)
            self._token_path.write_text(self._client.token)
            self._token_path.chmod(0o600)
