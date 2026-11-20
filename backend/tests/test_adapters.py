import contextlib
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import respx
from pylitterbot.enums import LitterBoxStatus as LRStatus

from cat_dash.adapters.litterrobot import LitterRobotAdapter, TokenFile
from cat_dash.adapters.petlibro import PetlibroAdapter
from cat_dash.hub import Hub
from cat_dash.petlibro import PetlibroClient
from cat_dash.store import Store

BASE = "https://api.us.petlibro.com"


def ok(data):
    return httpx.Response(200, json={"code": 0, "data": data})


@respx.mock
async def test_petlibro_poll_updates_hub_and_store(tmp_path):
    now_ms = int(datetime.now(UTC).timestamp() * 1000) - 60_000
    respx.post(f"{BASE}/member/auth/login").mock(return_value=ok({"token": "t"}))
    respx.post(f"{BASE}/device/device/list").mock(
        return_value=ok([{"deviceSn": "SN1", "productIdentifier": "PLAF301"}])
    )
    respx.post(f"{BASE}/device/device/realInfo").mock(
        return_value=ok({"surplusGrain": True, "online": True})
    )
    respx.post(f"{BASE}/data/data/realInfo").mock(return_value=ok({}))
    respx.post(f"{BASE}/device/data/grainStatus").mock(return_value=ok({"todayFeedingTimes": 1}))
    respx.post(f"{BASE}/device/workRecord/list").mock(
        return_value=ok(
            [
                {
                    "workRecords": [
                        {
                            "id": "f1",
                            "type": "GRAIN_OUTPUT_SUCCESS",
                            "recordTime": now_ms,
                            "actualGrainNum": 2,
                        },
                        {
                            "id": "v1",
                            "type": "DETECTION_EVENT",
                            "recordTime": now_ms - 5000,
                            "petId": 7,
                            "petName": "Mochi",
                            "params": '{"seconds":"01m10s"}',
                        },
                    ]
                }
            ]
        )
    )
    # A failing optional endpoint must not break the status.
    respx.post(f"{BASE}/device/feedingPlan/list").mock(return_value=httpx.Response(400))

    hub, store = Hub(), Store(":memory:")
    adapter = PetlibroAdapter(
        hub,
        store,
        PetlibroClient("e@x.com", "pw"),
        timezone="UTC",
        token_path=tmp_path / "token.txt",
    )
    await adapter.poll_once()

    feeder = hub.feeder("SN1")
    assert feeder and feeder.food_low is False and feeder.last_feed_portions == 2
    assert feeder.next_feed_at is None
    assert len(await store.feed_events("SN1", datetime(2000, 1, 1, tzinfo=UTC))) == 1
    assert (tmp_path / "token.txt").read_text() == "t"
    visits = await store.pet_visits("SN1", datetime(2000, 1, 1, tzinfo=UTC))
    assert [(v.pet_name, v.seconds) for v in visits] == [("Mochi", 70)]
    cursor = await store.get_state("petlibro:SN1:records_until")
    assert cursor and datetime.fromisoformat(cursor) == datetime.fromtimestamp(now_ms / 1000, UTC)

    # Second poll starts from the cursor (minus overlap), not 30 days back.
    await adapter.poll_once()
    work = [c for c in respx.calls if c.request.url.path.endswith("/workRecord/list")]
    start_ms = json.loads(work[-1].request.content)["startTime"]
    assert now_ms - start_ms <= 11 * 60 * 1000
    assert len(await store.pet_visits("SN1", datetime(2000, 1, 1, tzinfo=UTC))) == 1


class FakeRobot(SimpleNamespace):
    def on(self, _event, callback):
        self.callback = callback
        return lambda: None


class FakeAccount:
    def __init__(self, robot, **kwargs):
        self.robot = robot
        self.kwargs = kwargs
        self.session = SimpleNamespace(tokens={"id_token": "x"})

    async def connect(self, **kwargs):
        self.connect_kwargs = kwargs

    def get_robots(self, _cls):
        return [self.robot]

    async def disconnect(self):
        pass


async def test_litterrobot_connect_subscribes_and_pushes(tmp_path):
    now = datetime.now(UTC)
    robot = FakeRobot(
        id="1",
        name="Box",
        model="Litter-Robot 4",
        serial="LR4",
        status=LRStatus.READY,
        status_code="RDY",
        is_online=True,
        is_on=True,
        waste_drawer_level=10.0,
        is_waste_drawer_full=False,
        litter_level=90.0,
        pet_weight=0,
        cycle_count=1,
        is_sleeping=False,
        last_seen=now,
    )
    accounts = []

    def factory(**kwargs):
        accounts.append(FakeAccount(robot, **kwargs))
        return accounts[-1]

    hub, store = Hub(), Store(":memory:")
    adapter = LitterRobotAdapter(
        hub, store, "u", "p", TokenFile(tmp_path / "tok.json"), account_factory=factory
    )
    await adapter._connect()
    assert accounts[0].connect_kwargs["subscribe_for_updates"] is True
    assert hub.litter_box("1").waste_drawer_percent == 10.0

    robot.waste_drawer_level = 55.0
    robot.callback()  # simulate a websocket push
    assert hub.litter_box("1").waste_drawer_percent == 55.0
    assert (tmp_path / "tok.json").exists()


async def test_litterrobot_bad_login_backs_off_30_minutes(tmp_path, monkeypatch):
    import asyncio

    from pylitterbot.exceptions import LitterRobotLoginException

    from cat_dash.adapters import litterrobot as lr

    class BadAccount(FakeAccount):
        async def connect(self, **kwargs):
            raise LitterRobotLoginException("Incorrect username or password.")

    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        raise asyncio.CancelledError

    monkeypatch.setattr(lr.asyncio, "sleep", fake_sleep)
    hub = Hub()
    adapter = LitterRobotAdapter(
        hub,
        Store(":memory:"),
        "u",
        "p",
        TokenFile(tmp_path / "t.json"),
        account_factory=lambda **kw: BadAccount(None, **kw),
    )
    with contextlib.suppress(asyncio.CancelledError):
        await adapter._run()
    assert sleeps == [1800]
    assert "Login failed" in hub.snapshot().errors["litterrobot"]
