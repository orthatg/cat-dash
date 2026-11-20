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
    status_from_robot,
)
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
    # DFILevelPercent reads 0 while isDFIPartialFull is true: the state is what to show.
    assert status.waste_drawer_percent == 0.0 and status.waste_drawer_state == "partial"
    assert status.waste_drawer_full is False
    assert (status.litter_level_percent, status.litter_level_state) == (90.0, "OPTIMAL")
    assert status.cat_weight_lbs == 5.38
    # pylitterbot's cycle_count is the lifetime odometer, not "since drawer reset".
    assert (status.cycles_since_drawer_reset, status.lifetime_cycles) == (17, 7299)


def test_drawer_full_state():
    data = json.loads(FIXTURE.read_text()) | {"isDFIFull": True}
    status = status_from_robot(LitterRobot4(data=data, account=None), now=NOW)
    assert status.waste_drawer_full and status.waste_drawer_state == "full"


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


class HistoryRobot:
    """Wraps the real robot but serves canned history."""

    def __init__(self, robot, activities):
        self._robot = robot
        self._activities = activities
        self.calls = []

    def __getattr__(self, name):
        return getattr(self._robot, name)

    async def get_activity_history(self, limit, start):
        self.calls.append((limit, start))
        return self._activities

    async def get_insight(self, days):
        return SimpleNamespace(total_cycles=3, average_cycles=1.0, cycle_history=[])


async def test_sync_history_backfills_then_fills_last_activity(tmp_path):
    t = datetime.now(UTC) - timedelta(hours=2)
    robot = HistoryRobot(
        real_robot(),
        [
            Activity(t, LRStatus.CAT_DETECTED),
            Activity(t + timedelta(minutes=8), LRStatus.CLEAN_CYCLE_COMPLETE),
            Activity(t + timedelta(minutes=9), "Pet Weight Recorded: 5.4 lbs"),
        ],
    )
    hub, store = Hub(), Store(":memory:")
    adapter = LitterRobotAdapter(hub, store, "u", "p", TokenFile(tmp_path / "t.json"))
    adapter._account = SimpleNamespace(get_robots=lambda _cls: [robot])

    await adapter.sync_history()
    limit, _ = robot.calls[0]
    assert limit == 5000  # first run: 30-day backfill
    status = hub.litter_box("abc123unitid")
    assert status.last_cat_detected_at == t
    assert status.last_clean_cycle_at == t + timedelta(minutes=8)

    await adapter.sync_history()
    limit, start = robot.calls[1]
    assert limit == 1000 and start == t + timedelta(minutes=9)  # incremental
    assert len(await store.litter_events("abc123unitid", t - timedelta(days=1))) == 3
