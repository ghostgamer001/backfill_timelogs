"""
Backfill missing Log time entries for days you actually worked but forgot to log.

Usage:
    python backfill.py                # dry run, just prints what would be created
    python backfill.py --apply        # actually creates the entries
    python backfill.py --apply --force  # also create entries on days that already have one

Edit DATES / DESCRIPTION below before running.
"""
import argparse
import json
import random
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

CONFIG_PATH = Path(__file__).parent / "config.json"

# --- Days you actually worked ---
DATES = [
    # August 2026
    "2026-08-05", "2026-08-06", "2026-08-07",
    "2026-08-10", "2026-08-11", "2026-08-12", "2026-08-13", "2026-08-14",
    "2026-08-17", "2026-08-18", "2026-08-19", "2026-08-20", "2026-08-21",
    "2026-08-24", "2026-08-25", "2026-08-26", "2026-08-27", "2026-08-28",
    "2026-08-31",
    # September 2026 (full month — all weekdays)
    "2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04",
    "2026-09-07", "2026-09-08", "2026-09-09", "2026-09-10", "2026-09-11",
    "2026-09-14", "2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18",
    "2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24", "2026-09-25",
    "2026-09-28", "2026-09-29", "2026-09-30",
]
IS_BILLABLE = True

# --- What you actually worked on, per the Contribution Ledger (real GitHub-derived record) ---
# Only dates with real logged items are listed; other dates get a description
# blended from the nearest previous/next logged day (see build_descriptions()).
LOGGED = {
    "2026-08-05": [
        "Fix diligence to read real W1 data — was using synthetic data; now reads W1's diligence output via a shared table.",
        "Add real_diligence.py + shared stubs — new diligence module; shared.py scaffolds added across W4/W5/W6/W9/W10.",
        "Improve W4 per spec (reference article) — brought W4 in line with the reference article.",
        "Scaffold initial W5 workflow — initial portfolio-monitoring workflow.",
    ],
    "2026-08-11": [
        "Build W9 workflow; fix dashboard refresh persistence bug — first working W9 (LP Newsletter) pipeline; "
        "fixed a state-loss bug on workflow refresh; cleaned up W2/W8 synthetic-data usage.",
    ],
    "2026-08-12": [
        "Fix dashboard join key — was joining on company name; switched to companies.id.",
    ],
    "2026-08-20": [
        "Rebuild W8 end-to-end (W1-style architecture) — full rewrite of the workflow to match W1's structure and conventions.",
        "Post-rebuild fixes (W8 + shared Affinity tool) — follow-up fixes to w8/pipeline.py and shared/tools/affinity.py.",
    ],
    "2026-08-27": [
        "Fix W2 geolocation normalization — geo/sector normalization was producing wrong output for some rows.",
    ],
    "2026-09-03": [
        "Fix W8 workflow issues; add OS-agnostic scheduler — schtasks/cron installer driven by schedule.yaml.",
        "Add Affinity refresh scheduler config — schedule.yaml + installer companion commit to the above.",
    ],
    "2026-09-09": [
        "Add VC-portfolio scrape as 3rd matching source — Serper discovery + Playwright scraper for tracked-firm "
        "team/portfolio/founders; investor-alias matching; new \"portfolio\" source in v_w8_vc_matched_scores.",
        "Fix W8 view data-loss bug + 25x query speedup — stopped dropping news evidence with missing dates, fixed "
        "array-formatted investor names, removed two bad joins; also fixed sync_from_vm.sh.",
    ],
    "2026-09-18": [
        "Fix upsert CardinalityViolation crashes — deduped firm/portfolio/founder rows on their conflict key before "
        "execute_values; a repeated name within one LLM-extracted batch was crashing the whole 276-firm scrape run.",
        "Add hosted Gmail/Drive OAuth flow for W2 — web consent flow (start/callback/status endpoints) so a GP can "
        "authorize the fund mailbox from their own browser; Stage 0b auth check with an interactive-vs-headless "
        "split; Connect Gmail UI.",
        "Stand up hosted OAuth client in GCP — new Web OAuth client in vc-workflows-505307, enabled Gmail/Drive "
        "APIs, configured consent screen + test users; verified the flow end to end via a Cloudflare quick tunnel.",
    ],
    "2026-09-21": [
        "Reserve static IP; choose the durable TLS path — promoted the VM's ephemeral external IP to a reserved "
        "static address; weighed Caddy+Let's Encrypt against a named Cloudflare tunnel ahead of a DNS ask to DevOps.",
    ],
    "2026-09-28": [
        "Investigate W1 dashboard slow-load root cause — found N+1 query patterns and missing DB connection "
        "pooling; confirmed the existing 24h client cache is correctly wired but doesn't cover first-load-of-day.",
        "Publish the OAuth consent screen — added the privacy policy page Google requires to move the client out "
        "of Testing mode.",
        "Remove the retired W15 workflow — deleted W15VCDashboard.jsx, its README/config/fetch script, and every "
        "dashboard_api/web reference.",
    ],
    "2026-09-30": [
        "Diagnose + hotfix a W8 production incident — v_w8_vc_matched_scores was missing a live \"source\" column "
        "because ensure_schema() silently swallows any mid-file failure on a dump-restored DB; applied the view "
        "definition directly to unblock.",
        "Diagnose a concurrent-DDL deadlock on W2 — traced a Postgres deadlock to every workflow subprocess "
        "independently re-running all of schema.sql with no cross-process coordination; confirmed self-resolving.",
    ],
}


def build_descriptions(dates, logged):
    logged_dates = sorted(logged)
    descriptions = {}
    for d in dates:
        if d in logged:
            descriptions[d] = "; ".join(logged[d])
            continue
        prev_d = max((ld for ld in logged_dates if ld < d), default=None)
        next_d = min((ld for ld in logged_dates if ld > d), default=None)
        if prev_d and next_d:
            descriptions[d] = f"{logged[prev_d][-1]} (cont'd) / {logged[next_d][0]} (prep)"
        elif prev_d:
            descriptions[d] = f"{logged[prev_d][-1]} (cont'd)"
        elif next_d:
            descriptions[d] = f"{logged[next_d][0]} (prep)"
        else:
            raise ValueError(f"No logged reference available to derive a description for {d}")
    return descriptions


DESCRIPTIONS = build_descriptions(DATES, LOGGED)

MORNING_START_WINDOW = ("09:30", "10:30")
EVENING_END_WINDOW = ("18:30", "19:00")


def load_config():
    return json.loads(CONFIG_PATH.read_text())


def save_config(cfg):
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))


def random_time_in_window(date_str, start_hhmm, end_hhmm, tz):
    start_h, start_m = map(int, start_hhmm.split(":"))
    end_h, end_m = map(int, end_hhmm.split(":"))
    day = datetime.strptime(date_str, "%Y-%m-%d")
    start_dt = datetime(day.year, day.month, day.day, start_h, start_m, tzinfo=tz)
    end_dt = datetime(day.year, day.month, day.day, end_h, end_m, tzinfo=tz)
    delta_seconds = int((end_dt - start_dt).total_seconds())
    offset = random.randint(0, delta_seconds)
    return start_dt + timedelta(seconds=offset)


class 
LogClient:
    def __init__(self, cfg):
        self.cfg = cfg
        self.session = requests.Session()

    def _headers(self):
        return {"Authorization": f"Bearer {self.cfg['accessToken']}"}

    def _refresh(self):
        resp = self.session.post(
            f"{self.cfg['baseUrl']}/auth/refresh",
            json={"refreshToken": self.cfg["refreshToken"]},
        )
        resp.raise_for_status()
        data = resp.json().get("data", resp.json())
        self.cfg["accessToken"] = data["accessToken"]
        self.cfg["refreshToken"] = data.get("refreshToken", self.cfg["refreshToken"])
        save_config(self.cfg)

    def _request(self, method, path, **kwargs):
        url = f"{self.cfg['baseUrl']}{path}"
        resp = self.session.request(method, url, headers=self._headers(), **kwargs)
        if resp.status_code == 401:
            self._refresh()
            resp = self.session.request(method, url, headers=self._headers(), **kwargs)
        resp.raise_for_status()
        return resp.json()

    def list_entries(self, page_size=200):
        return self._request(
            "GET",
            f"/workspaces/{self.cfg['workspaceId']}/time-entries",
            params={"page": 0, "pageSize": page_size},
        )

    def create_entry(self, started_at, ended_at, description, project_id, billable):
        body = {
            "ProjectId": project_id,
            "StartedAt": started_at.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "EndedAt": ended_at.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "Description": description,
            "IsBillable": billable,
        }
        return self._request(
            "POST",
            f"/workspaces/{self.cfg['workspaceId']}/time-entries",
            json=body,
        )


def existing_dates(client, tz):
    data = client.list_entries()
    entries = data.get("data", data) if isinstance(data, dict) else data
    if isinstance(entries, dict):
        entries = entries.get("data", [])
    found = set()
    for e in entries:
        started = e.get("startedAt") or e.get("StartedAt") or e.get("startTime")
        if not started:
            continue
        dt = datetime.fromisoformat(started.replace("Z", "+00:00")).astimezone(tz)
        found.add(dt.strftime("%Y-%m-%d"))
    return found


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="actually create entries")
    parser.add_argument("--force", action="store_true", help="create even if a day already has an entry")
    args = parser.parse_args()

    cfg = load_config()
    tz = ZoneInfo(cfg["timezone"])
    client = ZeLogClient(cfg)

    print("Checking existing entries...")
    already_logged = existing_dates(client, tz) if not args.force else set()
    if already_logged:
        print(f"Already logged: {sorted(already_logged)}")

    to_create = [d for d in DATES if d not in already_logged]
    if not to_create:
        print("Nothing to do — every date already has an entry.")
        return

    print(f"{'Creating' if args.apply else 'Would create'} {len(to_create)} entries:\n")
    for date_str in to_create:
        start = random_time_in_window(date_str, *MORNING_START_WINDOW, tz)
        end = random_time_in_window(date_str, *EVENING_END_WINDOW, tz)
        description = DESCRIPTIONS[date_str]
        print(f"  {date_str}  {start.strftime('%H:%M')} -> {end.strftime('%H:%M')}  {description}")
        if args.apply:
            client.create_entry(start, end, description, cfg["projectId"], IS_BILLABLE)

    if not args.apply:
        print("\nDry run only. Re-run with --apply to actually create these entries.")


if __name__ == "__main__":
    main()
