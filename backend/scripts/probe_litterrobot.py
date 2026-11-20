"""Log in to Whisker (Litter-Robot), dump raw (redacted) robot data and history,
then listen for live websocket updates for a while.

    uv run python scripts/probe_litterrobot.py [listen_seconds]

Output goes to data/probe/litterrobot/ (git-ignored). Start a clean cycle from
the app or the robot while it listens to see a push update arrive.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pylitterbot import Account, LitterRobot4
from pylitterbot.event import EVENT_UPDATE
from redact import dump

from cat_dash.adapters.litterrobot import event_from_activity, status_from_robot
from cat_dash.config import Settings

OUT = Path("data/probe/litterrobot")


async def main(listen_seconds: int) -> int:
    settings = Settings()
    if not settings.litterrobot_configured:
        print(
            "Set CATDASH_LITTERROBOT_USERNAME in backend/.env, then: "
            "uv run cat-dash-secrets set litterrobot"
        )
        return 1
    account = Account(robot_types=[LitterRobot4])
    try:
        await account.connect(
            username=settings.litterrobot_username,
            password=settings.litterrobot_password_value(),
            load_robots=True,
            subscribe_for_updates=True,
        )
        robots = account.get_robots(LitterRobot4)
        print(f"{len(robots)} Litter-Robot 4(s)")
        for robot in robots:
            print(f"\n{robot}")
            dump(OUT, f"robot_{robot.id}", robot.to_dict())
            print(status_from_robot(robot).model_dump_json(indent=2))
            history = await robot.get_activity_history(
                limit=200, start=datetime.now(UTC) - timedelta(days=14)
            )
            dump(
                OUT,
                f"activity_{robot.id}",
                [event_from_activity(robot.id, a).model_dump(mode="json") for a in history],
            )
            insight = await robot.get_insight(days=30)
            print(insight)

            def on_update(r=robot) -> None:
                s = status_from_robot(r)
                print(
                    f"[{datetime.now():%H:%M:%S}] PUSH {r.name}: {s.status_code} "
                    f"drawer={s.waste_drawer_percent}% litter={s.litter_level_percent}%"
                )

            robot.on(EVENT_UPDATE, on_update)
        print(f"\nListening for live updates for {listen_seconds}s (Ctrl+C to stop)...")
        await asyncio.sleep(listen_seconds)
    finally:
        await account.disconnect()
    return 0


if __name__ == "__main__":
    seconds = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    sys.exit(asyncio.run(main(seconds)))
