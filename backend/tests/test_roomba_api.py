import pytest
from fastapi.testclient import TestClient

from cat_dash.app import create_app
from cat_dash.config import Settings
from cat_dash.hub import Hub
from cat_dash.roomba import RoombaAuthError, RoombaError, RoombaService, RoombaTimeout
from cat_dash.store import Store


class FakeRoombaClient:
    def __init__(self, result=None):
        self.result = result or {
            "batPct": 64,
            "cleanMissionStatus": {"phase": "run", "cycle": "quick", "error": 0},
        }
        self.calls = 0

    async def fetch_state(self, timeout: float = 15.0):
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("HOST", "BLID", "PASSWORD"):
        monkeypatch.delenv(f"CATDASH_ROOMBA_{name}", raising=False)


def make_client(client_fake=None, **kw):
    service = None
    if client_fake is not None:
        service = RoombaService(client_fake, device_id="BLID1", timezone="UTC", cache_seconds=30)
    app = create_app(
        Settings(_env_file=None, timezone="UTC"),
        store=Store(":memory:"),
        hub=Hub(),
        adapters=[],
        roomba=service,
        **kw,
    )
    return TestClient(app)


def test_503_when_not_configured():
    with make_client() as http:
        r = http.get("/api/roomba/status")
        assert r.status_code == 503
        assert http.get("/api/status").json()["configured"]["roomba"] is False


def test_200_when_configured():
    fake = FakeRoombaClient()
    with make_client(fake) as http:
        r = http.get("/api/roomba/status")
        assert r.status_code == 200
        body = r.json()
        assert body["device_id"] == "BLID1"
        assert body["battery_percent"] == 64
        assert body["state"] == "cleaning" and body["cycle"] == "quick"
        assert body["schedule"] == [] and body["next_scheduled_at"] is None
        assert http.get("/api/status").json()["configured"]["roomba"] is True


def test_refresh_param_passed_through():
    fake = FakeRoombaClient()
    with make_client(fake) as http:
        http.get("/api/roomba/status")
        http.get("/api/roomba/status")
        assert fake.calls == 1
        http.get("/api/roomba/status?refresh=true")
        assert fake.calls == 2
        http.get("/api/roomba/status?refresh=false")
        assert fake.calls == 2


def test_auth_error_is_502_mentioning_credentials():
    with make_client(FakeRoombaClient(RoombaAuthError("nope"))) as http:
        r = http.get("/api/roomba/status")
        assert r.status_code == 502
        assert "credentials" in r.json()["detail"].lower()


def test_timeout_is_504():
    with make_client(FakeRoombaClient(RoombaTimeout("took too long"))) as http:
        r = http.get("/api/roomba/status")
        assert r.status_code == 504
        assert "took too long" in r.json()["detail"]


def test_other_roomba_error_is_502():
    with make_client(FakeRoombaClient(RoombaError("boom"))) as http:
        r = http.get("/api/roomba/status")
        assert r.status_code == 502
        assert "boom" in r.json()["detail"]


def test_errors_are_not_cached_across_requests():
    fake = FakeRoombaClient(RoombaTimeout("slow"))
    with make_client(fake) as http:
        assert http.get("/api/roomba/status").status_code == 504
        fake.result = {"batPct": 1, "cleanMissionStatus": {"phase": "charge"}}
        assert http.get("/api/roomba/status").status_code == 200


def test_app_builds_roomba_from_settings(monkeypatch):
    # Configured settings (env password) build a real service without connecting.
    settings = Settings(
        _env_file=None,
        timezone="UTC",
        roomba_host="10.0.0.5",
        roomba_blid="ABC123",
        roomba_password="pw",
    )
    app = create_app(settings, store=Store(":memory:"), hub=Hub(), adapters=[])
    with TestClient(app) as http:
        assert http.get("/api/status").json()["configured"]["roomba"] is True
