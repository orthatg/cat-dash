"""HTTP client: login, token handling, response envelope, endpoints."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime
from typing import Any

import httpx

_LOGGER = logging.getLogger(__name__)

API_HOSTS = {"US": "https://api.us.petlibro.com"}
# The API rejects unknown apps; these mimic the Android app.
APP_ID = 1
APP_SN = "c35772530d1041699c87fe62348507a8"
APP_VERSION = "1.3.45"

CODE_OK = 0
CODE_NOT_LOGGED_IN = 1009
CODE_BAD_PASSWORD = 1102


class PetlibroError(Exception):
    """API call failed."""


class PetlibroAuthError(PetlibroError):
    """Login rejected (bad email/password, or account not created in the app)."""


def hash_password(password: str) -> str:
    return hashlib.md5(password.encode("utf-8")).hexdigest()  # noqa: S324 - API requirement


class PetlibroClient:
    def __init__(
        self,
        email: str,
        password: str,
        *,
        region: str = "US",
        timezone: str = "America/Chicago",
        token: str | None = None,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        if region not in API_HOSTS:
            raise ValueError(f"Unsupported Petlibro region {region!r}; known: {list(API_HOSTS)}")
        self._email = email
        self._password_hash = hash_password(password)
        self._region = region
        self._timezone = timezone
        self.token = token
        self._http = http or httpx.AsyncClient(timeout=20)
        self._base = API_HOSTS[region]
        self._login_lock = asyncio.Lock()

    async def aclose(self) -> None:
        await self._http.aclose()

    def _headers(self) -> dict[str, str]:
        headers = {
            "source": "ANDROID",
            "language": "EN",
            "timezone": self._timezone,
            "version": APP_VERSION,
            "Content-Type": "application/json",
        }
        if self.token:
            headers["token"] = self.token
        return headers

    async def login(self) -> str:
        async with self._login_lock:
            body = {
                "appId": APP_ID,
                "appSn": APP_SN,
                "country": self._region,
                "email": self._email,
                "password": self._password_hash,
                "phoneBrand": "",
                "phoneSystemVersion": "",
                "timezone": self._timezone,
                "thirdId": None,
                "type": None,
            }
            self.token = None
            data = await self._request("/member/auth/login", body, allow_relogin=False)
            token = data.get("token") if isinstance(data, dict) else None
            if not isinstance(token, str) or not token:
                raise PetlibroAuthError("Petlibro login returned no token")
            self.token = token
            _LOGGER.info("Petlibro login ok")
            return token

    async def _request(self, path: str, body: dict, *, allow_relogin: bool = True) -> Any:
        response = await self._send(path, body)
        payload = _json(response)
        code = payload.get("code")

        if code == CODE_NOT_LOGGED_IN and allow_relogin:
            await self.login()
            payload = _json(await self._send(path, body))
            code = payload.get("code")

        if code == CODE_BAD_PASSWORD:
            raise PetlibroAuthError("Petlibro rejected the email/password")
        if code == CODE_NOT_LOGGED_IN:
            raise PetlibroAuthError("Petlibro session not logged in")
        if code != CODE_OK:
            raise PetlibroError(f"{path}: code {code}: {payload.get('msg')}")
        return payload.get("data")

    async def _send(self, path: str, body: dict) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = await self._http.post(
                    self._base + path, json=body, headers=self._headers()
                )
            except httpx.TransportError as err:
                last_error = err
            else:
                if response.status_code < 500:
                    if response.status_code != 200:
                        raise PetlibroError(f"{path}: HTTP {response.status_code}")
                    return response
                last_error = PetlibroError(f"{path}: HTTP {response.status_code}")
            await asyncio.sleep(2 * (attempt + 1))
        raise PetlibroError(f"{path}: request failed after retries: {last_error}")

    async def ensure_login(self) -> None:
        if not self.token:
            await self.login()

    # --- endpoints ---
    async def _device_call(self, path: str, serial: str) -> Any:
        await self.ensure_login()
        return await self._request(path, {"id": serial, "deviceSn": serial})

    async def list_devices(self) -> list[dict]:
        await self.ensure_login()
        data = await self._request("/device/device/list", {})
        return data if isinstance(data, list) else []

    async def real_info(self, serial: str) -> dict:
        return await self._device_call("/device/device/realInfo", serial) or {}

    async def data_real_info(self, serial: str) -> dict:
        return await self._device_call("/data/data/realInfo", serial) or {}

    async def base_info(self, serial: str) -> dict:
        return await self._device_call("/device/device/baseInfo", serial) or {}

    async def grain_status(self, serial: str) -> dict:
        return await self._device_call("/device/data/grainStatus", serial) or {}

    async def feeding_plans(self, serial: str) -> Any:
        return await self._device_call("/device/feedingPlan/list", serial)

    async def feeding_plan_today(self, serial: str) -> Any:
        return await self._device_call("/device/feedingPlan/todayNew", serial)

    async def attribute_settings(self, serial: str) -> dict:
        return await self._device_call("/device/setting/getAttributeSetting", serial) or {}

    async def work_records(
        self, serial: str, start: datetime, end: datetime, size: int = 25
    ) -> Any:
        await self.ensure_login()
        body = {
            "deviceSn": serial,
            "startTime": int(start.timestamp() * 1000),
            "endTime": int(end.timestamp() * 1000),
            "size": size,
            "type": ["GRAIN_OUTPUT_SUCCESS"],
        }
        return await self._request("/device/workRecord/list", body)

    async def bound_pets(self, serial: str) -> Any:
        await self.ensure_login()
        return await self._request("/device/devicePetRelation/getBoundPets", {"deviceSn": serial})

    async def wear_list(self, serial: str) -> Any:
        await self.ensure_login()
        return await self._request(
            "/device/device/wear/wearListV2", {"deviceSn": serial, "type": 1}
        )


def _json(response: httpx.Response) -> dict:
    try:
        payload = response.json()
    except ValueError as err:
        raise PetlibroError(f"Non-JSON response from {response.request.url}") from err
    if not isinstance(payload, dict):
        raise PetlibroError("Unexpected response shape")
    return payload
