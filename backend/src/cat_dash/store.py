"""SQLite history store (litter events, drawer snapshots, feed events)."""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from .models import FeedEvent, LitterBoxStatus, LitterEvent

_SCHEMA = """
CREATE TABLE IF NOT EXISTS litter_events (
    device_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    code TEXT,
    text TEXT NOT NULL,
    cat_weight_lbs REAL,
    PRIMARY KEY (device_id, ts, text)
);
CREATE TABLE IF NOT EXISTS litter_snapshots (
    device_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    waste_drawer_percent REAL,
    litter_level_percent REAL,
    cat_weight_lbs REAL,
    PRIMARY KEY (device_id, ts)
);
CREATE TABLE IF NOT EXISTS feed_events (
    device_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    portions INTEGER NOT NULL,
    PRIMARY KEY (device_id, ts)
);
"""


def _ts(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


class Store:
    """Thin async wrapper over a single sqlite3 connection."""

    def __init__(self, path: Path | str) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._lock = asyncio.Lock()

    async def _run(self, fn, *args):
        async with self._lock:
            return await asyncio.to_thread(fn, *args)

    def close(self) -> None:
        self._conn.close()

    # --- litter events ---
    async def add_litter_events(self, events: Iterable[LitterEvent]) -> int:
        rows = [(e.device_id, _ts(e.timestamp), e.code, e.text, e.cat_weight_lbs) for e in events]

        def write() -> int:
            with self._conn:
                cur = self._conn.executemany(
                    "INSERT OR IGNORE INTO litter_events VALUES (?, ?, ?, ?, ?)", rows
                )
            return cur.rowcount

        return await self._run(write)

    async def latest_litter_event(self, device_id: str) -> datetime | None:
        def read():
            return self._conn.execute(
                "SELECT MAX(ts) FROM litter_events WHERE device_id = ?", (device_id,)
            ).fetchone()[0]

        value = await self._run(read)
        return _dt(value) if value else None

    async def litter_events(self, device_id: str, since: datetime) -> list[LitterEvent]:
        def read():
            return self._conn.execute(
                "SELECT device_id, ts, code, text, cat_weight_lbs FROM litter_events"
                " WHERE device_id = ? AND ts >= ? ORDER BY ts",
                (device_id, _ts(since)),
            ).fetchall()

        return [
            LitterEvent(
                device_id=r[0], timestamp=_dt(r[1]), code=r[2], text=r[3], cat_weight_lbs=r[4]
            )
            for r in await self._run(read)
        ]

    # --- litter snapshots (drawer level over time) ---
    async def add_litter_snapshot(self, status: LitterBoxStatus) -> None:
        row = (
            status.device_id,
            _ts(status.updated_at),
            status.waste_drawer_percent,
            status.litter_level_percent,
            status.cat_weight_lbs,
        )

        def write() -> None:
            with self._conn:
                self._conn.execute(
                    "INSERT OR REPLACE INTO litter_snapshots VALUES (?, ?, ?, ?, ?)", row
                )

        await self._run(write)

    async def litter_snapshots(self, device_id: str, since: datetime) -> list[dict]:
        def read():
            return self._conn.execute(
                "SELECT ts, waste_drawer_percent, litter_level_percent, cat_weight_lbs"
                " FROM litter_snapshots WHERE device_id = ? AND ts >= ? ORDER BY ts",
                (device_id, _ts(since)),
            ).fetchall()

        return [
            {
                "timestamp": r[0],
                "waste_drawer_percent": r[1],
                "litter_level_percent": r[2],
                "cat_weight_lbs": r[3],
            }
            for r in await self._run(read)
        ]

    # --- feed events ---
    async def add_feed_events(self, events: Iterable[FeedEvent]) -> int:
        rows = [(e.device_id, _ts(e.timestamp), e.portions) for e in events]

        def write() -> int:
            with self._conn:
                cur = self._conn.executemany(
                    "INSERT OR IGNORE INTO feed_events VALUES (?, ?, ?)", rows
                )
            return cur.rowcount

        return await self._run(write)

    async def feed_events(self, device_id: str, since: datetime) -> list[FeedEvent]:
        def read():
            return self._conn.execute(
                "SELECT device_id, ts, portions FROM feed_events"
                " WHERE device_id = ? AND ts >= ? ORDER BY ts",
                (device_id, _ts(since)),
            ).fetchall()

        return [
            FeedEvent(device_id=r[0], timestamp=_dt(r[1]), portions=r[2])
            for r in await self._run(read)
        ]
