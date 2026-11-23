"""Parsing and API output for a real (redacted) i7+ capture, plus cleanSchedule2 edge cases."""

import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from cat_dash.app import create_app
from cat_dash.config import Settings
from cat_dash.hub import Hub
from cat_dash.roomba import RoombaService
from cat_dash.roomba.parse import parse_status, schedule_entries
from cat_dash.store import Store

REAL = json.loads((Path(__file__).parent / "fixtures/roomba/real_i7_reported.json").read_text())
CHI = "America/Chicago"
# Monday 2026-11-23 06:00 CST, before the 08:00 schedule.
BEFORE = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)


def parse(reported=None, *, now=BEFORE, tz=CHI):
    data = copy.deepcopy(REAL if reported is None else reported)
    return parse_status(data, device_id="BLID1", timezone=tz, now=now)


def with_sched2(entries):
    data = copy.deepcopy(REAL)
    data["cleanSchedule2"] = entries
    return data


def entry(days, hour=8, minute=0, enabled=True):
    return {"enabled": enabled, "type": 0, "start": {"day": days, "hour": hour, "min": minute}}


def test_real_scalar_fields():
    s = parse()
    assert s.battery_percent == 100
    assert s.phase == "charge" and s.state == "charging"
    assert s.cycle == "none"
    assert s.error_code == 0 and s.error_text is None
    assert s.not_ready_code == 0 and s.problems == []
    assert s.bin_present is True and s.bin_full is False
    assert s.model == "i755020"
    assert s.mission_number == 779


def test_real_counters():
    s = parse()
    assert (s.missions_total, s.missions_ok) == (779, 519)
    assert (s.missions_cancelled, s.missions_failed) == (62, 198)


def test_real_mission_start_and_minutes():
    s = parse()
    assert s.last_mission_started_at == datetime(2026, 11, 23, 14, 0, 17, tzinfo=UTC)
    assert s.last_mission_minutes is None  # mssnM 0 after docking


def test_real_no_signal_and_no_last_command_time():
    s = parse()
    assert s.wifi_rssi is None and s.wifi_snr is None
    assert s.last_command_at is None


def test_real_schedule_expands_to_seven_days():
    s = parse()
    assert [e.weekday for e in s.schedule] == [0, 1, 2, 3, 4, 5, 6]
    assert all(e.time == "08:00" and e.enabled for e in s.schedule)


def test_real_next_before_0800_is_same_day():
    s = parse(now=BEFORE)
    assert s.next_scheduled_at == datetime(2026, 11, 23, 8, 0, tzinfo=ZoneInfo(CHI)).astimezone(UTC)
    assert s.next_scheduled_at == datetime(2026, 11, 23, 14, 0, tzinfo=UTC)


def test_real_next_after_0800_is_next_day():
    now = datetime(2026, 11, 23, 15, 0, tzinfo=UTC)  # 09:00 CST
    s = parse(now=now)
    assert s.next_scheduled_at == datetime(2026, 11, 24, 14, 0, tzinfo=UTC)


def test_real_next_exactly_at_0800_rolls_to_next_day():
    now = datetime(2026, 11, 23, 14, 0, tzinfo=UTC)
    assert parse(now=now).next_scheduled_at == datetime(2026, 11, 24, 14, 0, tzinfo=UTC)


def test_real_next_across_dst_end():
    # Sat 2026-10-31 13:00 CDT; next 08:00 is Sun Nov 1 after clocks fell back (CST, UTC-6).
    now = datetime(2026, 10, 31, 18, 0, tzinfo=UTC)
    s = parse(now=now)
    expected = datetime(2026, 11, 1, 8, 0, tzinfo=ZoneInfo(CHI)).astimezone(UTC)
    assert s.next_scheduled_at == expected
    assert s.next_scheduled_at == datetime(2026, 11, 1, 14, 0, tzinfo=UTC)
    # The day before the change it is 08:00 CDT = 13:00Z.
    before = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)  # 07:00 CDT
    assert parse(now=before).next_scheduled_at == datetime(2026, 10, 31, 13, 0, tzinfo=UTC)


def test_vendor_day_mapping():
    got = schedule_entries([entry([0, 1, 6])])
    assert [(e.weekday) for e in got] == [0, 5, 6]  # Mon(1), Sat(6), Sun(0)


def test_multiple_entries_same_day_kept_and_sorted():
    got = schedule_entries([entry([1], 18, 30), entry([1], 8, 0)])
    assert [(e.weekday, e.time) for e in got] == [(0, "08:00"), (0, "18:30")]


def test_next_picks_later_entry_same_day():
    data = with_sched2([entry([1], 8, 0), entry([1], 18, 0)])
    now = datetime(2026, 11, 23, 16, 0, tzinfo=UTC)  # 10:00 CST Monday
    # 18:00 CST Monday = 00:00Z Tuesday
    assert parse(data, now=now).next_scheduled_at == datetime(2026, 11, 24, 0, 0, tzinfo=UTC)


def test_enabled_requires_true():
    got = schedule_entries(
        [
            entry([1], enabled=False),
            {"enabled": 1, "start": {"day": [2], "hour": 8, "min": 0}},
            {"start": {"day": [3], "hour": 8, "min": 0}},
        ]
    )
    assert [e.enabled for e in got] == [False, False, False]


def test_disabled_entries_give_no_next():
    s = parse(with_sched2([entry([0, 1, 2, 3, 4, 5, 6], enabled=False)]))
    assert len(s.schedule) == 7 and s.next_scheduled_at is None


def test_empty_schedule2_wins_over_legacy():
    data = with_sched2([])
    data["cleanSchedule"] = {"cycle": ["start"] * 7, "h": [10] * 7, "m": [0] * 7}
    s = parse(data)
    assert s.schedule == [] and s.next_scheduled_at is None


def test_legacy_used_when_schedule2_not_a_list():
    data = copy.deepcopy(REAL)
    data["cleanSchedule2"] = {"oops": 1}
    data["cleanSchedule"] = {"cycle": ["start"] * 7, "h": [10] * 7, "m": [0] * 7}
    s = parse(data)
    assert len(s.schedule) == 7 and s.schedule[0].time == "10:00"


def test_legacy_used_when_schedule2_missing():
    data = copy.deepcopy(REAL)
    del data["cleanSchedule2"]
    data["cleanSchedule"] = {"cycle": ["start"] + ["none"] * 6, "h": [9] * 7, "m": [5] * 7}
    s = parse(data)
    assert [(e.weekday, e.time, e.enabled) for e in s.schedule][-1] == (6, "09:05", True)


@pytest.mark.parametrize(
    "bad",
    [
        {"day": 1, "hour": 8, "min": 0},
        {"day": [1], "hour": "8", "min": 0},
        {"day": [1], "hour": 8, "min": None},
        {"day": [1], "hour": 24, "min": 0},
        {"day": [1], "hour": 8, "min": 60},
        {"day": [7], "hour": 8, "min": 0},
        {"day": [-1], "hour": 8, "min": 0},
        {"day": [True], "hour": 8, "min": 0},
        {"day": [1], "hour": True, "min": 0},
        {"day": [1], "hour": 8, "min": False},
        {"hour": 8, "min": 0},
    ],
)
def test_malformed_schedule2_dropped_whole(bad):
    good = entry([2])
    s = parse(with_sched2([good, {"enabled": True, "start": bad}]))
    assert s.schedule == [] and s.next_scheduled_at is None


@pytest.mark.parametrize("value", [None, 0, "1795442417", 1.5, True])
def test_mission_start_none_for_bad_values(value):
    data = copy.deepcopy(REAL)
    data["cleanMissionStatus"]["mssnStrtTm"] = value
    assert parse(data).last_mission_started_at is None


def test_mission_start_missing():
    data = copy.deepcopy(REAL)
    del data["cleanMissionStatus"]["mssnStrtTm"]
    assert parse(data).last_mission_started_at is None


def test_mission_start_is_utc_aware():
    s = parse()
    assert s.last_mission_started_at.utcoffset() == timedelta(0)


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0, None), (None, None), ("12", None), (True, None), (12.5, None), (25, 25), (1, 1)],
)
def test_last_mission_minutes(value, expected):
    data = copy.deepcopy(REAL)
    data["cleanMissionStatus"]["mssnM"] = value
    assert parse(data).last_mission_minutes == expected


class FakeClient:
    async def fetch_state(self, timeout: float = 15.0):
        return copy.deepcopy(REAL)


def test_api_returns_last_mission_started_at_iso():
    service = RoombaService(FakeClient(), device_id="BLID1", timezone=CHI, cache_seconds=30)
    app = create_app(
        Settings(_env_file=None, timezone=CHI),
        store=Store(":memory:"),
        hub=Hub(),
        adapters=[],
        roomba=service,
    )
    with TestClient(app) as http:
        r = http.get("/api/roomba/status")
    assert r.status_code == 200
    body = r.json()
    started = datetime.fromisoformat(body["last_mission_started_at"].replace("Z", "+00:00"))
    assert started == datetime(2026, 11, 23, 14, 0, 17, tzinfo=UTC)
    assert body["last_mission_minutes"] is None
    assert body["missions_total"] == 779
    assert len(body["schedule"]) == 7
