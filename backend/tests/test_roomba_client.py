import asyncio
import ssl
import sys
import types

import pytest

from cat_dash.roomba import MqttRoombaClient, RoombaAuthError, RoombaError, RoombaTimeout
from cat_dash.roomba.client import is_usable, merge, tls_context


def test_merge_deep_and_overwrite():
    state = {"a": {"x": 1, "y": {"z": 1}}, "b": 1, "l": [1, 2]}
    merge(state, {"a": {"y": {"w": 2}}, "b": 2, "l": [3], "c": {"d": 1}})
    assert state == {"a": {"x": 1, "y": {"z": 1, "w": 2}}, "b": 2, "l": [3], "c": {"d": 1}}


def test_merge_replaces_dict_with_scalar_and_back():
    state = {"a": {"x": 1}}
    merge(state, {"a": 5})
    assert state == {"a": 5}
    merge(state, {"a": {"y": 1}})
    assert state == {"a": {"y": 1}}


def test_is_usable():
    assert not is_usable({})
    assert not is_usable({"batPct": 50})
    assert not is_usable({"cleanMissionStatus": {}})
    assert is_usable({"batPct": 50, "cleanMissionStatus": {}})


def test_tls_context_has_verification_off():
    ctx = tls_context()
    assert isinstance(ctx, ssl.SSLContext)
    assert ctx.verify_mode == ssl.CERT_NONE and ctx.check_hostname is False


# --- fake aiomqtt -------------------------------------------------------------


class FakeMessage:
    def __init__(self, payload):
        self.payload = payload


def install_fake_aiomqtt(monkeypatch, *, messages=(), enter_error=None, hang=False):
    mod = types.ModuleType("aiomqtt")

    class MqttError(Exception):
        pass

    class MqttCodeError(MqttError):
        def __init__(self, rc):
            super().__init__(f"rc={rc}")
            self.rc = rc

    class Client:
        instances: list = []

        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.subscribed = []
            Client.instances.append(self)

        async def __aenter__(self):
            if enter_error:
                raise enter_error(mod)
            return self

        async def __aexit__(self, *exc):
            return False

        async def subscribe(self, topic):
            self.subscribed.append(topic)

        @property
        def messages(self):
            async def gen():
                for m in messages:
                    yield m
                if hang:
                    await asyncio.Event().wait()

            return gen()

    mod.MqttError, mod.MqttCodeError, mod.Client = MqttError, MqttCodeError, Client
    monkeypatch.setitem(sys.modules, "aiomqtt", mod)
    return mod


def msg(text):
    return FakeMessage(text.encode())


async def test_collect_merges_deltas_until_usable(monkeypatch):
    mod = install_fake_aiomqtt(
        monkeypatch,
        messages=[
            msg('{"state":{"reported":{"batPct":70}}}'),
            msg("not json"),
            msg('{"other":1}'),
            msg('{"state":{"reported":{"cleanMissionStatus":{"phase":"run"}}}}'),
            msg('{"state":{"reported":{"batPct":1}}}'),  # never reached
        ],
    )
    state = await MqttRoombaClient("10.0.0.5", "BLID", "pw").fetch_state(5)
    assert state == {"batPct": 70, "cleanMissionStatus": {"phase": "run"}}
    kw = mod.Client.instances[0].kwargs
    assert kw["hostname"] == "10.0.0.5" and kw["port"] == 8883
    assert kw["username"] == "BLID" and kw["password"] == "pw"
    assert mod.Client.instances[0].subscribed == ["#"]


@pytest.mark.parametrize("rc", [4, 5, 134, 135])
async def test_auth_codes_raise_auth_error(monkeypatch, rc):
    install_fake_aiomqtt(monkeypatch, enter_error=lambda m: m.MqttCodeError(rc))
    with pytest.raises(RoombaAuthError):
        await MqttRoombaClient("h", "b", "p").fetch_state(5)


async def test_other_code_and_mqtt_errors_are_roomba_error(monkeypatch):
    install_fake_aiomqtt(monkeypatch, enter_error=lambda m: m.MqttCodeError(3))
    with pytest.raises(RoombaError) as exc:
        await MqttRoombaClient("h", "b", "p").fetch_state(5)
    assert not isinstance(exc.value, RoombaAuthError)
    install_fake_aiomqtt(monkeypatch, enter_error=lambda m: m.MqttError("down"))
    with pytest.raises(RoombaError):
        await MqttRoombaClient("h", "b", "p").fetch_state(5)


async def test_stream_ending_without_state_is_error(monkeypatch):
    install_fake_aiomqtt(monkeypatch, messages=[msg('{"state":{"reported":{"batPct":1}}}')])
    with pytest.raises(RoombaError):
        await MqttRoombaClient("h", "b", "p").fetch_state(5)


async def test_fetch_state_times_out(monkeypatch):
    install_fake_aiomqtt(monkeypatch, hang=True)
    with pytest.raises(RoombaTimeout):
        await MqttRoombaClient("h", "b", "p").fetch_state(0.05)
