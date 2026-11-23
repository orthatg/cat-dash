import asyncio

import pytest

from cat_dash.roomba import RoombaAuthError, RoombaService, RoombaTimeout

REPORTED = {"batPct": 80, "cleanMissionStatus": {"phase": "charge", "error": 0}}


class FakeRoombaClient:
    def __init__(self, results=None, delay=0.0):
        self.results = list(results or [REPORTED])
        self.calls: list[float] = []
        self.active = 0
        self.max_active = 0
        self.delay = delay

    async def fetch_state(self, timeout: float = 15.0):
        self.calls.append(timeout)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            result = self.results.pop(0) if len(self.results) > 1 else self.results[0]
            if isinstance(result, Exception):
                raise result
            return result
        finally:
            self.active -= 1


def service(client, **kw):
    return RoombaService(client, device_id="BLID1", timezone="UTC", **kw)


async def test_status_parses_and_passes_timeout():
    client = FakeRoombaClient()
    status = await service(client, timeout=7.0).status()
    assert status.device_id == "BLID1" and status.battery_percent == 80
    assert status.state == "charging"
    assert client.calls == [7.0]


async def test_cache_hit_within_window():
    client = FakeRoombaClient()
    svc = service(client, cache_seconds=30)
    first = await svc.status()
    second = await svc.status()
    assert len(client.calls) == 1
    assert first is second


async def test_refresh_bypasses_cache():
    client = FakeRoombaClient([REPORTED, {**REPORTED, "batPct": 55}])
    svc = service(client, cache_seconds=30)
    assert (await svc.status()).battery_percent == 80
    assert (await svc.status(refresh=True)).battery_percent == 55
    assert len(client.calls) == 2
    # refreshed value is what gets cached
    assert (await svc.status()).battery_percent == 55
    assert len(client.calls) == 2


async def test_cache_expires(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr("cat_dash.roomba.service.time.monotonic", lambda: clock[0])
    client = FakeRoombaClient([REPORTED, {**REPORTED, "batPct": 10}])
    svc = service(client, cache_seconds=30)
    await svc.status()
    clock[0] += 29
    assert (await svc.status()).battery_percent == 80
    clock[0] += 2
    assert (await svc.status()).battery_percent == 10
    assert len(client.calls) == 2


async def test_zero_cache_always_fetches():
    client = FakeRoombaClient()
    svc = service(client, cache_seconds=0)
    await svc.status()
    await svc.status()
    assert len(client.calls) == 2


async def test_errors_propagate_and_are_not_cached():
    client = FakeRoombaClient([RoombaTimeout("slow"), RoombaAuthError("bad"), REPORTED])
    svc = service(client)
    with pytest.raises(RoombaTimeout):
        await svc.status()
    with pytest.raises(RoombaAuthError):
        await svc.status()
    assert (await svc.status()).battery_percent == 80
    assert len(client.calls) == 3


async def test_error_after_success_does_not_wipe_or_serve_stale_on_refresh():
    client = FakeRoombaClient([REPORTED, RoombaTimeout("slow")])
    svc = service(client, cache_seconds=30)
    await svc.status()
    with pytest.raises(RoombaTimeout):
        await svc.status(refresh=True)
    # the earlier good status is still cached for normal reads
    assert (await svc.status()).battery_percent == 80


async def test_concurrent_calls_are_serialized():
    client = FakeRoombaClient(delay=0.01)
    svc = service(client, cache_seconds=0)
    await asyncio.gather(*(svc.status() for _ in range(4)))
    assert client.max_active == 1
    assert len(client.calls) == 4


async def test_concurrent_calls_share_cache():
    client = FakeRoombaClient(delay=0.01)
    svc = service(client, cache_seconds=30)
    results = await asyncio.gather(*(svc.status() for _ in range(4)))
    assert len(client.calls) == 1
    assert all(r is results[0] for r in results)
