from datetime import UTC, datetime
from types import SimpleNamespace

from pylitterbot.activity import Activity
from pylitterbot.enums import LitterBoxStatus as LRStatus

from cat_dash.adapters.litterrobot import event_from_activity, status_from_robot

NOW = datetime(2026, 11, 18, 15, 0, tzinfo=UTC)


def fake_robot(**overrides):
    values = dict(
        id="123",
        name="Box",
        model="Litter-Robot 4",
        serial="LR4C1",
        status=LRStatus.READY,
        status_code="RDY",
        is_online=True,
        is_on=True,
        waste_drawer_level=42.0,
        is_waste_drawer_full=False,
        litter_level=88.5,
        pet_weight=10.4,
        cycle_count=17,
        is_sleeping=False,
        last_seen=NOW,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def test_status_from_robot():
    status = status_from_robot(fake_robot(), now=NOW)
    assert status.device_id == "123"
    assert status.status_code == "RDY" and status.status_text == LRStatus.READY.text
    assert status.waste_drawer_percent == 42.0 and status.litter_level_percent == 88.5
    assert status.cat_weight_lbs == 10.4 and status.cycles_since_drawer_reset == 17


def test_zero_weight_is_none():
    assert status_from_robot(fake_robot(pet_weight=0), now=NOW).cat_weight_lbs is None


def test_event_from_status_activity():
    event = event_from_activity("123", Activity(NOW, LRStatus.CLEAN_CYCLE_COMPLETE))
    assert event.code == "CCC" and event.text == "Clean Cycle Complete"
    assert event.cat_weight_lbs is None


def test_event_from_weight_activity():
    event = event_from_activity("123", Activity(NOW, "Pet Weight Recorded: 10.25 lbs"))
    assert event.code is None and event.cat_weight_lbs == 10.25
