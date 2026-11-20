# Device integration plan

Cat Dash shows status and charts for a **Litter-Robot 4** and **Petlibro One RFID**
feeders. Neither vendor has an official API, so each sits behind an adapter that maps
vendor data to the models in `backend/src/cat_dash/models.py`.

## Push vs poll

| Device | Live status | History |
|---|---|---|
| Litter-Robot 4 | **Push**: GraphQL websocket via `pylitterbot` (`subscribe_for_updates=True`; `robot.on(EVENT_UPDATE, cb)`, callback takes no args) | Pulled: `get_activity_history(limit, start)`, `get_insight(days)` |
| Petlibro One RFID | **Poll** every 60 s (no push channel known) | Pulled each poll from `workRecord/list`, only records since the last one seen |

## Litter-Robot 4 (`pylitterbot`, MIT, pinned 2025.9.0)

- Auth: Whisker account email/password via AWS Cognito; tokens refresh automatically.
  Tokens are persisted (`token_update_callback`) so restarts don't resend the password.
  A rejected login waits 30 minutes before retrying, to avoid locking the account.
- Status: `status`, `status_code`, `waste_drawer_level`, `is_waste_drawer_full`,
  `litter_level`, `pet_weight`, `cycle_count` (since drawer reset), `is_online`, `is_on`,
  `is_sleeping`, `last_seen`.
- History: activity entries are `Activity(timestamp, action)`. `action` is a
  `LitterBoxStatus` (for example `CCC` = clean cycle complete) or a string such as
  `"Pet Weight Recorded: 10.2 lbs"`. Without `start` the API returns only about 6 days.
- `pylitterbot`'s `emit()` swallows callback exceptions, so our callback logs its own.
- A pushed status change (for example, a cycle finishing) triggers a history pull
  20 s later, so "last clean cycle" and "last cat detected" stay current.

Verified against a live LR4 on 2026-11-20. An anonymized response is in
`backend/tests/fixtures/litterrobot/robot.json`, and the tests build a real
`LitterRobot4` from it.

- `pylitterbot`'s `cycle_count` is the **lifetime** odometer (`odometerCleanCycles`).
  Cycles since the drawer was emptied is the raw `DFINumberOfCycles`.
- Drawer: `DFILevelPercent` was 0 and the Whisker app showed "Empty" (no percentage),
  while `isDFIPartialFull` was true. Cat Dash follows the percentage, like the app:
  `waste_drawer_state` is empty (0) / partial / full (`isDFIFull` or 100). The
  `isDFIPartialFull` flag is ignored.
- **Drawer emptied** isn't logged and `DFINumberOfCycles` doesn't reset on emptying.
  Cat Dash reads the raw `DFILevelPercent` history (logged after each cycle; `pylitterbot`
  drops its value, so the GraphQL activity query is sent directly) and records an empty
  when the level falls to 5% or less from at least 30% (`backend/src/cat_dash/drawer.py`).
  Live: 6 empties in 30 days, about every 5.3 days or 52 cycles. Dips like 92→68 are ignored.
- **Which cat:** Whisker pet profiles (`Account.load_pets`) give each cat's weight
  (Zora about 5.4 lb, Maui about 14.7 lb), but per-pet weight history only reaches back
  about a week. Cat Dash assigns every box weight reading to the nearest profile
  (`backend/src/cat_dash/cats.py`); this matched Whisker on all 77 overlapping readings.
- `lastSeen` was 3 days stale on an online, active robot, so it was dropped.
- History volume is about 60 entries a day (about 1,850 for 30 days). The backfill uses
  limit 5000. Activity entries for `DFILevelPercent` carry no value in `pylitterbot`.
- Daily clean-cycle counts from the activity log match Whisker's own insight exactly.

## Petlibro One RFID (own client; reference: jjjonesjr33/petlibro, GPL-3.0, nothing copied)

Verified against two live PLAF301 feeders on 2026-11-20. Anonymized responses are
in `backend/tests/fixtures/petlibro/`.

- Host `https://api.us.petlibro.com`. Every call is a POST with JSON.
  Headers are `source: ANDROID`, `language: EN`, `timezone`, `version: 1.3.45`, `token`.
- Login: `/member/auth/login` with `email` and an MD5-hex `password`, plus fixed app fields.
  Response envelope `{code, msg, data}`: `0` = ok, `1009` = log in again (re-login once
  and retry), `1102` = bad password.
- Device calls send `{"id": sn, "deviceSn": sn}`: `/device/device/realInfo`,
  `/data/data/realInfo`, `/device/data/grainStatus`, `/device/feedingPlan/list`.
- **Work records** (`/device/workRecord/list`; `deviceSn`, `startTime`/`endTime` epoch ms, `size`):
  - The `type` filter is **ignored**. Every kind of record comes back, newest first:
    `GRAIN_OUTPUT_SUCCESS` (feeds), `DETECTION_EVENT` (cat visits),
    `GRAIN_OUTLET_BLOCK_REMOVED`, and others.
  - `size` up to at least 200 works. Older records come from moving `endTime` to just before
    the oldest one returned. With the old 25-record default, cat visits pushed feeds out
    after about a day.
  - Shape: days `{"recordTime": "2026/11/20", "dayOfWeek": 5, "workRecords": [...]}`;
    each record has `id`, `type`, `eventType`, `recordTime` (ms), `actualGrainNum`
    (feeds), `petId`/`petName`, and `params` (JSON string, for example `{"seconds":"02m05s"}`).
- **Food level: low/not-low only (decided).** `food_low = not realInfo.surplusGrain`.
- **Per-cat visits** (RFID): `DETECTION_EVENT` / `PET_IDENTIFY_LEAVE_EVENT_BIND_PET` with
  the cat's name and eating time. Stored and charted per cat per day.
- Device list (`/device/device/list`) has `name`, `productName`, `nextFeedingTime`,
  `nextFeedingQuantity`, `enableBatteryPercent`, `desiccantState`, and more.
- `repeatDay` is ISO weekdays (`"[7,1,2,3,4,5,6]"`; 1 = Mon, 7 = Sun).
- Battery: `electricQuantity` is `0` with `enableBatteryPercent: false`, so Cat Dash shows
  no percentage then. `batteryState` still says `"low"`, probably meaning no batteries
  are fitted and the feeder runs on the power adapter (`powerType: 1`).
- Desiccant: `remainingDesiccantDays` goes negative when overdue (`desiccantState: OVER_DUE`).
- Quantities are portions (1 portion = 1/12 cup, about 10 g).

## Still unverified

1. Litter-Robot live push: the websocket subscribes fine, but no push has been seen yet
   (nobody used the box during the 90 s probe).
2. Whether `grainOutletState == False` means a blockage (always `true` so far).
3. Whether Cat Dash's Petlibro login signs out the phone app (a separate account is in use).
4. Whether Whisker limits concurrent sessions (app + Cat Dash).

## Next

- Watch a live push arrive (run `scripts/probe_litterrobot.py 600` and use the box).
- Frontend: status cards from `/api/status` + `/api/stream`, charts from the history endpoints.
