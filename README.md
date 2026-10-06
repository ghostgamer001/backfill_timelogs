# log-backfill

Scratch repo for two things:

1. `backfill.py` — a one-off script that filled in missing Log entries for
   Aug–Sep 2026 (see `NOTES.md` for the full writeup: API reverse-engineering,
   token handling, how descriptions were sourced). Not meant to be run again
   regularly — it was a single historical cleanup, not an ongoing workflow.
2. The thing this README is actually about: a **personal time/activity
   tracker**, built from scratch, whose real purpose is cutting down
   procrastination.

## Why a new tool instead of just using Log

Logger (and tools like it) logbut it does nothing to catch
procrastination in the moment — there's no feedback loop. The point of this
project is a tool that observes actual behavior locally (what's running, what
has focus, for how long) and surfaces it back to you in real time, so slipping
into a distraction is visible immediately instead of being discovered (or
glossed over) at the end of the day.

## Planned scope

### Phase 1 — passive tracking
- Background process that polls the active/foreground window on an interval
  (Windows: `psutil` + `win32gui`/`pygetwindow`).
- Logs `(timestamp, process_name, window_title, duration)` to a local SQLite
  file. No network calls, no external service — everything stays on disk.
- Simple daily rollup: time spent per app/category.

### Phase 2 — categorization + a "discipline" view
- A config mapping process/window names to categories (`work`, `distraction`,
  `neutral`).
- A small CLI or local dashboard: today's focus time vs. distraction time,
  streaks, a weekly trend.

### Phase 3 — soft intervention
- Nudges when a distracting app has been foregrounded past a threshold
  (notification, not a hard block, to start).
- Optional hard mode: block/kill-list for specific apps during defined work
  hours, with an escape hatch that requires deliberate friction to override
  (e.g. editing a config file + restart) rather than a single click — the
  friction is the point.

### Phase 4 — review loop
- End-of-day/week summary so the data actually gets looked at, not just
  collected. This is the part self-tracking tools usually skip, and it's the
  part that matters for actually changing behavior.

## Non-goals

- Not a replacement for Logger  time tracking — this is a personal,
  local-only tool for self-discipline, separate from anything reported
  elsewhere.
- Not a surveillance/monitoring tool for anyone but yourself — single-user,
  local data, no remote sync planned.

## Files

- `backfill.py` / `NOTES.md` — the historical Logger cleanup (reference only).
- `config.json` — gitignored; holds credentials, never commit.
- (planned) `tracker/` — the new local tracking tool, once started.
