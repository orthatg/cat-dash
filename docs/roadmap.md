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

## Next: refresh rates, change-only pushes and manual refresh
Do this once the rings-and-drawings design is settled.

**Today:** the hub pushes the whole dashboard snapshot over SSE on every device update, even
when nothing changed. The Petlibro poll alone sends one every 60 s. The Roomba isn't on the
stream; the page fetches it every 60 s. Rates are in `config.py`:
`petlibro_poll_seconds` (60), `litterrobot_history_poll_seconds` (900) and
`roomba_cache_seconds` (30).

### Refresh rates
- Review each source's rate (Litter-Robot push and history, Petlibro, Roomba) and make each
  one configurable. Slow them where the data barely moves; each poll costs vendor API calls and
  carries account risk.
- Show the current rates somewhere the user can see them (for example the History footer).

### Push only what changed
- Compare each new status with the last one sent, ignoring timestamp-only fields (`fetched_at`,
  `updated_at`, and so on).
- If nothing changed, send a small "unchanged" message instead of the full data:
  `{ "unchanged_since": <timestamp1>, "checked_at": <timestamp2> }`. `unchanged_since` is when
  the data last changed; `checked_at` is the most recent check.
- If something changed, send only the changed device (litter box, feeder or Roomba) with its
  id, not the whole snapshot.
- Applies to the SSE stream and to the REST endpoints (an `If-None-Match`/ETag or `since`
  parameter can return 304 or an "unchanged" body).

### "Time since" labels
- The header and each card show "Updated 3 min ago" / "Checked 20 s ago", not a clock time.
  Keep them ticking on the client (no server push needed to age them).
- Hovering (or long-pressing on a phone) shows a tooltip with the full date and time of both
  the last change and the last check.

### Manual refresh
Options considered:
1. **One refresh icon for the whole page.** Simple. It must still update only what changed
   (no full re-render), so the rings don't jump or flicker.
2. **One refresh per source:** litter box (drawer, litter, cleaning), food (the cat/feeder
   cards) and Roomba (its row in the Cleaning card). It refreshes only what's stale, and a
   slow Roomba (up to ~15 s) doesn't hold up the others.

**Leaning toward 2**, with a small icon in each card's header that spins while loading. A
long-press or the header could still offer "refresh all". Either way:
- Add backend endpoints that force a fresh read per source, for example
  `POST /api/refresh/{litter|feeders|roomba}`, rate-limited so a burst of clicks makes one
  vendor call.
- Results come back through the normal stream as change-only updates; the client patches just
  the affected cards (keep DOM nodes, update text and ring arcs in place).
- If the refresh finds nothing new, briefly show "No change since 10:42 AM", using the same
  unchanged message as above.

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
