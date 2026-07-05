"""Diagnose why the decision engine only bets mid-longshots (offline research).

Instruments DecisionEngine over a sandbox shadow-input CSV and reports, per
odds band: model probability vs market probability, edge, EV, and the skip
reason distribution. Read-only analysis; writes a markdown + JSON report.

Usage:
    python research/pre_contract_probe/edge_band_diagnostic.py \
        --input reports/data_collection/pre_contract_sandbox_combined_2d/shadow_input.csv \
        --outdir reports/data_collection/pre_contract_sandbox_combined_2d
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BANDS = [
    ("fav_1_3", 1.0, 3.0),
    ("mid_3_8", 3.0, 8.0),
    ("upper_8_12", 8.0, 12.0),
    ("longshot_12_26", 12.0, 26.0),
    ("deep_26_50", 26.0, 50.0),
    ("extreme_50_plus", 50.0, 10_000.0),
]


def band_of(odds: float) -> str:
    for name, lo, hi in BANDS:
        if lo <= odds < hi:
            return name
    return "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--outdir", required=True)
    args = parser.parse_args()

    from core.betting import decision_engine as de
    from scripts.shadow_run_from_file import run_shadow_file

    samples: list[dict] = []

    orig_log = de.DecisionEngine._log_decision

    def spy_log(self, d, skipped=False, skip_reason="", features=None):
        samples.append(
            {
                "race_id": d.race_id,
                "selection": d.selection,
                "odds": float(d.odds),
                "band": band_of(float(d.odds)),
                "ai_prob": float(d.probability),
                "calibrated_prob": float(d.calibrated_probability),
                "market_prob": float(d.market_probability),
                "edge": float(d.edge),
                "expected_value": float(d.expected_value),
                "submitted": not skipped,
                "skip_reason": skip_reason or ("SUBMITTED" if not skipped else "unknown"),
            }
        )
        return orig_log(self, d, skipped=skipped, skip_reason=skip_reason, features=features)

    de.DecisionEngine._log_decision = spy_log
    try:
        with tempfile.TemporaryDirectory() as tmp:
            run_shadow_file(
                Path(args.input),
                Path(tmp) / "dec.jsonl",
                Path(tmp) / "bets.csv",
                settle=False,
                independent_races=True,
            )
    finally:
        de.DecisionEngine._log_decision = orig_log

    by_band: dict[str, list[dict]] = defaultdict(list)
    for s in samples:
        by_band[s["band"]].append(s)

    report_rows = []
    for name, _, _ in BANDS:
        rows = by_band.get(name, [])
        if not rows:
            continue
        reasons = Counter(r["skip_reason"] for r in rows)
        report_rows.append(
            {
                "band": name,
                "count": len(rows),
                "submitted": sum(1 for r in rows if r["submitted"]),
                "mean_ai_prob": round(mean(r["ai_prob"] for r in rows), 4),
                "mean_calibrated_prob": round(mean(r["calibrated_prob"] for r in rows), 4),
                "mean_market_prob": round(mean(r["market_prob"] for r in rows), 4),
                "mean_edge": round(mean(r["edge"] for r in rows), 4),
                "mean_ev": round(mean(r["expected_value"] for r in rows), 4),
                "skip_reasons": dict(reasons.most_common()),
            }
        )

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "edge_band_diagnostic.json").write_text(
        json.dumps({"input": args.input, "bands": report_rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lines = [
        "# Edge Band Diagnostic (offline research)",
        "",
        f"Input: `{args.input}`  ",
        "Engine state: independent per race; untrained predictor fallback path.",
        "",
        "| Band | N | Submitted | ai_prob | calib_prob | market_prob | edge | EV | Top skip reasons |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for r in report_rows:
        top = ", ".join(f"{k}:{v}" for k, v in list(r["skip_reasons"].items())[:3])
        lines.append(
            f"| {r['band']} | {r['count']} | {r['submitted']} | {r['mean_ai_prob']} "
            f"| {r['mean_calibrated_prob']} | {r['mean_market_prob']} | {r['mean_edge']} "
            f"| {r['mean_ev']} | {top} |"
        )
    (outdir / "edge_band_diagnostic.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
