"""Turn raw Petlibro responses into Cat Dash models.

Field names were confirmed against a live One RFID (PLAF301) on 2026-11-20.
Redacted sample responses live in tests/fixtures/petlibro/. Parsing stays
defensive (missing keys -> None) because the API is unofficial.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..models import FeederStatus, FeedEvent, PetVisit

FEED_SUCCESS = "GRAIN_OUTPUT_SUCCESS"
DETECTION = "DETECTION_EVENT"
_DURATION_RE = re.compile(r"^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$")


def _get(mapping: Any, *keys: str) -> Any:
    if not isinstance(mapping, dict):
        return None
    for key in keys:
        if mapping.get(key) is not None:
            return mapping[key]
    return None


def _int(value: Any) -> int | None:
    try:
        return int(value) if value is not None and not isinstance(value, bool) else None
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    try:
        return float(value) if value is not None and not isinstance(value, bool) else None
    except (TypeError, ValueError):
        return None


def _ms(value: Any) -> datetime | None:
    millis = _int(value)
    return datetime.fromtimestamp(millis / 1000, tz=UTC) if millis else None


def _as_list(data: Any, *keys: str) -> list:
    """Accept either a bare list or a dict wrapping one under a known key."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in keys:
            if isinstance(data.get(key), list):
                return data[key]
    return []


def _params(record: dict) -> dict:
    raw = record.get("params")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            value = json.loads(raw)
        except ValueError:
            return {}
        return value if isinstance(value, dict) else {}
    return {}


def parse_duration(value: Any) -> int | None:
    """'15s' / '02m05s' / '1h02m05s' -> seconds."""
    if not isinstance(value, str):
        return None
    match = _DURATION_RE.match(value.strip())
    if not match or not any(match.groups()):
        return None
    hours, minutes, seconds = (int(g) if g else 0 for g in match.groups())
    return hours * 3600 + minutes * 60 + seconds


def device_name(device: dict) -> str:
    return str(
        _get(device, "name", "deviceName", "nickName")
        or _get(device, "productName")
        or device.get("deviceSn", "Feeder")
    )


def device_model(device: dict) -> str | None:
    value = _get(device, "productName", "productIdentifier")
    return str(value) if value else None


def flatten_records(work_records: Any) -> list[dict]:
    """The work-record response is days -> {"recordTime": "2026/11/20", "workRecords": [...]}.

    Note: the API ignores the request's `type` filter and returns every kind of record
    (feeds, pet visits, outlet events...), newest first.
    """
    flat: list[dict] = []
    for item in _as_list(work_records, "list", "records", "workRecords"):
        if not isinstance(item, dict):
            continue
        nested = item.get("workRecords")
        if isinstance(nested, list):
            flat.extend(r for r in nested if isinstance(r, dict))
        elif _int(item.get("recordTime")):
            flat.append(item)
    return flat


def feed_events(device_id: str, records: list[dict]) -> list[FeedEvent]:
    events = []
    for record in records:
        if record.get("type") != FEED_SUCCESS:
            continue
        timestamp = _ms(record.get("recordTime"))
        portions = _int(record.get("actualGrainNum"))
        if portions is None:
            portions = _int(_params(record).get("actualGrainNum"))
        if timestamp and portions is not None:
            events.append(FeedEvent(device_id=device_id, timestamp=timestamp, portions=portions))
    return sorted(events, key=lambda e: e.timestamp)


def pet_visits(device_id: str, records: list[dict]) -> list[PetVisit]:
    """RFID eating visits, e.g. "Whiskers came to eat and ate for 02m05s"."""
    visits = []
    for record in records:
        if record.get("type") != DETECTION:
            continue
        timestamp = _ms(record.get("recordTime"))
        if not timestamp:
            continue
        visits.append(
            PetVisit(
                device_id=device_id,
                timestamp=timestamp,
                pet_id=_int(record.get("petId")),
                pet_name=record.get("petName") or _params(record).get("petName"),
                seconds=parse_duration(_params(record).get("seconds")),
                event_type=record.get("eventType"),
            )
        )
    return sorted(visits, key=lambda v: v.timestamp)


def _repeat_days(value: Any) -> set[int]:
    """Plan weekdays, ISO numbering (1=Mon..7=Sun), e.g. "[7,1,2,3,4,5,6]".

    Confirmed: work-record days report dayOfWeek=5 for a Friday. Empty = every day.
    """
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            value = []
    if isinstance(value, int):
        value = [value]
    days = {d for d in (_int(v) for v in (value or [])) if d and 1 <= d <= 7}
    return days or set(range(1, 8))


def next_feed(plans: Any, now: datetime, default_tz: str) -> tuple[datetime, int | None] | None:
    best: tuple[datetime, int | None] | None = None
    for plan in _as_list(plans, "list", "plans", "feedingPlans"):
        if not isinstance(plan, dict) or plan.get("enable") is False:
            continue
        time_str = _get(plan, "executionTime", "time")
        if not isinstance(time_str, str) or ":" not in time_str:
            continue
        try:
            hour, minute = (int(p) for p in time_str.split(":")[:2])
        except ValueError:
            continue
        try:
            tz = ZoneInfo(plan.get("timezone") or default_tz)
        except (ZoneInfoNotFoundError, ValueError):
            tz = ZoneInfo(default_tz)
        days = _repeat_days(plan.get("repeatDay"))
        local_now = now.astimezone(tz)
        for offset in range(8):
            day = local_now.date() + timedelta(days=offset)
            if day.isoweekday() not in days:
                continue
            candidate = datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz)
            if candidate > local_now:
                if best is None or candidate < best[0]:
                    best = (candidate.astimezone(UTC), _int(plan.get("grainNum")))
                break
    return best


def problems(real_info: dict, data_real_info: dict) -> list[str]:
    found = []
    if real_info.get("barnDoorError") is True or real_info.get("doorErrorState") not in (
        None,
        "NORMAL",
    ):
        found.append("lid_blocked")
    # Live data: grainOutletState is True on a working feeder; the API also logs
    # GRAIN_OUTLET_BLOCK_REMOVED records, so False is treated as blocked.
    if real_info.get("grainOutletState") is False:
        found.append("dispenser_blocked")
    if real_info.get("deviceStoppedWorking") is True:
        found.append("stopped_working")
    message = data_real_info.get("exceptionMessage")
    if isinstance(message, str) and message.strip():
        lowered = message.lower()
        found.append(
            "rotor_stuck"
            if "rotor" in lowered or "stuck" in lowered
            else f"device_error: {message.strip()}"
        )
    return found


def _battery_percent(device: dict, real_info: dict) -> float | None:
    """The feeder reports electricQuantity=0 when it doesn't report a percentage
    (enableBatteryPercent False, e.g. running on the power adapter); show nothing then."""
    value = _float(real_info.get("electricQuantity"))
    enabled = _get(device, "enableBatteryPercent")
    if value is None or (value == 0 and enabled is not True):
        return None
    return value


def feeder_status(
    device: dict,
    *,
    real_info: dict,
    data_real_info: dict,
    grain_status: dict,
    records: list[dict],
    plans: Any,
    now: datetime,
    timezone: str,
    last_feed: FeedEvent | None = None,
) -> FeederStatus:
    """`last_feed` (e.g. from stored history) wins over what's in `records`."""
    serial = str(device.get("deviceSn"))
    surplus = real_info.get("surplusGrain")
    if last_feed is None:
        events = feed_events(serial, records)
        last_feed = events[-1] if events else None
    upcoming = next_feed(plans, now, timezone)
    online = real_info.get("online", device.get("online"))
    desiccant_days = _get(real_info, "remainingDesiccantDays")
    if desiccant_days is None:
        desiccant_days = _get(data_real_info, "remainingDesiccantDays")
    return FeederStatus(
        device_id=serial,
        name=device_name(device),
        model=device_model(device),
        online=online if isinstance(online, bool) else None,
        # surplusGrain True means "has food"; False means low.
        food_low=(not surplus) if isinstance(surplus, bool) else None,
        battery_percent=_battery_percent(device, real_info),
        battery_state=_get(real_info, "batteryState"),
        today_dispensed_portions=_int(grain_status.get("todayFeedingQuantity")),
        today_feed_count=_int(grain_status.get("todayFeedingTimes")),
        today_eat_count=_int(grain_status.get("todayEatingTimes")),
        today_eat_seconds=_int(grain_status.get("petEatingTime")),
        last_feed_at=last_feed.timestamp if last_feed else None,
        last_feed_portions=last_feed.portions if last_feed else None,
        next_feed_at=upcoming[0] if upcoming else None,
        next_feed_portions=upcoming[1] if upcoming else None,
        # Negative = overdue by that many days.
        desiccant_days_left=_float(desiccant_days),
        desiccant_state=_get(data_real_info, "desiccantState") or _get(device, "desiccantState"),
        problems=problems(real_info, data_real_info),
        updated_at=now,
    )
