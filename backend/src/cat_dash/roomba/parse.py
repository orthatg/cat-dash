"""Turn the robot's merged `state.reported` dict into a RoombaStatus.

Field names follow dorita980 / roombapy and were checked against a real i7+ capture
(firmware lewis+22.52.10; see docs/roomba/NOTES.md). Everything is read defensively:
robots only publish the fields their firmware knows about.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .models import RoombaStatus, ScheduleEntry

SENSOR_GROUPS = ("bbrun", "bbchg3", "bbchg", "bbswitch", "bbsys", "bbpanic", "bbpause", "bbnav")

# Vendor weekday index 0 = Sunday (dorita980 README example). Convert to Python's Monday=0.
_VENDOR_TO_PY_WEEKDAY = [6, 0, 1, 2, 3, 4, 5]


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def error_text(code: int) -> str | None:
    # TODO: map codes once verified against roombapy's ErrorCode table / a real fault.
    return None if code == 0 else f"Robot error {code}"


def state_from(phase: str | None, error: int, not_ready: int) -> str:
    if error:
        return "error"
    return {
        "charge": "charging",
        "run": "cleaning",
        "hmUsrDock": "returning",
        "hmMidMsn": "returning",
        "hmPostMsn": "returning",
        "evac": "cleaning",
        "stuck": "stuck",
        "stop": "paused",
        "pause": "paused",
        "new": "idle",
    }.get(phase or "", "unknown")


def _entry(vendor_day: Any, hour: Any, minute: Any, enabled: bool) -> ScheduleEntry | None:
    day, h, m = _int(vendor_day), _int(hour), _int(minute)
    if day is None or h is None or m is None:
        return None
    if not (0 <= day < 7 and 0 <= h < 24 and 0 <= m < 60):
        return None
    return ScheduleEntry(
        weekday=_VENDOR_TO_PY_WEEKDAY[day], time=f"{h:02d}:{m:02d}", enabled=enabled
    )


def schedule_entries(raw: Any) -> list[ScheduleEntry]:
    """Weekly schedule as one entry per day and time.

    Newer firmware (the i7+ we tested) sends `cleanSchedule2`, a list of
    {enabled, start: {day: [0..6], hour, min}}; older firmware sends `cleanSchedule`,
    {cycle[7], h[7], m[7]}. A malformed schedule is dropped whole rather than half-shown.
    """
    if isinstance(raw, list):
        entries: list[ScheduleEntry] = []
        for item in raw:
            start = _dict(_dict(item).get("start"))
            days = start.get("day")
            if not isinstance(days, list):
                return []
            enabled = _dict(item).get("enabled") is True
            for day in days:
                entry = _entry(day, start.get("hour"), start.get("min"), enabled)
                if entry is None:
                    return []
                entries.append(entry)
        return sorted(entries, key=lambda e: (e.weekday, e.time))
    raw = _dict(raw)
    cycles, hours, minutes = raw.get("cycle"), raw.get("h"), raw.get("m")
    if not (isinstance(cycles, list) and isinstance(hours, list) and isinstance(minutes, list)):
        return []
    entries = []
    for i in range(min(7, len(cycles), len(hours), len(minutes))):
        entry = _entry(i, hours[i], minutes[i], cycles[i] != "none")
        if entry is None:
            return []
        entries.append(entry)
    return sorted(entries, key=lambda e: e.weekday)


def next_scheduled(entries: list[ScheduleEntry], now: datetime, tz: ZoneInfo) -> datetime | None:
    local = now.astimezone(tz)
    best: datetime | None = None
    for entry in entries:
        if not entry.enabled:
            continue
        hour, minute = (int(p) for p in entry.time.split(":"))
        days_ahead = (entry.weekday - local.weekday()) % 7
        candidate = (local + timedelta(days=days_ahead)).replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
        if candidate <= local:
            candidate += timedelta(days=7)
        if best is None or candidate < best:
            best = candidate
    return best.astimezone(UTC) if best else None


def parse_status(
    reported: dict, *, device_id: str, timezone: str, now: datetime | None = None
) -> RoombaStatus:
    now = now or datetime.now(UTC)
    mission = _dict(reported.get("cleanMissionStatus"))
    last_cmd = _dict(reported.get("lastCommand"))
    counters = _dict(reported.get("bbmssn"))
    signal = _dict(reported.get("signal"))
    bin_ = _dict(reported.get("bin"))
    error = _int(mission.get("error")) or 0
    not_ready = _int(mission.get("notReady")) or 0
    phase = _str(mission.get("phase"))
    schedule_raw = reported.get("cleanSchedule2")
    if not isinstance(schedule_raw, list):
        schedule_raw = reported.get("cleanSchedule")
    entries = schedule_entries(schedule_raw)
    problems = []
    if error:
        problems.append(error_text(error) or "Error")
    if bin_.get("full"):
        problems.append("Bin full")
    if bin_.get("present") is False:
        problems.append("Bin missing")
    if not_ready:
        problems.append(f"Not ready (code {not_ready})")
    cmd_time = _int(last_cmd.get("time"))
    started = _int(mission.get("mssnStrtTm"))
    minutes = _int(mission.get("mssnM"))
    return RoombaStatus(
        device_id=device_id,
        name=_str(reported.get("name")),
        model=_str(reported.get("sku")),
        software_version=_str(reported.get("softwareVer")),
        battery_percent=_int(reported.get("batPct")),
        state=state_from(phase, error, not_ready),
        phase=phase,
        cycle=_str(mission.get("cycle")),
        error_code=error,
        error_text=error_text(error),
        not_ready_code=not_ready,
        problems=problems,
        bin_present=_bool(bin_.get("present")),
        bin_full=_bool(bin_.get("full")),
        last_mission_started_at=datetime.fromtimestamp(started, tz=UTC) if started else None,
        last_command=_str(last_cmd.get("command")),
        last_command_at=datetime.fromtimestamp(cmd_time, tz=UTC) if cmd_time else None,
        last_command_initiator=_str(last_cmd.get("initiator")),
        last_mission_minutes=minutes or None,  # 0 = robot reset it, not "ran 0 min"
        last_mission_sqft=_int(mission.get("sqft")),
        mission_number=_int(mission.get("nMssn")),
        missions_total=_int(counters.get("nMssn")),
        missions_ok=_int(counters.get("nMssnOk")),
        missions_cancelled=_int(counters.get("nMssnC")),
        missions_failed=_int(counters.get("nMssnF")),
        next_scheduled_at=next_scheduled(entries, now, ZoneInfo(timezone)),
        schedule=entries,
        wifi_rssi=_int(signal.get("rssi")),
        wifi_snr=_int(signal.get("snr")),
        sensors={k: reported[k] for k in SENSOR_GROUPS if k in reported},
        fetched_at=now,
    )
