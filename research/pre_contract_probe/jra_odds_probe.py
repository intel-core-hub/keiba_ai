"""Low-volume JRA official-site win-odds probe (offline research only).

Discovers today's venues and race times from www.jra.go.jp odds pages
(robots.txt allows all paths), then takes ONE win/place odds snapshot per race
about N minutes before its start time. Roughly 40 polite requests per race
day, 3s apart. Output feeds the pre_contract_sandbox pipeline with source
label ``scrape_probe`` and is never Stage 4 evidence.

Run for a whole race day:

    python research/pre_contract_probe/jra_odds_probe.py \
        --outdir pre_contract_sandbox/probe_odds_YYYYMMDD
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = "https://www.jra.go.jp"
ACCESS_O = BASE + "/JRADB/accessO.html"
USER_AGENT = "keiba-ai-personal-verification/0.1 (low-volume research probe)"
REQUEST_DELAY_SECONDS = 3.0
JST = timezone(timedelta(hours=9))

VENUE_NAMES = {
    "01": "SAPPORO", "02": "HAKODATE", "03": "FUKUSHIMA", "04": "NIIGATA",
    "05": "TOKYO", "06": "NAKAYAMA", "07": "CHUKYO", "08": "KYOTO",
    "09": "HANSHIN", "10": "KOKURA",
}

DAY_LINK_RE = re.compile(r"doAction\('/JRADB/accessO\.html',\s*'(pw15orl00(\d{2})\d{4}\d{4}(\d{8})/[0-9A-F]{2})'\)")
# the time cell shows "H時M分" before the race and "発走済" afterwards
RACE_ROW_RE = re.compile(
    r"btn_race_num(\d+)\.png.*?<td class=\"time\">\s*(?:(\d{1,2})時(\d{1,2})分|発走済).*?"
    r"class=\"tanpuku\">.*?doAction\('/JRADB/accessO\.html',\s*'(pw151ouS3[^']+)'\)",
    re.S,
)
# bracket cells use rowspan when one bracket holds several horses, so the
# waku <td> is absent on continuation rows; parse per <tr> and carry the
# bracket forward.
WAKU_RE = re.compile(r'alt="枠(\d)')
HORSE_ROW_RE = re.compile(
    r'<td class="num">(\d+)</td>\s*'
    r'<td class="horse"><a[^>]*>([^<]+)</a></td>\s*'
    r'<td class="odds_tan">(?:<strong[^>]*>)?([\d.]+|取消|除外)(?:</strong>)?</td>'
    r'(?:<td class="odds_fuku"><span class="inner"><span class="min">([\d.]*)</span>'
    r'<span class="cap">-</span><span class="max">([\d.]*)</span>)?',
    re.S,
)


def post_cname(cname: str) -> str:
    data = urllib.parse.urlencode({"cname": cname}).encode()
    req = urllib.request.Request(
        ACCESS_O, data=data, headers={"User-Agent": USER_AGENT}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read()
    time.sleep(REQUEST_DELAY_SECONDS)
    return body.decode("shift_jis", errors="replace")


def discover_races(target_date: str) -> list[dict]:
    """Return today's races across venues: race_id, start_at, odds cname."""
    index_html = post_cname("pw15oli00/6D")
    races: list[dict] = []
    seen_days = set()
    for cname, venue_code, date_str in DAY_LINK_RE.findall(index_html):
        if date_str != target_date or cname in seen_days:
            continue
        seen_days.add(cname)
        venue = VENUE_NAMES.get(venue_code, f"VENUE{venue_code}")
        day_html = post_cname(cname)
        for race_no, hh, mm, odds_cname in RACE_ROW_RE.findall(day_html):
            start = datetime.strptime(target_date, "%Y%m%d").replace(
                hour=int(hh) if hh else 0, minute=int(mm) if mm else 0, tzinfo=JST
            )
            races.append(
                {
                    "race_id": f"SANDBOX_{target_date}_{venue}_{int(race_no):02d}",
                    "venue": venue,
                    "race_number": f"{int(race_no):02d}",
                    "start_at_jst": start,
                    "odds_cname": odds_cname,
                }
            )
    races.sort(key=lambda r: (r["start_at_jst"], r["race_id"]))
    return races


def parse_odds_page(html: str) -> list[dict]:
    body_start = html.find("<tbody")
    rows: list[dict] = []
    current_bracket: int | None = None
    for tr in re.split(r"<tr[ >]", html[body_start:] if body_start >= 0 else html):
        waku = WAKU_RE.search(tr)
        if waku:
            current_bracket = int(waku.group(1))
        horse = HORSE_ROW_RE.search(tr)
        if not horse or current_bracket is None:
            continue
        num, name, tan, fuku_min, fuku_max = horse.groups()
        scratched = tan in ("取消", "除外")
        rows.append(
            {
                "horse_id": int(num),
                "bracket": current_bracket,
                "horse_name": name.strip(),
                "odds": None if scratched else float(tan),
                "place_odds_min": float(fuku_min) if fuku_min else None,
                "place_odds_max": float(fuku_max) if fuku_max else None,
                "scratched": scratched,
            }
        )
    return rows


def append_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    new_file = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        if new_file:
            writer.writeheader()
        writer.writerows(rows)


def log_status(path: Path, payload: dict) -> None:
    payload["logged_at_utc"] = datetime.now(timezone.utc).isoformat()
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outdir", required=True)
    parser.add_argument("--date", default=datetime.now(JST).strftime("%Y%m%d"))
    parser.add_argument("--minutes-before", type=float, default=5.0)
    parser.add_argument("--dry-run", action="store_true",
                        help="discover and snapshot the first race immediately, then exit")
    parser.add_argument("--immediate", action="store_true",
                        help="snapshot every race right now regardless of start "
                             "time (post-race pages show final odds)")
    args = parser.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    status_path = outdir / "probe_status.jsonl"

    races = discover_races(args.date)
    if not races:
        log_status(status_path, {"event": "no_races_found", "date": args.date})
        print("no races found for", args.date, file=sys.stderr)
        return 1
    print(f"discovered {len(races)} races on {args.date} "
          f"({', '.join(sorted({r['venue'] for r in races}))})")
    log_status(status_path, {"event": "discovered", "date": args.date,
                             "race_count": len(races)})

    schedule_rows = [
        {
            "race_id": r["race_id"],
            "race_start_at_utc": r["start_at_jst"].astimezone(timezone.utc).isoformat(),
            "venue": r["venue"],
            "race_number": r["race_number"],
            "source": "scrape_probe",
        }
        for r in races
    ]
    schedule_path = outdir / "schedule.csv"
    if not schedule_path.exists():
        append_csv(schedule_path, schedule_rows,
                   list(schedule_rows[0].keys()))

    odds_fields = ["race_id", "horse_id", "odds", "snapshot_at_utc", "source",
                   "bracket", "horse_name", "place_odds_min", "place_odds_max"]
    collected = 0
    for race in races if not args.dry_run else races[:1]:
        snapshot_at = race["start_at_jst"] - timedelta(minutes=args.minutes_before)
        now = datetime.now(JST)
        if not args.dry_run and not args.immediate:
            if now >= race["start_at_jst"]:
                log_status(status_path, {"event": "skipped_started",
                                         "race_id": race["race_id"]})
                continue
            wait = (snapshot_at - now).total_seconds()
            if wait > 0:
                print(f"waiting {wait/60:.1f} min for {race['race_id']} "
                      f"(start {race['start_at_jst'].strftime('%H:%M')})")
                time.sleep(wait)
        try:
            html = post_cname(race["odds_cname"])
            rows = parse_odds_page(html)
            if not rows:
                raise ValueError("no odds rows parsed")
            snapshot_utc = datetime.now(timezone.utc).isoformat()
            runners = [r for r in rows if not r["scratched"]]
            append_csv(
                outdir / "odds.csv",
                [
                    {
                        "race_id": race["race_id"],
                        "horse_id": r["horse_id"],
                        "odds": r["odds"],
                        "snapshot_at_utc": snapshot_utc,
                        "source": "scrape_probe",
                        "bracket": r["bracket"],
                        "horse_name": r["horse_name"],
                        "place_odds_min": r["place_odds_min"],
                        "place_odds_max": r["place_odds_max"],
                    }
                    for r in runners
                ],
                odds_fields,
            )
            collected += 1
            log_status(status_path, {"event": "snapshot", "race_id": race["race_id"],
                                     "runners": len(runners),
                                     "scratched": len(rows) - len(runners)})
            print(f"snapshot {race['race_id']}: {len(runners)} runners")
        except Exception as exc:  # keep collecting remaining races
            log_status(status_path, {"event": "error", "race_id": race["race_id"],
                                     "error": str(exc)})
            print(f"ERROR {race['race_id']}: {exc}", file=sys.stderr)

    log_status(status_path, {"event": "done", "collected": collected,
                             "total": len(races)})
    print(f"done: {collected}/{len(races)} races collected")
    return 0


if __name__ == "__main__":
    sys.exit(main())
