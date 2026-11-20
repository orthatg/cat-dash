from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from cat_dash.app import create_app
from cat_dash.config import Settings
from cat_dash.hub import Hub
from cat_dash.models import FeederStatus, FeedEvent, LitterEvent
from cat_dash.store import Store


@pytest.fixture
def store():
    s = Store(":memory:")
    yield s


async def test_store_dedupes_events(store):
    now = datetime.now(UTC)
    events = [FeedEvent(device_id="SN1", timestamp=now, portions=2)]
    assert await store.add_feed_events(events) == 1
    assert await store.add_feed_events(events) == 0
    assert [e.portions for e in await store.feed_events("SN1", now - timedelta(hours=1))] == [2]

    litter = [LitterEvent(device_id="1", timestamp=now, code="CCC", text="Clean Cycle Complete")]
    await store.add_litter_events(litter)
    await store.add_litter_events(litter)
    assert len(await store.litter_events("1", now - timedelta(hours=1))) == 1
    assert await store.latest_litter_event("1") == now


def test_settings_placeholders_mean_unconfigured(monkeypatch):
    monkeypatch.setenv("CATDASH_PETLIBRO_EMAIL", "CHANGE_ME")
    monkeypatch.setenv("CATDASH_PETLIBRO_PASSWORD", "CHANGE_ME")
    monkeypatch.setenv("CATDASH_LITTERROBOT_USERNAME", "")
    settings = Settings(_env_file=None)
    assert not settings.petlibro_configured and not settings.litterrobot_configured


async def test_api_status_and_feeder_daily(store):
    hub = Hub()
    now = datetime.now(UTC)
    hub.update_feeder(
        FeederStatus(
            device_id="SN1",
            name="Kibble",
            model="PLAF301",
            online=True,
            food_low=False,
            battery_percent=None,
            battery_state=None,
            today_dispensed_portions=3,
            today_feed_count=2,
            today_eat_count=None,
            last_feed_at=None,
            last_feed_portions=None,
            next_feed_at=None,
            next_feed_portions=None,
            desiccant_days_left=None,
            updated_at=now,
        )
    )
    await store.add_feed_events(
        [
            FeedEvent(device_id="SN1", timestamp=now - timedelta(minutes=5), portions=2),
            FeedEvent(device_id="SN1", timestamp=now - timedelta(minutes=1), portions=1),
        ]
    )
    app = create_app(Settings(_env_file=None, timezone="UTC"), store=store, hub=hub, adapters=[])
    with TestClient(app) as client:
        status = client.get("/api/status").json()
        assert status["feeders"][0]["food_low"] is False
        daily = client.get("/api/feeder/SN1/daily").json()
        assert sum(d["portions"] for d in daily) == 3
        assert sum(d["feeds"] for d in daily) == 2
        assert client.get("/api/litterbox/nope/insight").status_code == 404


async def test_drawer_endpoint(store):
    t = datetime(2026, 11, 1, tzinfo=UTC)
    await store.add_drawer_levels("box", [(t, 80.0), (t + timedelta(days=4), 90.0)])
    await store.add_drawer_empties(
        "box", [(t + timedelta(hours=1), 80.0), (t + timedelta(days=4, hours=1), 90.0)]
    )
    await store.add_litter_events(
        [
            LitterEvent(
                device_id="box",
                timestamp=t + timedelta(days=d),
                code="CCC",
                text="Clean Cycle Complete",
            )
            for d in (1, 2, 3)
        ]
    )
    app = create_app(Settings(_env_file=None), store=store, hub=Hub(), adapters=[])
    with TestClient(app) as client:
        body = client.get("/api/litterbox/box/drawer?days=3650").json()
    assert body["average_days_between_empties"] == 4.0
    assert body["average_cycles_between_empties"] == 3.0
    assert [e["clean_cycles"] for e in body["emptied"]] == [None, 3]
    assert len(body["levels"]) == 2


async def test_litter_daily_uses_median_weight(store):
    t = datetime(2026, 11, 7, 15, tzinfo=UTC)
    await store.add_litter_events(
        [
            LitterEvent(
                device_id="box",
                timestamp=t + timedelta(minutes=i),
                code=None,
                text=f"Pet Weight Recorded: {w} lbs",
                cat_weight_lbs=w,
            )
            for i, w in enumerate([5.4, 5.43, 15.99, 5.5])
        ]
    )
    app = create_app(Settings(_env_file=None, timezone="UTC"), store=store, hub=Hub(), adapters=[])
    with TestClient(app) as client:
        rows = client.get("/api/litterbox/box/daily?days=365").json()
    assert rows == [
        {"date": "2026-11-07", "clean_cycles": 0, "cat_weight_lbs": 5.46, "weight_readings": 4}
    ]


def test_attribute_by_nearest_profile():
    from cat_dash.cats import attribute
    from cat_dash.models import CatProfile

    cats = [CatProfile(name="Maui", weight_lbs=14.66), CatProfile(name="Zora", weight_lbs=5.38)]
    assert attribute(5.46, cats) == "Zora"
    assert attribute(15.99, cats) == "Maui"
    assert attribute(10.86, cats) == "Maui"
    assert attribute(25.0, cats) is None  # far from everyone
    assert attribute(5.4, []) is None


async def test_cats_daily_endpoint(store):
    from cat_dash.models import CatProfile, LitterBoxStatus

    t = datetime(2026, 11, 7, 15, tzinfo=UTC)
    await store.add_litter_events(
        [
            LitterEvent(
                device_id="box",
                timestamp=t + timedelta(minutes=i),
                code=None,
                text=f"Pet Weight Recorded: {w} lbs",
                cat_weight_lbs=w,
            )
            for i, w in enumerate([5.4, 5.43, 15.99, 5.5, 14.5])
        ]
    )
    hub = Hub()
    hub.update_litter_box(
        LitterBoxStatus(
            device_id="box",
            name="Box",
            model="LR4",
            serial="S",
            online=True,
            powered_on=True,
            status_code="RDY",
            status_text="Ready",
            waste_drawer_percent=0,
            waste_drawer_full=False,
            litter_level_percent=90,
            cat_weight_lbs=5.4,
            sleeping=False,
            updated_at=t,
            cats=[
                CatProfile(name="Maui", weight_lbs=14.66),
                CatProfile(name="Zora", weight_lbs=5.38),
            ],
        )
    )
    app = create_app(Settings(_env_file=None, timezone="UTC"), store=store, hub=hub, adapters=[])
    with TestClient(app) as client:
        rows = client.get("/api/litterbox/box/cats/daily?days=365").json()
    assert rows == [
        {"date": "2026-11-07", "cat": "Maui", "visits": 2, "weight_lbs": 15.25},
        {"date": "2026-11-07", "cat": "Zora", "visits": 3, "weight_lbs": 5.43},
    ]
