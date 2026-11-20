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
from pylitterbot.exceptions import LitterRobotLoginException

from ..hub import Hub
from ..models import LitterBoxStatus, LitterEvent
from ..store import Store

_LOGGER = logging.getLogger(__name__)
NAME = "litterrobot"
_WEIGHT_RE = re.compile(r":\s*([\d.]+)\s*lbs", re.IGNORECASE)

# How far back to backfill history on first start. A busy box logs ~60 entries/day
# (about 1,850 for 30 days), so the backfill limit must be generous.
BACKFILL = timedelta(days=30)
BACKFILL_LIMIT = 5000
INCREMENTAL_LIMIT = 1000
CLEAN_CYCLE_COMPLETE = "CCC"
CAT_DETECTED = "CD"
# Safety-net full refresh even when the websocket is healthy.
REFRESH_INTERVAL = timedelta(minutes=5)
# At most one drawer/litter snapshot per robot in this window (unless values change).
SNAPSHOT_MIN_INTERVAL = timedelta(minutes=10)
AUTH_RETRY = timedelta(minutes=30)
# After a pushed status change, wait a bit and then pull the new activity entries.
SYNC_DELAY = timedelta(seconds=20)


def _drawer_state(data: dict, full: bool) -> str | None:
    if full:
        return "full"
    if data.get("isDFIPartialFull") is True:
        return "partial"
    if "isDFIPartialFull" in data:
        return "ok"
    return None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def status_from_robot(robot: Any, now: datetime | None = None) -> LitterBoxStatus:
    """Map a pylitterbot LitterRobot4 to our model.

    Checked against a live LR4 on 2026-11-20: pylitterbot's `cycle_count` is the
    lifetime odometer (odometerCleanCycles); cycles since the drawer was emptied is
    the raw DFINumberOfCycles. DFILevelPercent can read 0 while isDFIPartialFull is
    true, so `waste_drawer_state` is the more trustworthy signal.
    """
    data = robot.to_dict() if hasattr(robot, "to_dict") else {}
    status = robot.status
    weight = robot.pet_weight
    full = robot.is_waste_drawer_full
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
        waste_drawer_full=full,
        waste_drawer_state=_drawer_state(data, full),
        litter_level_percent=float(robot.litter_level) if robot.litter_level is not None else None,
        litter_level_state=data.get("litterLevelState"),
        cat_weight_lbs=float(weight) if weight else None,
        cycles_since_drawer_reset=_int_or_none(data.get("DFINumberOfCycles")),
        lifetime_cycles=robot.cycle_count,
        sleeping=robot.is_sleeping,
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
        # device_id -> {"last_clean_cycle_at": dt, "last_cat_detected_at": dt}
        self._latest: dict[str, dict[str, datetime | None]] = {}
        self._last_code: dict[str, str | None] = {}
        self._sync_lock = asyncio.Lock()
        self._sync_task: asyncio.Task | None = None

    @property
    def robots(self) -> list[LitterRobot4]:
        return self._account.get_robots(LitterRobot4) if self._account else []

    def insight(self, device_id: str) -> Insight | None:
        return self._insights.get(device_id)

    async def start(self) -> None:
        self._tasks.append(asyncio.create_task(self._run(), name="litterrobot"))

    async def stop(self) -> None:
        if self._sync_task:
            self._tasks.append(self._sync_task)
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
            except LitterRobotLoginException as err:
                # Bad credentials won't fix themselves, and repeated failed logins can
                # lock the Whisker account: wait a long time between attempts.
                _LOGGER.error("Litter-Robot login rejected; retrying in 30 min: %s", err)
                self._hub.set_error(NAME, f"Login failed: {err}")
                await self._teardown_account()
                await asyncio.sleep(AUTH_RETRY.total_seconds())
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
            if latest := self._latest.get(status.device_id):
                status = status.model_copy(update=latest)
            self._hub.update_litter_box(status)
            previous = self._last_code.get(status.device_id, status.status_code)
            self._last_code[status.device_id] = status.status_code
            if previous != status.status_code:
                # A pushed state change (cat detected, cycle done...) means new activity.
                self._schedule_sync()
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

    def _schedule_sync(self) -> None:
        if self._sync_task and not self._sync_task.done():
            return
        self._sync_task = asyncio.get_running_loop().create_task(self._delayed_sync())
        self._sync_task.add_done_callback(_log_task_error)

    async def _delayed_sync(self) -> None:
        await asyncio.sleep(SYNC_DELAY.total_seconds())  # let Whisker log the activity
        await self.sync_history()

    async def sync_history(self) -> None:
        async with self._sync_lock:
            await self._sync_history()

    async def _sync_history(self) -> None:
        for robot in self.robots:
            device_id = str(robot.id)
            latest = await self._store.latest_litter_event(device_id)
            if latest:
                activities = await robot.get_activity_history(limit=INCREMENTAL_LIMIT, start=latest)
            else:
                activities = await robot.get_activity_history(
                    limit=BACKFILL_LIMIT, start=datetime.now(UTC) - BACKFILL
                )
            added = await self._store.add_litter_events(
                event_from_activity(device_id, a) for a in activities
            )
            _LOGGER.info("Litter-Robot %s: %d new activity rows", robot.name, added)
            self._latest[device_id] = {
                "last_clean_cycle_at": await self._store.latest_litter_event(
                    device_id, code=CLEAN_CYCLE_COMPLETE
                ),
                "last_cat_detected_at": await self._store.latest_litter_event(
                    device_id, code=CAT_DETECTED
                ),
            }
            self._insights[device_id] = await robot.get_insight(days=30)
            self._on_robot_update(robot)


def _log_task_error(task: asyncio.Task) -> None:
    if not task.cancelled() and task.exception():
        _LOGGER.error("Background store write failed", exc_info=task.exception())
