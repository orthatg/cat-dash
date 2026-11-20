import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cat_dash.petlibro import parse

TZ = "America/Chicago"
# Wednesday 2026-11-18 15:00 UTC = 09:00 Chicago
NOW = datetime(2026, 11, 18, 15, 0, tzinfo=UTC)
FIXTURES = Path(__file__).parent / "fixtures" / "petlibro"

DEVICE = {
    "deviceSn": "SN1",
    "productIdentifier": "PLAF301",
    "name": "Kibble",
    "enableBatteryPercent": True,
}


def ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def load(name: str):
    return json.loads((FIXTURES / f"{name}.json").read_text())


WORK_RECORDS = [
    {
        "recordTime": "2026/11/18",
        "workRecords": [
            {
                "id": "a",
                "type": "GRAIN_OUTPUT_SUCCESS",
                "recordTime": ms(datetime(2026, 11, 18, 13, 0, tzinfo=UTC)),
                "actualGrainNum": 2,
            },
            {"id": "b", "type": "GRAIN_OUTLET_BLOCK_REMOVED", "recordTime": ms(NOW)},
        ],
    },
    {
        "recordTime": "2026/11/17",
        "workRecords": [
            {
                "id": "c",
                "type": "GRAIN_OUTPUT_SUCCESS",
                "recordTime": ms(datetime(2026, 11, 17, 23, 0, tzinfo=UTC)),
                "actualGrainNum": None,
                "params": '{"actualGrainNum":3}',
            },
        ],
    },
]


def test_flatten_ignores_day_level_record_time_string():
    assert [r["id"] for r in parse.flatten_records(WORK_RECORDS)] == ["a", "b", "c"]


def test_feed_events_only_feeds_sorted_with_params_fallback():
    events = parse.feed_events("SN1", parse.flatten_records(WORK_RECORDS))
    assert [e.portions for e in events] == [3, 2]
    assert events[-1].timestamp == datetime(2026, 11, 18, 13, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("text", "seconds"),
    [("15s", 15), ("02m05s", 125), ("1h02m05s", 3725), ("3m", 180), ("", None), ("x", None)],
)
def test_parse_duration(text, seconds):
    assert parse.parse_duration(text) == seconds


def test_next_feed_today_and_wraps_to_next_day():
    plans = [
        {"enable": True, "executionTime": "07:00", "repeatDay": "[7,1,2,3,4,5,6]", "grainNum": 1},
        {"enable": True, "executionTime": "18:30", "repeatDay": "[]", "grainNum": 2},
        {"enable": False, "executionTime": "10:00", "repeatDay": "[]", "grainNum": 9},
    ]
    when, portions = parse.next_feed(plans, NOW, TZ)
    assert portions == 2
    assert when == datetime(2026, 11, 19, 0, 30, tzinfo=UTC)  # 18:30 Chicago

    late = datetime(2026, 11, 19, 1, 0, tzinfo=UTC)  # 19:00 Chicago
    when, portions = parse.next_feed(plans, late, TZ)
    assert portions == 1 and when == datetime(2026, 11, 19, 13, 0, tzinfo=UTC)


def test_next_feed_respects_weekdays():
    # "[1,5,3]" = Mon/Fri/Wed (ISO). NOW is Wednesday 09:00, so 08:00 Wed has passed -> Fri.
    plans = [{"enable": True, "executionTime": "08:00", "repeatDay": "[1,5,3]", "grainNum": 1}]
    when, _ = parse.next_feed(plans, NOW, TZ)
    assert when == datetime(2026, 11, 20, 14, 0, tzinfo=UTC)


def test_battery_hidden_when_device_does_not_report_percent():
    no_percent = {**DEVICE, "enableBatteryPercent": False}
    kwargs = dict(data_real_info={}, grain_status={}, records=[], plans=None, now=NOW, timezone=TZ)
    status = parse.feeder_status(no_percent, real_info={"electricQuantity": 0}, **kwargs)
    assert status.battery_percent is None
    status = parse.feeder_status(DEVICE, real_info={"electricQuantity": 87}, **kwargs)
    assert status.battery_percent == 87.0


def test_feeder_status_missing_fields_are_none():
    status = parse.feeder_status(
        {"deviceSn": "SN2"},
        real_info={},
        data_real_info={},
        grain_status={},
        records=[],
        plans=None,
        now=NOW,
        timezone=TZ,
    )
    assert status.food_low is None and status.last_feed_at is None and status.next_feed_at is None


def test_problems():
    found = parse.problems(
        {"barnDoorError": True, "grainOutletState": False, "deviceStoppedWorking": True},
        {"exceptionMessage": "Rotor stuck"},
    )
    assert found == ["lid_blocked", "dispenser_blocked", "stopped_working", "rotor_stuck"]
    assert parse.problems({"doorErrorState": "NORMAL", "grainOutletState": True}, {}) == []


# --- real (anonymized) One RFID responses captured 2026-11-20 ---


def test_real_one_rfid_status():
    records = parse.flatten_records(load("work_records"))
    status = parse.feeder_status(
        load("device"),
        real_info=load("real_info"),
        data_real_info=load("data_real_info"),
        grain_status=load("grain_status"),
        records=records,
        plans=load("feeding_plans"),
        now=datetime(2026, 11, 20, 19, 7, tzinfo=UTC),
        timezone=TZ,
    )
    assert status.name == "Feeder One" and status.model == "One RFID Smart Feeder"
    assert status.online is True
    assert status.food_low is False  # surplusGrain: true
    assert status.battery_percent is None  # electricQuantity 0, enableBatteryPercent false
    assert (status.today_dispensed_portions, status.today_feed_count) == (4, 2)
    assert (status.today_eat_count, status.today_eat_seconds) == (11, 751)
    assert status.last_feed_at == datetime(2026, 11, 20, 13, 0, 4, tzinfo=UTC)
    assert status.last_feed_portions == 1
    # 19:00 Chicago dinner plan, 2 portions; device list agrees (nextFeedingTime "19:00").
    assert status.next_feed_at == datetime(2026, 11, 21, 1, 0, tzinfo=UTC)
    assert status.next_feed_portions == 2
    assert (status.desiccant_days_left, status.desiccant_state) == (-701.0, "OVER_DUE")
    assert status.problems == []


def test_real_one_rfid_records():
    records = parse.flatten_records(load("work_records"))
    feeds = parse.feed_events("SN", records)
    visits = parse.pet_visits("SN", records)
    assert [f.portions for f in feeds] == [3, 1]
    assert len(visits) == 4
    assert {v.pet_name for v in visits} == {"Whiskers"} and visits[0].pet_id == 1001
    assert all(v.seconds is not None and v.seconds > 0 for v in visits)
