"""Low-volume JRA official-site result probe (offline research only).

Fetches race result pages for one venue-day from www.jra.go.jp (robots.txt
allows all paths; requests are throttled) and writes pre_contract_sandbox
style CSVs with source label ``scrape_probe``.

This is research tooling. It must never be imported by runtime code, and its
output is never Stage 4 evidence (``evidence_eligible: false``). Per-horse win
odds are NOT available for past races on the official site, so this probe
emits results/schedule plus favorite rank and official payouts. Odds require
live collection on race day (see jra_odds_probe.py).

The day index can be either a GET path (``/JRADB/accessS.html?CNAME=pw01sde...``,
a race page that links its siblings) or a raw ``pw01srl...`` CNAME (the
venue-day result list, which only answers to POST).
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = "https://www.jra.go.jp"
USER_AGENT = "keiba-ai-personal-verification/0.1 (low-volume research probe)"
REQUEST_DELAY_SECONDS = 3.0
JST = timezone(timedelta(hours=9))

CNAME_RE = re.compile(
    r"pw01sde(\d{4})(\d{4})(\d{2})(\d{2})(\d{2})(\d{8})"
)  # venue, year, kai, day, race_number, yyyymmdd
ROW_RE = re.compile(
    r'<td class="place">(\d+)</td>.*?<td class="num">(\d+)</td>.*?'
    r'<td class="horse">.*?>([^<]+)</a>.*?<td class="pop">(\d*)</td>',
    re.S,
)
META_RE = re.compile(
    r'class="cell date">(\d{4})年(\d{1,2})月(\d{1,2})日[^<]*</div>\s*'
    r'<div class="cell time">\s*発走時刻：<strong>(\d{1,2})時(\d{1,2})分',
    re.S,
)
RACE_NUM_RE = re.compile(r"race_num_(\d+)\.png")
SRL_INDEX_RE = re.compile(
    r"pw01srl\d0(\d{2})(\d{4})(\d{2})(\d{2})(\d{8})"
)  # venue, year, kai, day, yyyymmdd
PAYOUT_LINE_RE = re.compile(
    r'<div class="num">([-\d]+)</div>\s*'
    r'<div class="yen">([\d,]+)<span class="unit">円</span></div>\s*'
    r'<div class="pop">(\d*)',
    re.S,
)
PAYOUT_TYPES = {
    "win": "win", "place": "place", "wakuren": "wakuren", "wide": "wide",
    "umaren": "quinella", "umatan": "exacta", "trio": "trio", "tierce": "trifecta",
}


def fetch(path_or_cname: str) -> str:
    if path_or_cname.startswith("pw"):
        data = urllib.parse.urlencode({"cname": path_or_cname}).encode()
        req = urllib.request.Request(
            BASE + "/JRADB/accessS.html", data=data,
            headers={"User-Agent": USER_AGENT},
        )
    else:
        req = urllib.request.Request(
            BASE + path_or_cname, headers={"User-Agent": USER_AGENT}
        )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read()
    time.sleep(REQUEST_DELAY_SECONDS)
    return body.decode("shift_jis", errors="replace")


def parse_payouts(html: str) -> list[dict]:
    """Parse the refund_unit block: all bet-type payouts per 100 yen."""
    start = html.find("refund_unit")
    if start < 0:
        return []
    segment = html[start:start + 6000]
    payouts = []
    for li_class, jra_name in PAYOUT_TYPES.items():
        li_match = re.search(
            rf'<li class="{li_class}">\s*<dl>(.*?)</dl>', segment, re.S
        )
        if not li_match:
            continue
        for combo, yen, pop in PAYOUT_LINE_RE.findall(li_match.group(1)):
            payouts.append(
                {
                    "bet_type": jra_name,
                    "combination": combo,
                    "payout_per_100": int(yen.replace(",", "")),
                    "popularity": int(pop) if pop else None,
                }
            )
    return payouts


def parse_race(html: str) -> dict:
    meta = META_RE.search(html)
    race_num = RACE_NUM_RE.search(html)
    if not meta or not race_num:
        raise ValueError("race meta not found")
    year, month, day, hour, minute = (int(g) for g in meta.groups())
    start_jst = datetime(year, month, day, hour, minute, tzinfo=JST)
    rows = []
    for place, num, name, pop in ROW_RE.findall(html):
        rows.append(
            {
                "finish_position": int(place),
                "horse_id": int(num),
                "horse_name": name.strip(),
                "favorite_rank": int(pop) if pop else None,
            }
        )
    if not rows:
        raise ValueError("no result rows parsed")
    return {
        "race_number": int(race_num.group(1)),
        "start_at_utc": start_jst.astimezone(timezone.utc),
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--day-index-cname", required=True,
                        help="accessS CNAME path of the venue-day index page, "
                             "e.g. '/JRADB/accessS.html?CNAME=pw01sde1002202601061120260628/2D'")
    parser.add_argument("--venue", required=True, help="venue label, e.g. HAKODATE")
    parser.add_argument("--outdir", default="pre_contract_sandbox/probe_results")
    parser.add_argument("--max-races", type=int, default=12)
    args = parser.parse_args()

    index_key = CNAME_RE.search(args.day_index_cname)
    if index_key:
        venue4, year, kai, day, _, date_str_key = index_key.groups()
        venue_code = venue4[-2:]
    else:
        srl_key = SRL_INDEX_RE.search(args.day_index_cname)
        if not srl_key:
            print("day-index-cname is neither a pw01sde nor pw01srl CNAME",
                  file=sys.stderr)
            return 1
        venue_code, year, kai, day, date_str_key = srl_key.groups()

    index_html = fetch(args.day_index_cname)
    race_links: list[tuple[int, str]] = []
    seen = set()
    for m in re.finditer(
        r'href="(/JRADB/accessS\.html\?CNAME=pw01sde\d+/[0-9A-F]{2})"', index_html
    ):
        href = m.group(1)
        key = CNAME_RE.search(href)
        if not key or href in seen:
            continue
        # keep only races of the same venue-day as the passed index page
        # (sde venue field is 4 digits; the venue proper is its last 2 digits)
        link_venue4, link_year, link_kai, link_day, _, link_date = key.groups()
        if (link_venue4[-2:], link_year, link_kai, link_day, link_date) != (
            venue_code, year, kai, day, date_str_key
        ):
            continue
        seen.add(href)
        race_links.append((int(key.group(5)), href))
    race_links = sorted(set(race_links))[: args.max_races]
    if not race_links:
        print("no race links found in day index", file=sys.stderr)
        return 1
    print(f"found {len(race_links)} race pages; fetching with "
          f"{REQUEST_DELAY_SECONDS}s delay")

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    schedule_rows, result_rows, payout_rows = [], [], []
    for race_number, href in race_links:
        page = fetch(href)
        race = parse_race(page)
        payouts = parse_payouts(page)
        date_str = race["start_at_utc"].astimezone(JST).strftime("%Y%m%d")
        if date_str != date_str_key:
            raise ValueError(f"page date {date_str} != index date {date_str_key}")
        race_id = f"SANDBOX_{date_str}_{args.venue}_{race_number:02d}"
        win_payout_by_horse = {
            p["combination"]: p["payout_per_100"]
            for p in payouts
            if p["bet_type"] == "win"
        }
        for payout in payouts:
            payout_rows.append({"race_id": race_id, **payout})
        schedule_rows.append(
            {
                "race_id": race_id,
                "race_start_at_utc": race["start_at_utc"].isoformat(),
                "venue": args.venue,
                "race_number": f"{race_number:02d}",
                "source": "scrape_probe",
            }
        )
        for row in race["rows"]:
            is_win = row["finish_position"] == 1
            result_rows.append(
                {
                    "race_id": race_id,
                    "horse_id": row["horse_id"],
                    "finish_position": row["finish_position"],
                    "is_win": str(is_win).lower(),
                    "win_payout": (
                        win_payout_by_horse.get(str(row["horse_id"]), 0)
                        if is_win else 0
                    ),
                    "result_time_utc": race["start_at_utc"].isoformat(),
                    "source": "scrape_probe",
                    "favorite_rank": row["favorite_rank"],
                    "horse_name": row["horse_name"],
                }
            )
        print(f"  {race_id}: {len(race['rows'])} finishers, "
              f"{len(payouts)} payout lines")

    outputs = [
        ("schedule.csv", schedule_rows),
        ("results.csv", result_rows),
        ("payouts.csv", payout_rows),
    ]
    for name, rows in outputs:
        if not rows:
            continue
        path = outdir / name
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        print(f"wrote {path} ({len(rows)} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
