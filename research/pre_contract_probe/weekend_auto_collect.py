"""End-to-end weekend probe orchestrator (offline research only).

Runs the full sandbox collection/evaluation day unattended:

1. jra_odds_probe: discover today's JRA races, snapshot win/place odds
   ~5 minutes before each start (exits quietly on non-race days).
2. After the last race: collect results and official payouts per venue.
3. Merge, import to the sandbox layout, build shadow input, run the
   shadow pipeline (sequential + independent + conservative filter),
   and write evaluation reports.

Everything stays under pre_contract_sandbox/ and
reports/data_collection/pre_contract_sandbox_YYYYMMDD/ — never Stage 4
evidence, never canonical paths. Designed for Windows Task Scheduler:

    schtasks /Create /SC WEEKLY /D SAT,SUN /ST 08:40 ^
      /TN KeibaAI_WeekendProbe ^
      /TR "<python> <this file>"
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JST = timezone(timedelta(hours=9))
USER_AGENT = "keiba-ai-personal-verification/0.1 (low-volume research probe)"
VENUE_NAMES = {
    "01": "SAPPORO", "02": "HAKODATE", "03": "FUKUSHIMA", "04": "NIIGATA",
    "05": "TOKYO", "06": "NAKAYAMA", "07": "CHUKYO", "08": "KYOTO",
    "09": "HANSHIN", "10": "KOKURA",
}
RESULT_WAIT_MINUTES = 20
MAX_ODDS_FILTER = "20"
MAX_FAVORITE_RANK_FILTER = "8"


def log(msg: str) -> None:
    print(f"[{datetime.now(JST).isoformat(timespec='seconds')}] {msg}", flush=True)


def run(args: list[str], *, check: bool = True) -> int:
    log("run: " + " ".join(str(a) for a in args))
    proc = subprocess.run([sys.executable, *args], cwd=ROOT)
    if check and proc.returncode != 0:
        raise RuntimeError(f"step failed ({proc.returncode}): {args}")
    return proc.returncode


def discover_result_indexes(date_str: str) -> dict[str, str]:
    """Return venue name -> pw01srl CNAME for today's result day-indexes."""
    data = urllib.parse.urlencode({"cname": "pw01sli00/AF"}).encode()
    req = urllib.request.Request(
        "https://www.jra.go.jp/JRADB/accessS.html",
        data=data,
        headers={"User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        html = resp.read().decode("shift_jis", errors="replace")
    time.sleep(3)
    indexes: dict[str, str] = {}
    for m in re.finditer(
        rf"'(pw01srl\d0(\d{{2}})\d{{4}}\d{{4}}{date_str}/[0-9A-F]{{2}})'", html
    ):
        venue = VENUE_NAMES.get(m.group(2), f"VENUE{m.group(2)}")
        indexes.setdefault(venue, m.group(1))
    return indexes


def merge_day(date_str: str, odds_dir: Path, result_dirs: dict[str, Path]) -> Path:
    import csv

    out = ROOT / "pre_contract_sandbox" / f"merged_{date_str}"
    out.mkdir(parents=True, exist_ok=True)
    for name in ("results.csv", "payouts.csv"):
        rows: list[dict] = []
        for venue_dir in result_dirs.values():
            path = venue_dir / name
            if path.exists():
                rows += list(csv.DictReader(path.open(encoding="utf-8")))
        if rows:
            with (out / name).open("w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
                writer.writeheader()
                writer.writerows(rows)
    for name in ("odds.csv", "schedule.csv"):
        (out / name).write_bytes((odds_dir / name).read_bytes())
    return out


def main() -> int:
    date_str = datetime.now(JST).strftime("%Y%m%d")
    odds_dir = ROOT / "pre_contract_sandbox" / f"probe_odds_{date_str}"
    report_dir = ROOT / "reports" / "data_collection" / f"pre_contract_sandbox_{date_str}"

    # ---- 1. odds collection (blocks until the last race; rc=1 = no races)
    rc = run(
        ["research/pre_contract_probe/jra_odds_probe.py",
         "--outdir", str(odds_dir), "--minutes-before", "5"],
        check=False,
    )
    if rc != 0:
        log("no races today (or odds probe failed); exiting")
        return 0

    # ---- 2. results + payouts after the final race settles
    log(f"odds done; waiting {RESULT_WAIT_MINUTES} min for final results")
    time.sleep(RESULT_WAIT_MINUTES * 60)
    indexes = discover_result_indexes(date_str)
    if not indexes:
        log("no result indexes found; aborting before evaluation")
        return 1
    result_dirs: dict[str, Path] = {}
    for venue, cname in sorted(indexes.items()):
        outdir = ROOT / "pre_contract_sandbox" / f"probe_results_{date_str}_{venue.lower()}"
        run(["research/pre_contract_probe/jra_result_probe.py",
             "--day-index-cname", cname, "--venue", venue, "--outdir", str(outdir)])
        result_dirs[venue] = outdir

    # ---- 3. merge + import + shadow input
    merged = merge_day(date_str, odds_dir, result_dirs)
    live_inputs = report_dir / "live_inputs"
    run(["-m", "scripts.import_pre_contract_sandbox",
         "--schedule-input", str(merged / "schedule.csv"),
         "--odds-input", str(merged / "odds.csv"),
         "--results-input", str(merged / "results.csv"),
         "--output-root", str(live_inputs),
         "--source", "scrape_probe",
         "--min-races", "12", "--min-horses-per-race", "5",
         "--status", str(report_dir / "import_status.json")])
    shadow_input = report_dir / "shadow_input.csv"
    run(["-m", "scripts.build_pre_contract_shadow_input",
         "--schedule", str(live_inputs / "today_races.json"),
         "--odds-dir", str(live_inputs / "odds"),
         "--results-dir", str(live_inputs / "results"),
         "--output", str(shadow_input),
         "--status", str(report_dir / "shadow_input_status.json")])

    # ---- 4. shadow runs + evaluations
    variants = {
        "": [],
        "_independent": ["--independent-races"],
        "_independent_filtered": ["--independent-races",
                                  "--max-odds", MAX_ODDS_FILTER,
                                  "--max-favorite-rank", MAX_FAVORITE_RANK_FILTER],
    }
    for suffix, extra in variants.items():
        run(["-m", "scripts.shadow_run_from_file",
             "--input", str(shadow_input),
             "--decision-log", str(report_dir / f"decisions{suffix}.jsonl"),
             "--csv-report", str(report_dir / f"bets{suffix}.csv"),
             "--settle", *extra])
        run(["-m", "scripts.evaluate_pre_contract_sandbox",
             "--bets-csv", str(report_dir / f"bets{suffix}.csv"),
             "--shadow-input-csv", str(shadow_input),
             "--output-json", str(report_dir / f"eval{suffix}.json"),
             "--output-md", str(report_dir / f"eval{suffix}.md")])
        run(["-m", "scripts.analyze_pre_contract_filters",
             "--evaluation-json", str(report_dir / f"eval{suffix}.json"),
             "--output-json", str(report_dir / f"filter_analysis{suffix}.json"),
             "--output-md", str(report_dir / f"filter_analysis{suffix}.md")])

    summary = {
        "date": date_str,
        "status": "auto_collect_complete",
        "evidence_eligible": False,
        "venues": sorted(result_dirs),
        "reports": str(report_dir),
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    (report_dir / "auto_collect_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log(f"auto collect complete: {report_dir}")
    return 0


if __name__ == "__main__":
    log_dir = ROOT / "reports" / "data_collection" / "auto_collect_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{datetime.now(JST).strftime('%Y%m%d')}.log"
    tee = log_path.open("a", encoding="utf-8")

    class _Tee:
        def __init__(self, *streams):
            self._streams = streams

        def write(self, data):
            for stream in self._streams:
                stream.write(data)

        def flush(self):
            for stream in self._streams:
                stream.flush()

    sys.stdout = _Tee(sys.__stdout__, tee)  # type: ignore[assignment]
    sys.stderr = _Tee(sys.__stderr__, tee)  # type: ignore[assignment]
    try:
        raise SystemExit(main())
    finally:
        tee.flush()
