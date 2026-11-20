# Roadmap

## Next: interface refinement
- Polish the tile layout from the `first-pass` tag; tune spacing, sizes and phone layout.

## Next: alerts
Show alerts on the dashboard first; push notifications can come later.

| Alert | Trigger (starting point, make configurable) |
|---|---|
| No clean cycle for too long | No clean cycle in 6 h while cats are visiting (the robot may be stuck or asleep) |
| Drawer high | Drawer at or above the usual emptying level (~82%), or the forecast "empty by" date has passed |
| Drawer full | Robot reports full, or drawer ≥ 100% |
| Litter low | `litter_level_state` isn't OPTIMAL |
| Robot fault / offline | Status in the fault set, or offline |
| Feeder | Food low, blocked, offline, desiccant overdue |

Notes: build it as a small rules module over the existing status (`hub`), give each alert a
clear/raised state with a timestamp so it doesn't flap, and add an `/api/alerts` endpoint.

## Later: Roomba clean-up after litter box use
Goal: after a cat uses the box, send the Roomba to vacuum around it (litter tracking).

- **Trigger:** the Litter-Robot's live updates already arrive within seconds (cat detected →
  clean cycle complete). Fire after the clean cycle completes, not on cat detected.
- **Guards:** wait a few minutes after the visit; no new cat detected in the meantime;
  at most one run per N hours; quiet hours (night); skip if the Roomba is already running or docked
  with a low battery.
- **Target:** a spot clean or a single room/zone clean of the litter area, not a full-house run.
- **Integration options to evaluate:** `roombapy` (local MQTT, needs the robot's BLID and
  password; used by Home Assistant), or iRobot's cloud via Home Assistant. Prefer local control.
- **Learn first:** log the would-be triggers for a week before letting it actually run.
