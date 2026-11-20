from datetime import UTC, datetime

from cat_dash.petlibro import parse

TZ = "America/Chicago"
# Wednesday 2026-11-18 15:00 UTC = 09:00 Chicago
NOW = datetime(2026, 11, 18, 15, 0, tzinfo=UTC)

DEVICE = {"deviceSn": "SN1", "productIdentifier": "PLAF301", "name": "Kibble"}


def ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


WORK_RECORDS = [
    {
        "day": "2026-11-18",
        "workRecords": [
            {
                "type": "GRAIN_OUTPUT_SUCCESS",
                "recordTime": ms(datetime(2026, 11, 18, 13, 0, tzinfo=UTC)),
                "actualGrainNum": 2,
            },
            {"type": "SOMETHING_ELSE", "recordTime": ms(NOW)},
        ],
    },
    {
        "day": "2026-11-17",
        "workRecords": [
            {
                "type": "GRAIN_OUTPUT_SUCCESS",
                "recordTime": ms(datetime(2026, 11, 17, 23, 0, tzinfo=UTC)),
                "actualGrainNum": 3,
            },
        ],
    },
]


def test_feed_events_flatten_and_sort():
    events = parse.feed_events("SN1", WORK_RECORDS)
    assert [e.portions for e in events] == [3, 2]
    assert events[-1].timestamp == datetime(2026, 11, 18, 13, 0, tzinfo=UTC)


def test_next_feed_today_and_wraps_to_next_day():
    plans = [
        {"enable": True, "executionTime": "07:00", "repeatDay": "[1,2,3,4,5,6,7]", "grainNum": 1},
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
    # Only Fridays (ISO 5). NOW is Wednesday.
    plans = [{"enable": True, "executionTime": "08:00", "repeatDay": [5], "grainNum": 1}]
    when, _ = parse.next_feed(plans, NOW, TZ)
    assert when == datetime(2026, 11, 20, 14, 0, tzinfo=UTC)


def test_feeder_status_full():
    status = parse.feeder_status(
        DEVICE,
        real_info={
            "surplusGrain": False,
            "online": True,
            "electricQuantity": 87,
            "batteryState": "high",
            "barnDoorError": False,
            "grainOutletState": True,
        },
        data_real_info={"exceptionMessage": ""},
        grain_status={"todayFeedingQuantity": 5, "todayFeedingTimes": 2, "todayEatingTimes": 4},
        work_records=WORK_RECORDS,
        plans=[{"enable": True, "executionTime": "18:30", "repeatDay": "[]", "grainNum": 2}],
        now=NOW,
        timezone=TZ,
    )
    assert status.device_id == "SN1" and status.name == "Kibble" and status.model == "PLAF301"
    assert status.food_low is True
    assert status.online is True and status.battery_percent == 87.0
    assert (status.today_dispensed_portions, status.today_feed_count, status.today_eat_count) == (
        5,
        2,
        4,
    )
    assert status.last_feed_portions == 2
    assert status.next_feed_portions == 2
    assert status.problems == []


def test_feeder_status_missing_fields_are_none():
    status = parse.feeder_status(
        {"deviceSn": "SN2"},
        real_info={},
        data_real_info={},
        grain_status={},
        work_records=None,
        plans=None,
        now=NOW,
        timezone=TZ,
    )
    assert status.food_low is None and status.last_feed_at is None and status.next_feed_at is None


def test_problems():
    found = parse.problems(
        {"barnDoorError": True, "grainOutletState": False},
        {"exceptionMessage": "Rotor stuck"},
    )
    assert found == ["lid_blocked", "dispenser_blocked", "rotor_stuck"]
