import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from cat_dash.roomba.parse import next_scheduled, parse_status, schedule_entries

REPORTED = json.loads((Path(__file__).parent / "fixtures/roomba/reported.json").read_text())
CHI = "America/Chicago"
NOW = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)  # Monday 06:00 Chicago (CST)


def parse(reported=None, *, now=NOW, tz=CHI):
    data = copy.deepcopy(REPORTED if reported is None else reported)
    return parse_status(data, device_id="BLID1", timezone=tz, now=now)


def with_phase(phase, **mission):
    data = copy.deepcopy(REPORTED)
    data["cleanMissionStatus"].update(phase=phase, **mission)
    return data


def sched(cycles, hours=None, minutes=None):
    return {
        "cycle": cycles,
        "h": hours or [10] * len(cycles),
        "m": minutes or [30] * len(cycles),
    }


def week(enabled_vendor_days, hour=10, minute=30):
    """Vendor-indexed schedule (0 = Sunday) with the given days enabled."""
    cycles = ["start" if i in enabled_vendor_days else "none" for i in range(7)]
    return sched(cycles, [hour] * 7, [minute] * 7)


def test_full_sample_fields():
    s = parse()
    assert s.device_id == "BLID1"
    assert s.battery_percent == 87
    assert s.state == "charging" and s.phase == "charge"
    assert s.cycle == "none"
    assert s.error_code == 0 and s.error_text is None
    assert s.problems == []
    assert s.bin_present is True and s.bin_full is False
    assert s.model == "i755020" and s.name == "Roomba"
    assert s.software_version == "v3.2.x-SYNTHETIC"
    assert s.last_command == "start" and s.last_command_initiator == "schedule"
    assert s.last_command_at == datetime.fromtimestamp(1795440000, tz=UTC)
    assert s.last_command_at.utcoffset().total_seconds() == 0
    assert (s.last_mission_minutes, s.last_mission_sqft, s.mission_number) == (42, 310, 214)
    assert (s.missions_total, s.missions_ok) == (214, 198)
    assert (s.missions_cancelled, s.missions_failed) == (12, 4)
    assert (s.wifi_rssi, s.wifi_snr) == (-52, 38)
    assert s.fetched_at == NOW


def test_sensors_include_present_groups_only():
    s = parse()
    assert set(s.sensors) == {"bbrun", "bbchg3", "bbchg", "bbswitch", "bbsys"}
    assert s.sensors["bbrun"]["nStuck"] == 9
    assert "bbmssn" not in s.sensors and "signal" not in s.sensors
    data = copy.deepcopy(REPORTED)
    data["bbnav"] = {"aMtrack": 1}
    assert "bbnav" in parse(data).sensors


@pytest.mark.parametrize(
    ("phase", "expected"),
    [
        ("charge", "charging"),
        ("run", "cleaning"),
        ("hmUsrDock", "returning"),
        ("hmMidMsn", "returning"),
        ("hmPostMsn", "returning"),
        ("stuck", "stuck"),
        ("stop", "paused"),
        ("new", "idle"),
        ("somethingNew", "unknown"),
        (None, "unknown"),
    ],
)
def test_state_mapping(phase, expected):
    assert parse(with_phase(phase)).state == expected


def test_nonzero_error_overrides_phase():
    s = parse(with_phase("run", error=15))
    assert s.state == "error" and s.error_code == 15
    assert s.error_text
    assert any("15" in p or "rror" in p for p in s.problems)


def test_problems_list():
    data = with_phase("charge", notReady=7)
    data["bin"] = {"present": True, "full": True}
    problems = parse(data).problems
    assert any("full" in p.lower() for p in problems)
    assert any("ready" in p.lower() for p in problems)
    assert parse(data).not_ready_code == 7
    data["bin"] = {"present": False, "full": False}
    assert any("missing" in p.lower() for p in parse(data).problems)


def test_problems_combined():
    data = with_phase("run", error=1, notReady=2)
    data["bin"] = {"present": False, "full": True}
    assert len(parse(data).problems) == 4


def test_empty_reported_does_not_crash():
    s = parse({})
    assert s.state == "unknown" and s.battery_percent is None
    assert s.schedule == [] and s.next_scheduled_at is None
    assert s.sensors == {} and s.problems == []
    assert s.error_code == 0 and s.not_ready_code == 0
    assert s.last_command_at is None


@pytest.mark.parametrize(
    "key", ["cleanMissionStatus", "lastCommand", "bbmssn", "signal", "bin", "cleanSchedule"]
)
@pytest.mark.parametrize("junk", ["oops", 5, [], ["x"], True])
def test_non_dict_groups_do_not_crash(key, junk):
    data = copy.deepcopy(REPORTED)
    data[key] = junk
    s = parse(data)
    assert s.device_id == "BLID1"


def test_wrong_scalar_types_do_not_crash():
    data = {
        "batPct": "87",
        "cleanMissionStatus": {"error": "boom", "notReady": None, "mssnM": 1.5, "nMssn": "x"},
        "lastCommand": {"time": "yesterday"},
    }
    s = parse(data)
    assert s.battery_percent is None
    assert s.error_code == 0 and s.not_ready_code == 0
    assert s.last_mission_minutes is None and s.mission_number is None
    assert s.last_command_at is None


@pytest.mark.parametrize("key", ["name", "sku", "softwareVer"])
def test_non_string_text_fields_do_not_crash(key):
    data = copy.deepcopy(REPORTED)
    data[key] = 5
    parse(data)


def test_non_string_phase_and_cycle_do_not_crash():
    parse(with_phase(5, cycle=7))


@pytest.mark.parametrize(
    "bad",
    [
        {"cycle": ["start"] * 7, "h": ["x"] * 7, "m": [0] * 7},
        {"cycle": ["start"] * 7, "h": [None] * 7, "m": [0] * 7},
        {"cycle": ["start"] * 7, "h": [10] * 7, "m": [[]] * 7},
    ],
)
def test_garbage_schedule_values_do_not_crash(bad):
    data = copy.deepcopy(REPORTED)
    data["cleanSchedule"] = bad
    parse(data)


def test_booleans_are_not_ints():
    data = copy.deepcopy(REPORTED)
    data["batPct"] = True
    data["cleanMissionStatus"]["error"] = True
    data["signal"] = {"rssi": False, "snr": True}
    s = parse(data)
    assert s.battery_percent is None
    assert s.error_code == 0 and s.state == "charging"
    assert s.wifi_rssi is None and s.wifi_snr is None


def test_none_mission_blocks():
    s = parse({"batPct": 50, "cleanMissionStatus": None, "lastCommand": None, "bbmssn": None})
    assert s.battery_percent == 50 and s.state == "unknown"


# ---------------------------------------------------------------- schedule


def test_schedule_weekday_conversion_and_sort():
    entries = schedule_entries(REPORTED["cleanSchedule"])
    assert [e.weekday for e in entries] == [0, 1, 2, 3, 4, 5, 6]
    # vendor index 0 (Sunday, "none") becomes weekday 6, disabled
    assert entries[6].enabled is False
    assert all(e.enabled for e in entries[:5])
    assert entries[5].enabled is False  # vendor Saturday
    assert entries[0].time == "10:30"


def test_schedule_vendor_index_maps_to_correct_weekday():
    entries = schedule_entries(
        sched(["start"] * 7, [0, 1, 2, 3, 4, 5, 6], [0, 10, 20, 30, 40, 50, 5])
    )
    by_day = {e.weekday: e.time for e in entries}
    assert by_day[6] == "00:00"  # Sunday
    assert by_day[0] == "01:10"  # Monday
    assert by_day[5] == "06:05"  # Saturday (vendor index 6)


def test_schedule_time_zero_padded_and_disabled_flag():
    entries = schedule_entries(sched(["none", "start"], [7, 9], [5, 0]))
    assert len(entries) == 2
    sunday = next(e for e in entries if e.weekday == 6)
    monday = next(e for e in entries if e.weekday == 0)
    assert sunday.time == "07:05" and not sunday.enabled
    assert monday.time == "09:00" and monday.enabled


@pytest.mark.parametrize(
    "raw",
    [
        {},
        None,
        {"cycle": "none", "h": [], "m": []},
        {"cycle": ["start"] * 7},
        {"cycle": ["start"] * 7, "h": [10] * 7, "m": "30"},
    ],
)
def test_schedule_malformed_is_empty(raw):
    assert schedule_entries(raw or {}) == []


def test_malformed_schedule_gives_none_next():
    data = copy.deepcopy(REPORTED)
    data["cleanSchedule"] = {"cycle": ["start"] * 7}
    s = parse(data)
    assert s.schedule == [] and s.next_scheduled_at is None


def test_next_scheduled_later_today():
    # Monday 06:00 local; Monday 10:30 enabled (vendor 1) -> 16:30 UTC (CST, UTC-6)
    s = parse()
    assert s.next_scheduled_at == datetime(2026, 11, 23, 16, 30, tzinfo=UTC)
    assert s.next_scheduled_at.utcoffset().total_seconds() == 0


def test_next_scheduled_same_day_already_passed_goes_to_next_enabled_day():
    now = datetime(2026, 11, 23, 20, 0, tzinfo=UTC)  # Monday 14:00 local, past 10:30
    s = parse(now=now)
    assert s.next_scheduled_at == datetime(2026, 11, 24, 16, 30, tzinfo=UTC)  # Tuesday


def test_next_scheduled_strictly_after_now():
    exactly = datetime(2026, 11, 23, 16, 30, tzinfo=UTC)  # Monday 10:30 local exactly
    assert parse(now=exactly).next_scheduled_at == datetime(2026, 11, 24, 16, 30, tzinfo=UTC)
    just_before = datetime(2026, 11, 23, 16, 29, 59, tzinfo=UTC)
    assert parse(now=just_before).next_scheduled_at == exactly


def test_next_scheduled_wraps_to_next_week():
    data = copy.deepcopy(REPORTED)
    data["cleanSchedule"] = week({1})  # Monday only
    now = datetime(2026, 11, 23, 20, 0, tzinfo=UTC)  # Monday after 10:30
    assert parse(data, now=now).next_scheduled_at == datetime(2026, 11, 30, 16, 30, tzinfo=UTC)


def test_next_scheduled_skips_disabled_weekend():
    # Fixture: Saturday and Sunday disabled. Friday afternoon -> Monday.
    now = datetime(2026, 11, 27, 20, 0, tzinfo=UTC)  # Friday 14:00 local
    assert parse(now=now).next_scheduled_at == datetime(2026, 11, 30, 16, 30, tzinfo=UTC)


def test_next_scheduled_sunday_uses_vendor_index_zero():
    data = copy.deepcopy(REPORTED)
    data["cleanSchedule"] = week({0})  # Sunday only
    assert parse(data).next_scheduled_at == datetime(2026, 11, 29, 16, 30, tzinfo=UTC)


def test_next_scheduled_none_when_all_disabled():
    data = copy.deepcopy(REPORTED)
    data["cleanSchedule"] = week(set())
    s = parse(data)
    assert s.next_scheduled_at is None
    assert len(s.schedule) == 7 and not any(e.enabled for e in s.schedule)


def test_next_scheduled_uses_house_timezone_for_day_boundary():
    # 2026-11-24 03:00 UTC is still Monday 21:00 in Chicago, so Monday 10:30 has passed
    # and the next slot is Tuesday 10:30 local, not Wednesday.
    now = datetime(2026, 11, 24, 3, 0, tzinfo=UTC)
    assert parse(now=now).next_scheduled_at == datetime(2026, 11, 24, 16, 30, tzinfo=UTC)
    # In UTC the same instant is Tuesday 03:00, so Tuesday 10:30 UTC.
    assert parse(now=now, tz="UTC").next_scheduled_at == datetime(2026, 11, 24, 10, 30, tzinfo=UTC)


def test_next_scheduled_dst_spring_forward():
    # Saturday 2027-03-13 20:00 UTC. DST starts Sunday 2027-03-14 02:00 local.
    # Sunday 10:30 local is CDT (UTC-5) -> 15:30 UTC, not 16:30.
    data = copy.deepcopy(REPORTED)
    data["cleanSchedule"] = week({0})
    now = datetime(2027, 3, 13, 20, 0, tzinfo=UTC)
    assert parse(data, now=now).next_scheduled_at == datetime(2027, 3, 14, 15, 30, tzinfo=UTC)


def test_next_scheduled_dst_fall_back():
    # Saturday 2026-10-31 20:00 UTC. DST ends Sunday 2026-11-01. Sunday 10:30 is CST -> 16:30 UTC.
    data = copy.deepcopy(REPORTED)
    data["cleanSchedule"] = week({0})
    now = datetime(2026, 10, 31, 20, 0, tzinfo=UTC)
    assert parse(data, now=now).next_scheduled_at == datetime(2026, 11, 1, 16, 30, tzinfo=UTC)


def test_next_scheduled_across_dst_week_wraps_in_local_wall_time():
    # Sunday-only slot, now is Sunday after the slot on the spring-forward day.
    # Next one is the following Sunday 10:30 CDT -> 15:30 UTC.
    data = copy.deepcopy(REPORTED)
    data["cleanSchedule"] = week({0})
    now = datetime(2027, 3, 14, 18, 0, tzinfo=UTC)
    assert parse(data, now=now).next_scheduled_at == datetime(2027, 3, 21, 15, 30, tzinfo=UTC)


def test_next_scheduled_accepts_non_utc_now():
    now = datetime(2026, 11, 23, 6, 0, tzinfo=ZoneInfo(CHI))  # same instant as NOW
    assert parse(now=now).next_scheduled_at == datetime(2026, 11, 23, 16, 30, tzinfo=UTC)


def test_next_scheduled_helper_direct():
    entries = schedule_entries(week({3}, hour=23, minute=59))  # Wednesday 23:59
    out = next_scheduled(entries, NOW, ZoneInfo(CHI))
    assert out == datetime(2026, 11, 26, 5, 59, tzinfo=UTC)
