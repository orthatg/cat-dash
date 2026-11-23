# Roomba i7+ local API: findings and example response

Example: [`example-state.real-redacted.json`](example-state.real-redacted.json) is a REAL
capture (i7+, firmware `lewis+22.52.10`, 2026-11-23). Identity, network, map and serial
fields are redacted (`backend/scripts/probe_roomba.py` does this; re-run it any time).
Raw dumps go to the git-ignored `backend/data/probe/roomba/`.

## Transport
- Local MQTT 3.1.1 over TLS, robot IP port **8883**, self-signed cert (not verified).
- Client id and username = **BLID**; password = robot password. Subscribe `#`.
- State arrives as `{"state":{"reported":{...}}}` deltas that we deep-merge until
  `batPct` and `cleanMissionStatus` are present (a few seconds). Confirmed working with the
  relaxed-cipher TLS context in `client.py`.
- **One local connection at a time.** While connected the iRobot app falls back to cloud,
  so the server connects per request and disconnects (30 s cache, calls serialized).

## Does it push events?
**Yes.** The robot publishes its state on connect and whenever it changes, and republishes
periodically. We use the initial burst. A future "live" mode could hold the connection
open and relay changes over the SSE stream, at the cost of locking out the local app.

## Where each wanted value comes from (`state.reported.*`), verified on a real i7+
| Want | Field(s) |
|---|---|
| Battery | `batPct` |
| State | `cleanMissionStatus.phase` (seen: `charge`) and `.cycle` |
| Last ran | `cleanMissionStatus.mssnStrtTm` (epoch s, mission START: reliable). `mssnM` is minutes but resets to 0 once docked; `sqft` is not sent after a mission. `nMssn` = mission number. `lastCommand.time` is often null (`command` was `addrobotdone`), so it is only a fallback |
| Next scheduled | **`cleanSchedule2`**: list of `{enabled, type, start:{day:[0..6], hour, min}, cmdStr}`. Several entries and day sets are possible. Day 0 = Sunday (assumed iRobot convention; all 7 days were enabled so Sunday-first is not yet proven). The legacy `cleanSchedule` `{cycle,h,m}` is still parsed as a fallback |
| Errors/faults | `cleanMissionStatus.error` (0 = none), `.notReady`, `.condNotReady[]`, `bin.full`, `bin.present` |
| Lifetime counters (fun) | `bbmssn` (missions ok/cancelled/failed), `bbrun` (stuck, cliff, bump, scrubs, evacs), `bbchg`/`bbchg3` (battery/charging), `bbswitch`, `bbsys` (uptime), `runtimeStats` (total hours/area), `bbpause`, `bbnav` |
| Wi-Fi quality | **Not present** on this firmware (no `signal` block), so the API returns null |
| Pose/position | Not present |

Other fields worth knowing: `connected`, `dock.state`, `evacAllowed`, `schedHold`,
`timezone`, `cap` (capabilities), `mssnNavStats`, `batInfo` (redacted: has serials).

## Still unknown
- Error code to text table (only "Robot error N" is shown).
- Real `phase` values other than `charge` (`run`, `hmUsrDock`, `stuck`... come from docs).
- Whether Sunday really is day 0 in `cleanSchedule2` (needs a non-daily schedule).
- Whether a mission still shows `mssnM`/`sqft` while running (expected yes).

## Setup
1. `uv sync`, set `CATDASH_ROOMBA_HOST` and `CATDASH_ROOMBA_BLID` in `backend/.env`.
2. `uv run cat-dash-secrets set roomba` (password into the Keychain). To obtain it, with the
   robot on its dock hold HOME until it plays tones, then from `backend/` run
   `uvx --from "roombapy[cli]" roombapy discover <real IP>`; close the iRobot app first.
3. `PYTHONPATH=scripts uv run python scripts/probe_roomba.py` to capture and print status.
