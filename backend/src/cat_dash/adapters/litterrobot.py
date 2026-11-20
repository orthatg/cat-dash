"""Litter-Robot 4 integration via pylitterbot.

Live status is pushed over pylitterbot's GraphQL websocket subscription.
History (activity log) is pulled on a slow timer, and a periodic refresh() guards
against a silently stale websocket.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pylitterbot import Account, LitterRobot4
from pylitterbot.activity import Activity, Insight
from pylitterbot.enums import LitterBoxStatus as LRStatus
from pylitterbot.event import EVENT_UPDATE

from ..hub import Hub
from ..models import LitterBoxStatus, LitterEvent
from ..store import Store

_LOGGER = logging.getLogger(__name__)
NAME = "litterrobot"
_WEIGHT_RE = re.compile(r":\s*([\d.]+)\s*lbs", re.IGNORECASE)

# How far back to backfill history on first start.
BACKFILL = timedelta(days=30)
# Safety-net full refresh even when the websocket is healthy.
REFRESH_INTERVAL = timedelta(minutes=5)
# At most one drawer/litter snapshot per robot in this window (unless values change).
SNAPSHOT_MIN_INTERVAL = timedelta(minutes=10)


def status_from_robot(robot: Any, now: datetime | None = None) -> LitterBoxStatus:
    """Map a pylitterbot LitterRobot4 to our model."""
    status = robot.status
    weight = robot.pet_weight
    return LitterBoxStatus(
        device_id=str(robot.id),
        name=robot.name,
        model=robot.model,
        serial=robot.serial,
        online=robot.is_online,
        powered_on=robot.is_on,
        status_code=robot.status_code,
        status_text=getattr(status, "text", None),
        waste_drawer_percent=float(robot.waste_drawer_level),
        waste_drawer_full=robot.is_waste_drawer_full,
        litter_level_percent=float(robot.litter_level) if robot.litter_level is not None else None,
        cat_weight_lbs=float(weight) if weight else None,
        cycles_since_drawer_reset=robot.cycle_count,
        sleeping=robot.is_sleeping,
        last_seen=robot.last_seen,
        updated_at=now or datetime.now(UTC),
    )


def event_from_activity(device_id: str, activity: Activity) -> LitterEvent:
    action = activity.action
    if isinstance(action, LRStatus):
        code, text = action.value, action.text or str(action.value)
    else:
        code, text = None, str(action)
    weight = None
    if match := _WEIGHT_RE.search(text):
        weight = float(match.group(1))
    timestamp = activity.timestamp
    if not isinstance(timestamp, datetime):  # date-only entries
        timestamp = datetime(timestamp.year, timestamp.month, timestamp.day, tzinfo=UTC)
    return LitterEvent(
        device_id=device_id, timestamp=timestamp, code=code, text=text, cat_weight_lbs=weight
    )


class TokenFile:
    """Persists Cognito tokens so restarts don't re-send the password."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict | None:
        try:
            return json.loads(self.path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    def save(self, tokens: dict | None) -> None:
        if not tokens:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(tokens))
        self.path.chmod(0o600)


class LitterRobotAdapter:
    def __init__(
        self,
        hub: Hub,
        store: Store,
        username: str,
        password: str,
        token_file: TokenFile,
        history_poll_seconds: int = 900,
        account_factory: Callable[..., Account] = Account,
    ) -> None:
        self._hub = hub
        self._store = store
        self._username = username
        self._password = password
        self._tokens = token_file
        self._history_poll = history_poll_seconds
        self._account_factory = account_factory
        self._account: Account | None = None
        self._unsubscribers: list[Callable[[], None]] = []
        self._tasks: list[asyncio.Task] = []
        self._last_snapshot: dict[str, tuple[datetime, tuple]] = {}
        self._insights: dict[str, Insight] = {}

    @property
    def robots(self) -> list[LitterRobot4]:
        return self._account.get_robots(LitterRobot4) if self._account else []

    def insight(self, device_id: str) -> Insight | None:
        return self._insights.get(device_id)

    async def start(self) -> None:
        self._tasks.append(asyncio.create_task(self._run(), name="litterrobot"))

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._tasks.clear()
        for unsubscribe in self._unsubscribers:
            unsubscribe()
        self._unsubscribers.clear()
        if self._account:
            with contextlib.suppress(Exception):
                await self._account.disconnect()
            self._account = None

    async def _run(self) -> None:
        delay = 30
        while True:
            try:
                await self._connect()
                self._hub.set_error(NAME, None)
                delay = 30
                await self._maintain()
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001 - keep the service alive
                _LOGGER.warning("Litter-Robot error, retrying in %ss: %s", delay, err)
                self._hub.set_error(NAME, str(err) or type(err).__name__)
                await self._teardown_account()
                await asyncio.sleep(delay)
                delay = min(delay * 2, 900)

    async def _connect(self) -> None:
        self._account = self._account_factory(
            token=self._tokens.load(),
            token_update_callback=self._tokens.save,
            robot_types=[LitterRobot4],
        )
        await self._account.connect(
            username=self._username,
            password=self._password,
            load_robots=True,
            subscribe_for_updates=True,
        )
        self._tokens.save(self._account.session.tokens)
        robots = self.robots
        _LOGGER.info("Litter-Robot connected: %d robot(s)", len(robots))
        for robot in robots:
            self._unsubscribers.append(
                robot.on(EVENT_UPDATE, lambda r=robot: self._on_robot_update(r))
            )
            self._on_robot_update(robot)

    async def _teardown_account(self) -> None:
        for unsubscribe in self._unsubscribers:
            unsubscribe()
        self._unsubscribers.clear()
        if self._account:
            with contextlib.suppress(Exception):
                await self._account.disconnect()
        self._account = None

    async def _maintain(self) -> None:
        """Pull history now and on a timer; refresh state as a websocket safety net."""
        last_history = datetime.min.replace(tzinfo=UTC)
        while True:
            now = datetime.now(UTC)
            if now - last_history >= timedelta(seconds=self._history_poll):
                await self.sync_history()
                last_history = now
            await asyncio.sleep(REFRESH_INTERVAL.total_seconds())
            for robot in self.robots:
                await robot.refresh()  # emits EVENT_UPDATE -> _on_robot_update

    def _on_robot_update(self, robot: LitterRobot4) -> None:
        # Called synchronously by pylitterbot; it swallows exceptions, so log our own.
        try:
            status = status_from_robot(robot)
            self._hub.update_litter_box(status)
            self._maybe_snapshot(status)
        except Exception:
            _LOGGER.exception("Failed to process Litter-Robot update")

    def _maybe_snapshot(self, status: LitterBoxStatus) -> None:
        values = (status.waste_drawer_percent, status.litter_level_percent, status.cat_weight_lbs)
        previous = self._last_snapshot.get(status.device_id)
        if (
            previous
            and previous[1] == values
            and (status.updated_at - previous[0] < SNAPSHOT_MIN_INTERVAL)
        ):
            return
        self._last_snapshot[status.device_id] = (status.updated_at, values)
        task = asyncio.get_running_loop().create_task(self._store.add_litter_snapshot(status))
        task.add_done_callback(_log_task_error)

    async def sync_history(self) -> None:
        for robot in self.robots:
            device_id = str(robot.id)
            latest = await self._store.latest_litter_event(device_id)
            start = latest or (datetime.now(UTC) - BACKFILL)
            activities = await robot.get_activity_history(limit=1000, start=start)
            added = await self._store.add_litter_events(
                event_from_activity(device_id, a) for a in activities
            )
            _LOGGER.debug("Litter-Robot %s: %d new activity rows", robot.name, added)
            self._insights[device_id] = await robot.get_insight(days=30)


def _log_task_error(task: asyncio.Task) -> None:
    if not task.cancelled() and task.exception():
        _LOGGER.error("Background store write failed", exc_info=task.exception())
