import hashlib
import json

import httpx
import pytest
import respx

from cat_dash.petlibro import PetlibroAuthError, PetlibroClient, PetlibroError

BASE = "https://api.us.petlibro.com"


def ok(data):
    return httpx.Response(200, json={"code": 0, "msg": None, "data": data})


@pytest.fixture
def client():
    return PetlibroClient("cat@example.com", "hunter2", timezone="America/Chicago")


@respx.mock
async def test_login_hashes_password_and_stores_token(client):
    route = respx.post(f"{BASE}/member/auth/login").mock(return_value=ok({"token": "abc"}))
    assert await client.login() == "abc"
    body = json.loads(route.calls[0].request.content)
    assert body["password"] == hashlib.md5(b"hunter2").hexdigest()
    assert body["email"] == "cat@example.com" and body["country"] == "US"
    assert route.calls[0].request.headers["source"] == "ANDROID"


@respx.mock
async def test_device_call_sends_token_and_serial(client):
    respx.post(f"{BASE}/member/auth/login").mock(return_value=ok({"token": "abc"}))
    route = respx.post(f"{BASE}/device/device/realInfo").mock(
        return_value=ok({"surplusGrain": True})
    )
    assert await client.real_info("SN1") == {"surplusGrain": True}
    request = route.calls[0].request
    assert request.headers["token"] == "abc"
    assert json.loads(request.content) == {"id": "SN1", "deviceSn": "SN1"}


@respx.mock
async def test_relogin_on_expired_token(client):
    client.token = "stale"
    login = respx.post(f"{BASE}/member/auth/login").mock(return_value=ok({"token": "fresh"}))
    respx.post(f"{BASE}/device/data/grainStatus").mock(
        side_effect=[
            httpx.Response(200, json={"code": 1009, "msg": "not login"}),
            ok({"todayFeedingTimes": 2}),
        ]
    )
    assert await client.grain_status("SN1") == {"todayFeedingTimes": 2}
    assert login.call_count == 1 and client.token == "fresh"


@respx.mock
async def test_bad_password_raises_auth_error(client):
    respx.post(f"{BASE}/member/auth/login").mock(
        return_value=httpx.Response(200, json={"code": 1102, "msg": "bad"})
    )
    with pytest.raises(PetlibroAuthError):
        await client.login()


@respx.mock
async def test_other_error_code_raises(client):
    client.token = "abc"
    respx.post(f"{BASE}/device/device/list").mock(
        return_value=httpx.Response(200, json={"code": 5000, "msg": "boom"})
    )
    with pytest.raises(PetlibroError, match="5000"):
        await client.list_devices()
