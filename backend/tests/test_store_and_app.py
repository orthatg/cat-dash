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
