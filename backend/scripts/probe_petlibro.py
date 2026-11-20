"""Log in to Petlibro and dump raw (redacted) responses for every endpoint we use.

    uv run python scripts/probe_petlibro.py

Output goes to data/probe/petlibro/ (git-ignored). Compare the fields against
src/cat_dash/petlibro/parse.py and the Petlibro app.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from redact import dump

from cat_dash.config import Settings
from cat_dash.petlibro import PetlibroClient, PetlibroError
from cat_dash.petlibro.parse import feeder_status

OUT = Path("data/probe/petlibro")


async def main() -> int:
    settings = Settings()
    if not settings.petlibro_configured:
        print("Set CATDASH_PETLIBRO_EMAIL / CATDASH_PETLIBRO_PASSWORD in backend/.env")
        return 1
    client = PetlibroClient(
        settings.petlibro_email or "",
        settings.petlibro_password.get_secret_value() if settings.petlibro_password else "",
        region=settings.petlibro_region,
        timezone=settings.timezone,
    )
    try:
        await client.login()
        devices = await client.list_devices()
        dump(OUT, "device_list", devices)
        now = datetime.now(UTC)
        for device in devices:
            serial = device.get("deviceSn")
            print(f"Device {device.get('productIdentifier')} / {device.get('productName')}")
            calls = {
                "base_info": client.base_info(serial),
                "real_info": client.real_info(serial),
                "data_real_info": client.data_real_info(serial),
                "grain_status": client.grain_status(serial),
                "work_records": client.work_records(serial, now - timedelta(days=30), now),
                "feeding_plans": client.feeding_plans(serial),
                "feeding_plan_today": client.feeding_plan_today(serial),
                "attribute_settings": client.attribute_settings(serial),
                "bound_pets": client.bound_pets(serial),
                "wear_list": client.wear_list(serial),
            }
            results = {}
            for name, call in calls.items():
                try:
                    results[name] = await call
                    dump(OUT / "device", name, results[name])
                except PetlibroError as err:
                    print(f"  {name}: FAILED {err}")
            status = feeder_status(
                device,
                real_info=results.get("real_info") or {},
                data_real_info=results.get("data_real_info") or {},
                grain_status=results.get("grain_status") or {},
                work_records=results.get("work_records"),
                plans=results.get("feeding_plans"),
                now=now,
                timezone=settings.timezone,
            )
            print("\nParsed status:\n" + status.model_dump_json(indent=2))
    finally:
        await client.aclose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
