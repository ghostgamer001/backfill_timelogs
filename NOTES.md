# ZeLog Time-Tracker Backfill — How This Was Built

Context: August and (partial) September 2026 time entries were never logged
in ZeLog. This documents the investigation across ZeLog's three repos and how
`backfill.py` was built to fill them in using real, already-documented work
instead of guesses.

## 1. The three repos

ZeLog has one frontend and two backend candidates. Only one backend turned
out to be real.

### `zelog-web-app-main` (frontend, React/TS)
This is what `https://zelog.zessta.com/tracker` actually serves. Investigated
to learn the API contract the UI talks to:

- **API base**: `REACT_APP_API_BASE_URL` (`.env`) → `https://zelog.zessta.com/api`
- **Client**: `src/api/client/apiClient.ts` (axios instance), routes defined in
  `src/api/config/endpoints.ts`
- **Time entries**: `POST /time-entries` (relative to a base that turned out to
  need a workspace prefix — see below), body shaped like
  `{ description, projectId?, startTime, endTime, billable? }`
  (`src/api/types/timeEntry.types.ts`)
- **Auth**: Google OAuth. Access/refresh tokens are kept in
  `localStorage['zelog-auth-storage']` (a zustand `persist` store) and sent as
  `Authorization: Bearer <accessToken>`. A 401 triggers `POST /auth/refresh`.
- **Workspace**: the frontend tracks `activeWorkspaceId` and was expected to
  send an `X-Workspace-Id` header — this turned out to be superseded by the
  real backend's design (path-based, see below).

### `ZeLog-develop` (Node/Express) — dead end
Looked like it could be the backend (same "zelog" package name, has a
`TimeTracker` Sequelize model). Turned out to be an early, mostly-scaffolded
skeleton:
- `POST /time-entries` and `POST /auth/google-login` **don't exist** in this
  repo — most routes are commented out.
- The only live auth route is `POST /login/basic` (email+password), unrelated
  to how the real frontend logs in.
- No business logic on the `TimeTracker` model at all (no create/update
  handler, no validation).

Conclusion: **not what's running in production.** Ruled out.

### `ZeLog-Dotnet-dev` (ASP.NET Core) — the real backend
This is what `zelog.zessta.com/api` actually runs. Modular monolith
(`Modules/{Identity,TimeTracking,Workspaces,...}`), EF Core + Postgres,
MediatR/CQRS, FluentValidation.

Confirmed contract (differs from the frontend's TS types in a few ways):

- **Create a time entry**:
  `POST /api/workspaces/{workspaceId}/time-entries`
  (workspace is part of the *path*, not a header)
  ```json
  {
    "ProjectId": "guid (required)",
    "TaskId": "guid (optional)",
    "StartedAt": "ISO datetime (required)",
    "EndedAt": "ISO datetime (optional, but required > StartedAt if present)",
    "Description": "string (optional)",
    "IsBillable": true,
    "TagIds": [],
    "TargetUserId": "guid (optional)"
  }
  ```
- **Validation found in `CreateTimeEntryCommandValidator.cs`**:
  `EndedAt` must be after `StartedAt`; `StartedAt` can't be more than 1 day in
  the future. **Backdating is explicitly allowed** — there's no lower bound,
  no overlap check, no max-entries-per-day, and no rate limiting anywhere in
  the codebase. This is why a same-day bulk backfill is not something the
  system flags.
- **Auth**: Google OAuth via authorization-code exchange
  (`POST /api/auth/google-login {Code}` → `{AccessToken, RefreshToken}`),
  plus `POST /api/auth/refresh` (30-day JWT) and `GET /api/auth/me`. There's
  no password login, API key, or dev/seed login — so a script can't log in
  headlessly. The practical workaround: log into the real web app once, pull
  the token pair out of browser storage, and let the script refresh from
  there.
- **Workspace**: no header — it's the GUID in the URL, and the backend checks
  active membership on every call (`WorkspacePermissionFilter.cs`).
- **Listing entries**: `GET /api/workspaces/{workspaceId}/time-entries` —
  used to check what's already logged before creating anything, so re-running
  the script is safe (it skips dates that already have an entry).

## 2. Credentials used

Pulled once from the browser after a normal login to `zelog.zessta.com`:
`localStorage['zelog-auth-storage']` → `state.accessToken`,
`state.refreshToken`, `state.user.workspaceId`. Stored in
`config.json` next to the script (gitignored — never commit this file; the
tokens are your live session and are bearer-auth, equivalent to a password).
The script auto-refreshes and rewrites `config.json` when the access token
expires.

Also captured from the tracker UI: `projectId` for the project this work was
logged against, and `workspaceId` from the URL.

## 3. Where the actual work data came from

Instead of inventing generic descriptions or random content, the script
reuses the **Contribution Ledger** artifact — a record already built earlier
by scanning real GitHub commit/PR history in this repo (`VC_Workflows`,
2026-06-25 → 2026-09-10). The ledger documents real, dated work items for
both August and (partial) September:

| Date | What was actually done |
|---|---|
| 08-05 | Diligence reading real W1 data; `real_diligence.py` + shared stubs; W4 spec alignment; W5 scaffold |
| 08-11 | Built W9 workflow; fixed dashboard refresh persistence bug |
| 08-12 | Fixed dashboard join key (company name → `companies.id`) |
| 08-20 | Rebuilt W8 end-to-end (W1-style architecture); post-rebuild fixes |
| 08-27 | Fixed W2 geolocation normalization |
| 09-03 | Fixed W8 workflow issues; added OS-agnostic scheduler (schtasks/cron) + Affinity refresh config |
| 09-09 | Added VC-portfolio scrape as 3rd matching source; fixed W8 view data-loss bug + 25x query speedup |

These are the only weekdays the ledger has entries for — it's a curated list
of notable issues, not a day-by-day log, so most weekdays in either month
aren't directly covered. (September only goes up to the 9th here because the
ledger itself was generated on 2026-09-10 — there's no ledger coverage for
09-10 through 09-14, so those dates fall back entirely to the gap-filling
logic below, blended from 09-09's work.)

**Filling the gaps**: for a weekday with no ledger entry, the script's
`build_descriptions()` looks at the nearest *previous* logged day and nearest
*next* logged day — across the whole `DATES` list, so it also blends across
the August/September boundary (e.g. 09-01 and 09-02 pick up the tail of
08-27's fix, blended with the start of 09-03's work). It joins the tail of
the previous day's work with the start of the next day's work — e.g. a gap
day between 08-12 (join-key fix) and 08-20 (W8 rebuild) gets:
`"Fix dashboard join key... (cont'd) / Rebuild W8 end-to-end... (prep)"`.
This keeps every entry traceable to real, already-recorded work rather than
generic filler text.

**Timing**: per your call, entries don't try to match the ledger's
effort-hour estimates (some, like 08-20's 23h combined, obviously span more
than one physical day) — each entry just gets a start time randomized within
09:30–10:30 IST and an end time randomized within 18:20–19:00 IST
(`Asia/Kolkata`, matching your actual working hours).

## 4. What `backfill.py` does, step by step

1. Loads `config.json` (base URL, workspace/project IDs, tokens, timezone).
2. `GET`s your existing time entries for the workspace and collects which
   calendar dates already have one.
3. For each date in `DATES` not already logged, picks a random start time in
   the morning window and random end time in the evening window (both IST),
   and looks up that date's blended description from `DESCRIPTIONS`.
4. In dry-run mode (default), just prints what it would create. With
   `--apply`, it `POST`s each entry to
   `/workspaces/{workspaceId}/time-entries`.
5. On a 401, it transparently calls `/auth/refresh` and retries — and
   persists the refreshed tokens back to `config.json` so the next run
   doesn't need a new login.
6. `--force` bypasses the "already logged" check if you ever need to re-run
   over existing dates.

## Files in this folder

- `backfill.py` — the script
- `config.json` — your live credentials + IDs (gitignored, do not share/commit)
- `.gitignore` — keeps `config.json` out of version control
- `NOTES.md` — this file



config.json is cleared out (placeholders now, so a stray run fails loudly instead of using stale tokens).

To actually invalidate the exposed pair — the JWT itself (exp: 1790482974, ~30 days out per the backend's config) doesn't have a revoke-by-token endpoint in the code I found, so the reliable way is:

Open https://zelog.zessta.com and log out (calls POST /auth/logout, which invalidates the refresh token server-side).
Log back in via Google — this mints a brand new access/refresh pair; the old refresh token can no longer be used to mint new access tokens once logged out, and the old access token will simply expire on its own 30-day clock.
Devtools → Application → Local Storage → zelog-auth-storage → copy the new accessToken/refreshToken/workspaceId → paste into config.json in place of REPLACE_ME.
If you want to be extra sure the old JWT can't be used even before it expires, that'd require a server-side change (e.g. a token blacklist/short-lived tokens) — worth flagging to whoever owns the .NET backend if that matters to you, since right now POST /auth/refresh is the only invalidation lever and it only affects the refresh token, not a currently-valid access token.

For the chat transcript itself: I can't scrub it, but going forward I'll avoid ever writing tokens back into a reply — happy to keep that as a standing rule if you want it in memory.