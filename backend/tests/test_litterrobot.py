import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from pylitterbot import LitterRobot4
from pylitterbot.activity import Activity
from pylitterbot.enums import LitterBoxStatus as LRStatus

from cat_dash.adapters.litterrobot import (
    LitterRobotAdapter,
    TokenFile,
    event_from_activity,
    parse_raw_activity,
    status_from_robot,
)
from cat_dash.drawer import detect_empties
from cat_dash.hub import Hub
from cat_dash.store import Store

NOW = datetime(2026, 11, 18, 15, 0, tzinfo=UTC)
FIXTURE = Path(__file__).parent / "fixtures" / "litterrobot" / "robot.json"


def real_robot() -> LitterRobot4:
    """A real pylitterbot object built from an anonymized live LR4 response (2026-11-20)."""
    return LitterRobot4(data=json.loads(FIXTURE.read_text()), account=None)


def test_status_from_real_robot():
    status = status_from_robot(real_robot(), now=NOW)
    assert status.device_id == "abc123unitid" and status.serial == "LR4C000001"
    assert status.online and status.powered_on and not status.sleeping
    assert (status.status_code, status.status_text) == ("RDY", "Ready")
    # The Whisker app showed "Empty" for this response, even though isDFIPartialFull is true.
    assert status.waste_drawer_percent == 0.0 and status.waste_drawer_state == "empty"
    assert status.waste_drawer_full is False
    assert (status.litter_level_percent, status.litter_level_state) == (90.0, "OPTIMAL")
    assert status.cat_weight_lbs == 5.38
    # pylitterbot's cycle_count is the lifetime odometer, not "since drawer emptied".
    assert status.lifetime_cycles == 7299
    assert status.last_emptied_at is None  # filled from history by the adapter


def test_drawer_full_state():
    data = json.loads(FIXTURE.read_text()) | {"isDFIFull": True}
    status = status_from_robot(LitterRobot4(data=data, account=None), now=NOW)
    assert status.waste_drawer_full and status.waste_drawer_state == "full"


def test_drawer_partial_state():
    data = json.loads(FIXTURE.read_text()) | {"DFILevelPercent": 45}
    status = status_from_robot(LitterRobot4(data=data, account=None), now=NOW)
    assert (status.waste_drawer_percent, status.waste_drawer_state) == (45.0, "partial")


def test_zero_weight_is_none():
    data = json.loads(FIXTURE.read_text()) | {"catWeight": 0}
    assert status_from_robot(LitterRobot4(data=data, account=None)).cat_weight_lbs is None


def test_event_from_status_activity():
    event = event_from_activity("123", Activity(NOW, LRStatus.CLEAN_CYCLE_COMPLETE))
    assert event.code == "CCC" and event.text == "Clean Cycle Complete"
    assert event.cat_weight_lbs is None


def test_event_from_weight_activity():
    event = event_from_activity("123", Activity(NOW, "Pet Weight Recorded: 10.25 lbs"))
    assert event.code is None and event.cat_weight_lbs == 10.25


def raw(ts: datetime, value: str, action: str = "") -> dict:
    return {
        "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S.000000000"),
        "value": value,
        "actionValue": action,
    }


class HistoryRobot:
    """Wraps the real robot but answers the activity GraphQL query with canned entries."""

    def __init__(self, robot, entries):
        self._robot = robot
        self.entries = entries
        self.calls = []

    def __getattr__(self, name):
        return getattr(self._robot, name)

    async def _post(self, json):
        self.calls.append(json["variables"])
        return {"data": {"getLitterRobot4Activity": self.entries}}

    async def get_insight(self, days):
        return SimpleNamespace(total_cycles=3, average_cycles=1.0, cycle_history=[])


def test_parse_raw_activity_keeps_drawer_levels():
    t = datetime(2026, 11, 20, 15, 0, tzinfo=UTC)
    events, levels = parse_raw_activity(
        real_robot(),
        "dev",
        [
            raw(t, "robotStatusCatDetect"),
            raw(t, "robotCycleStatusIdle"),
            raw(t, "catWeight", "5.4"),
            raw(t, "DFILevelPercent", "42"),
        ],
    )
    assert [e.code for e in events] == ["CD", "CCC", None]
    assert events[2].cat_weight_lbs == 5.4
    assert levels == [(t, 42.0)]


def test_detect_empties_ignores_noise():
    t = datetime(2026, 11, 1, tzinfo=UTC)
    readings = [49, 87, 0, 3, 40, 92, 68, 76, 14, 82, 0, 2]  # from the live robot
    levels = [(t + timedelta(hours=i), float(p)) for i, p in enumerate(readings)]
    empties = detect_empties(levels)
    assert [(e[0] - t, e[1]) for e in empties] == [
        (timedelta(hours=2), 87.0),
        (timedelta(hours=10), 82.0),
    ]


async def test_sync_tracks_drawer_empties(tmp_path):
    t = datetime.now(UTC).replace(microsecond=0) - timedelta(days=3)
    entries = [
        raw(t, "DFILevelPercent", "80"),
        raw(t + timedelta(hours=1), "DFILevelPercent", "0"),  # emptied
        raw(t + timedelta(hours=2), "robotStatusCatDetect"),
        raw(t + timedelta(hours=3), "robotCycleStatusIdle"),
        raw(t + timedelta(hours=4), "robotCycleStatusIdle"),
        raw(t + timedelta(hours=4, minutes=1), "DFILevelPercent", "5"),
    ]
    robot = HistoryRobot(real_robot(), entries)
    hub, store = Hub(), Store(":memory:")
    adapter = LitterRobotAdapter(hub, store, "u", "p", TokenFile(tmp_path / "t.json"))
    adapter._account = SimpleNamespace(get_robots=lambda _cls: [robot])

    await adapter.sync_history()
    assert robot.calls[0]["limit"] == 5000  # first run: 30-day backfill
    status = hub.litter_box("abc123unitid")
    assert status.last_emptied_at == t + timedelta(hours=1)
    assert status.cycles_since_emptied == 2
    assert status.last_cat_detected_at == t + timedelta(hours=2)
    assert status.last_clean_cycle_at == t + timedelta(hours=4)

    await adapter.sync_history()
    second = robot.calls[1]
    assert second["limit"] == 1000
    assert second["startTimestamp"] == (t + timedelta(hours=4, minutes=1)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    assert len(await store.drawer_empties("abc123unitid")) == 1  # no duplicates


def test_fill_model_and_forecast_from_live_empties():
    from cat_dash.drawer import fill_model, forecast

    # The six empties seen on the live robot (Oct 25 - Nov 20, 2026).
    empties = [
        (datetime(2026, 10, 25, 3, 7, 53, tzinfo=UTC), 87.0),
        (datetime(2026, 10, 28, 12, 25, 23, tzinfo=UTC), 65.0),
        (datetime(2026, 11, 5, 23, 49, 3, tzinfo=UTC), 82.0),
        (datetime(2026, 11, 10, 14, 54, 56, tzinfo=UTC), 87.0),
        (datetime(2026, 11, 15, 20, 25, 39, tzinfo=UTC), 70.0),
        (datetime(2026, 11, 20, 15, 2, 32, tzinfo=UTC), 107.0),
    ]
    model = fill_model(empties)
    assert model.cycles_used == 5
    assert round(model.rate_percent_per_day, 1) == 18.8
    assert model.usual_empty_percent == 82.0

    now = datetime(2026, 11, 20, 23, 0, tzinfo=UTC)
    outlook = forecast(model, 6.0, now)
    assert round((outlook.needs_emptying_at - now).total_seconds() / 86400, 1) == 4.0
    assert round((outlook.full_at - now).total_seconds() / 86400, 1) == 5.0
    # Already past full: due now.
    assert forecast(model, 120.0, now).full_at == now


def test_fill_model_needs_two_empties():
    from cat_dash.drawer import fill_model

    assert fill_model([]) is None
    assert fill_model([(datetime(2026, 11, 1, tzinfo=UTC), 80.0)]) is None


async def test_status_carries_drawer_forecast(tmp_path):
    t = datetime.now(UTC).replace(microsecond=0) - timedelta(days=10)
    entries = [
        raw(t, "DFILevelPercent", "60"),
        raw(t + timedelta(days=1), "DFILevelPercent", "0"),  # emptied
        raw(t + timedelta(days=5), "DFILevelPercent", "80"),
        raw(t + timedelta(days=5, hours=1), "DFILevelPercent", "0"),  # emptied: 80% in 4 days
    ]
    robot = HistoryRobot(real_robot(), entries)  # live level in the fixture: 0%
    hub, store = Hub(), Store(":memory:")
    adapter = LitterRobotAdapter(hub, store, "u", "p", TokenFile(tmp_path / "t.json"))
    adapter._account = SimpleNamespace(get_robots=lambda _cls: [robot])
    await adapter.sync_history()
    status = hub.litter_box("abc123unitid")
    assert status.drawer_fill_rate_per_day == 19.8  # 80% over 4.04 days
    assert status.drawer_usual_empty_percent == 70.0  # median of 60 and 80
    days_to_full = (status.drawer_full_at - status.updated_at).total_seconds() / 86400
    assert round(days_to_full, 1) == 5.1
