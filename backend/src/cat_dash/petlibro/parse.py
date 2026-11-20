"""Turn raw Petlibro responses into Cat Dash models.

Field names come from reading the community integration, not from live data.
Everything here is defensive (missing keys -> None); run scripts/probe_petlibro.py
against the real feeder to confirm before trusting a field.
"""

from __future__ import annotations

import ast
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..models import FeederStatus, FeedEvent

FEED_SUCCESS = "GRAIN_OUTPUT_SUCCESS"


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


def device_name(device: dict) -> str:
    return str(
        _get(device, "name", "deviceName", "nickName")
        or _get(device, "productName")
        or device.get("deviceSn", "Feeder")
    )


def device_model(device: dict) -> str | None:
    value = _get(device, "productName", "productIdentifier")
    return str(value) if value else None


def feed_records(work_records: Any) -> list[dict]:
    """Flatten the work-record response (days -> records) to successful feeds."""
    flat: list[dict] = []
    for item in _as_list(work_records, "list", "records", "workRecords"):
        if not isinstance(item, dict):
            continue
        nested = item.get("workRecords")
        if isinstance(nested, list):
            flat.extend(r for r in nested if isinstance(r, dict))
        elif "recordTime" in item:
            flat.append(item)
    return [r for r in flat if r.get("type", FEED_SUCCESS) == FEED_SUCCESS and r.get("recordTime")]


def feed_events(device_id: str, work_records: Any) -> list[FeedEvent]:
    events = []
    for record in feed_records(work_records):
        timestamp = _ms(record.get("recordTime"))
        portions = _int(_get(record, "actualGrainNum", "grainNum"))
        if timestamp and portions is not None:
            events.append(FeedEvent(device_id=device_id, timestamp=timestamp, portions=portions))
    return sorted(events, key=lambda e: e.timestamp)


def _repeat_days(value: Any) -> set[int]:
    """Plan weekdays. Assumed ISO numbering (1=Mon..7=Sun); empty means every day.

    UNVERIFIED: confirm the numbering with a probe dump of a known schedule.
    """
    if isinstance(value, str):
        for loader in (json.loads, ast.literal_eval):
            try:
                value = loader(value)
                break
            except (ValueError, SyntaxError):
                continue
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
    if real_info.get("barnDoorError") is True:
        found.append("lid_blocked")
    # The reference integration flags a dispenser problem when grainOutletState is
    # False. UNVERIFIED against live data.
    if real_info.get("grainOutletState") is False:
        found.append("dispenser_blocked")
    message = data_real_info.get("exceptionMessage")
    if isinstance(message, str) and message.strip():
        lowered = message.lower()
        found.append(
            "rotor_stuck"
            if "rotor" in lowered or "stuck" in lowered
            else f"device_error: {message.strip()}"
        )
    return found


def feeder_status(
    device: dict,
    *,
    real_info: dict,
    data_real_info: dict,
    grain_status: dict,
    work_records: Any,
    plans: Any,
    now: datetime,
    timezone: str,
) -> FeederStatus:
    serial = str(device.get("deviceSn"))
    surplus = real_info.get("surplusGrain")
    events = feed_events(serial, work_records)
    last = events[-1] if events else None
    upcoming = next_feed(plans, now, timezone)
    online = real_info.get("online", device.get("online"))
    return FeederStatus(
        device_id=serial,
        name=device_name(device),
        model=device_model(device),
        online=online if isinstance(online, bool) else None,
        # surplusGrain True means "has food"; False means low.
        food_low=(not surplus) if isinstance(surplus, bool) else None,
        battery_percent=_float(real_info.get("electricQuantity")),
        battery_state=_get(real_info, "batteryState"),
        today_dispensed_portions=_int(grain_status.get("todayFeedingQuantity")),
        today_feed_count=_int(grain_status.get("todayFeedingTimes")),
        today_eat_count=_int(grain_status.get("todayEatingTimes")),
        last_feed_at=last.timestamp if last else None,
        last_feed_portions=last.portions if last else None,
        next_feed_at=upcoming[0] if upcoming else None,
        next_feed_portions=upcoming[1] if upcoming else None,
        desiccant_days_left=_float(
            _get(device, "remainingDesiccantDays") or _get(real_info, "remainingDesiccantDays")
        ),
        problems=problems(real_info, data_real_info),
        updated_at=now,
    )
