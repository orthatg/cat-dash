# Device integration plan

Cat Dash shows status and charts for a **Litter-Robot 4** and a **Petlibro One RFID**
feeder. Neither vendor has an official API, so each sits behind an adapter that maps
vendor data to the models in `backend/src/cat_dash/models.py`.

## Push vs poll

| Device | Live status | History |
|---|---|---|
| Litter-Robot 4 | **Push**: GraphQL websocket via `pylitterbot` (`subscribe_for_updates=True`; `robot.on(EVENT_UPDATE, cb)`, callback takes no args) | Pulled: `get_activity_history(limit, start)`, `get_insight(days)` |
| Petlibro One RFID | **Poll** every 60 s (no push channel known) | Pulled with each poll from `workRecord/list` (max 25 records per call) |

## Litter-Robot 4 (`pylitterbot`, MIT, pinned 2025.9.0)

- Auth: Whisker account email/password via AWS Cognito; tokens refresh automatically.
  Tokens are persisted (`token_update_callback`) so restarts don't resend the password.
- Status: `status`, `status_code`, `waste_drawer_level`, `is_waste_drawer_full`,
  `litter_level`, `pet_weight`, `cycle_count` (since drawer reset), `is_online`, `is_on`,
  `is_sleeping`, `last_seen`.
- History: activity entries are `Activity(timestamp, action)`. `action` is a
  `LitterBoxStatus` (for example `CCC` = clean cycle complete) or a string such as
  `"Pet Weight Recorded: 10.2 lbs"`. Without `start` the API returns only about 6 days.
- `pylitterbot`'s `emit()` swallows callback exceptions, so our callback logs its own.

## Petlibro One RFID (own client; reference: jjjonesjr33/petlibro, GPL-3.0, nothing copied)

- Host `https://api.us.petlibro.com` (US works for all regions). Every call is a POST with JSON.
  Headers are `source: ANDROID`, `language: EN`, `timezone`, `version: 1.3.45`, `token`.
- Login: `/member/auth/login` with `email` and an MD5-hex `password`, plus fixed app fields.
  Response envelope `{code, msg, data}`: `0` = ok, `1009` = log in again (re-login once
  and retry), `1102` = bad password.
- Device calls send `{"id": sn, "deviceSn": sn}`: `/device/device/realInfo`,
  `/data/data/realInfo`, `/device/data/grainStatus`, `/device/feedingPlan/list`.
  `/device/workRecord/list` takes `deviceSn`, `startTime`/`endTime` in epoch ms, `size`,
  and `type: ["GRAIN_OUTPUT_SUCCESS"]`.
- **Food level: low/not-low only (decided).** `food_low = not realInfo.surplusGrain`.
- Other fields: today's totals (`grainStatus.todayFeedingQuantity/Times`,
  `todayEatingTimes`), last feed (`workRecord.recordTime`, `actualGrainNum`), next feed
  (computed from `executionTime`, `repeatDay`, `grainNum`), battery
  (`electricQuantity`), `online`, problems (`barnDoorError`, `grainOutletState`,
  `exceptionMessage`), `remainingDesiccantDays`.
- Quantities are portions (1 portion = 1/12 cup, about 10 g).

## Still unverified (check with `scripts/probe_*.py` once credentials are in)

1. Petlibro field names and response shapes on a real One RFID, especially the
   work-record nesting and whether `grainOutletState == False` really means a blockage.
2. `repeatDay` numbering (assumed ISO 1=Mon..7=Sun; empty = every day).
3. Device name key in the Petlibro device list (`name`/`deviceName`/`nickName` tried).
4. Petlibro per-pet RFID data (`getBoundPets`, `wearListV2`): dumped by the probe, not used yet.
5. Whether Cat Dash's Petlibro login signs out the phone app (a second shared account avoids it).
6. Whether Whisker limits concurrent sessions (app + Cat Dash).

## Next

- Run the probes, fix parsing against real dumps, and save redacted dumps as test fixtures.
- Frontend: status cards from `/api/status` + `/api/stream`, charts from the history endpoints.
