from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.betting.bet_types import default_registry
from scripts.bet_type_metrics_report import (
    _decision_opportunities,
    _hhi,
    _oos_stability,
    _profit_factor,
    _profit_for_row,
    _recommendation,
    _violation_counts,
    _worst_fold_roi,
    boolish,
    build_report,
    normalize_rows,
    numeric,
    read_csv_rows,
    read_jsonl,
)


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_jsonl(path: Path, events: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")


def _candidate_event(bet_type: str, legs: list[str], idx: int) -> dict:
    return {
        "event_type": "BetRejected",
        "occurred_at_utc": datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat(),
        "payload": {
            "race_id": f"R{idx}",
            "bet_type": bet_type,
            "legs": legs,
            "selection_id": "-".join(legs),
            "execution_status": "SHADOW",
            "shadow_mode": True,
        },
    }


def _metric(payload: dict, bet_type: str) -> dict:
    return next(row for row in payload["bet_type_metrics"] if row["bet_type"] == bet_type)


def test_bet_type_metrics_roi_profit_factor_hit_rate_coverage_and_recommendations(tmp_path):
    derived = tmp_path / "derived" / "bets.csv"
    decisions = tmp_path / "logs" / "decisions.jsonl"
    out_json = tmp_path / "reports" / "stage4" / "bet_type_metrics.json"
    out_csv = tmp_path / "reports" / "stage4" / "bet_type_metrics.csv"
    _write_csv(
        derived,
        [
            {"race_id": "R1", "horse_id": "H01", "odds": 3.0, "stake": 100, "hit": 1, "payout": 300},
            {"race_id": "R2", "bet_type": "quinella", "legs": '["H01","H02"]', "stake": 100, "hit": 1, "profit": 20},
            {"race_id": "R3", "bet_type": "quinella", "legs": '["H03","H04"]', "stake": 100, "hit": 1, "profit": 20},
            {"race_id": "R4", "bet_type": "trio", "legs": '["H01","H02","H03"]', "stake": 100, "hit": 0, "profit": -10},
            {"race_id": "R5", "bet_type": "exacta", "legs": '["H01","H02"]', "stake": 100, "hit": 0, "profit": -100},
        ],
    )
    _write_jsonl(
        decisions,
        [_candidate_event("quinella", ["H01", "H02"], idx) for idx in range(1, 5)]
        + [_candidate_event("trio", ["H01", "H02", "H03"], idx) for idx in range(5, 15)],
    )

    payload = build_report(
        derived_bets=derived,
        decisions_jsonl=decisions,
        output_json=out_json,
        output_csv=out_csv,
    )

    quinella = _metric(payload, "quinella")
    assert quinella["ROI"] == 0.2
    assert quinella["Profit Factor"] == "inf"
    assert quinella["Hit Rate"] == 1.0
    assert quinella["coverage"] == 0.5
    assert quinella["recommendation"] == "promote_candidate_possible"

    trio = _metric(payload, "trio")
    assert trio["ROI"] == -0.1
    assert trio["recommendation"] == "disable"

    win = _metric(payload, "win")
    assert win["bet_count"] == 1
    assert payload["old_win_compat_conversion_count"] >= 1
    assert payload["disabled_bet_type_candidate_count"] >= 1
    assert out_json.exists()
    assert out_csv.exists()


def test_shadow_only_extreme_coverage_recommends_disable(tmp_path):
    derived = tmp_path / "derived" / "bets.csv"
    decisions = tmp_path / "logs" / "decisions.jsonl"
    _write_csv(
        derived,
        [
            {"race_id": "R1", "bet_type": "quinella", "legs": '["H01","H02"]', "stake": 100, "hit": 1, "profit": 10},
            {"race_id": "R2", "bet_type": "quinella", "legs": '["H03","H04"]', "stake": 100, "hit": 1, "profit": 10},
        ],
    )
    _write_jsonl(decisions, [_candidate_event("quinella", ["H01", "H02"], 1)])

    payload = build_report(derived_bets=derived, decisions_jsonl=decisions)

    assert _metric(payload, "quinella")["coverage"] == 2.0
    assert _metric(payload, "quinella")["recommendation"] == "disable"


def test_bet_type_metrics_helpers_cover_payout_and_bad_inputs(tmp_path):
    registry = default_registry()
    assert read_csv_rows(tmp_path / "missing.csv") == []
    assert read_jsonl(tmp_path / "missing.jsonl") == []
    bad_jsonl = tmp_path / "bad.jsonl"
    bad_jsonl.write_text("{bad\n", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid JSON"):
        read_jsonl(bad_jsonl)

    assert numeric("bad", default=7) == 7
    assert boolish("", default=True) is True
    assert boolish(True) is True

    rows, counters = normalize_rows([{"race_id": "R1"}], registry=registry)
    assert rows[0]["_normalization_error"] is True
    assert counters["bet_type_missing_count"] == 1

    assert _profit_for_row({"stake": 500, "hit": 1, "payout_per_100": 360}) == 1300
    assert _profit_for_row({"stake": 500, "hit": 1, "gross_payout": 1800}) == 1300
    assert _profit_for_row({"stake": 100, "hit": 1, "payout_per_100": 0}) == 0
    assert _profit_for_row({"stake": 100}) == 0
    assert _profit_factor([10, -5]) == 2
    assert _profit_factor([]) is None
    assert _hhi([]) == 0
    assert _worst_fold_roi([{"stake": 0, "profit": 0}]) is None
    assert _oos_stability([{"fold": "A", "stake": 100, "profit": 10}]) is None


def test_bet_type_metrics_recommendations_and_violation_counters():
    registry = default_registry()
    assert _recommendation(
        config=registry.get("win"),
        roi=-0.10,
        profit_factor=0.5,
        coverage=0.10,
        max_drawdown_contribution=0,
        hhi=0,
        oos_stability=None,
        risk_reject_rate=0,
    )[0] == "limit_or_review"
    assert _recommendation(
        config=registry.get("exacta"),
        roi=None,
        profit_factor=None,
        coverage=0,
        max_drawdown_contribution=0,
        hhi=0,
        oos_stability=None,
        risk_reject_rate=0,
    )[0] == "disabled"
    assert _recommendation(
        config=registry.get("quinella"),
        roi=0.01,
        profit_factor=1.10,
        coverage=0.10,
        max_drawdown_contribution=0.10,
        hhi=0.10,
        oos_stability=0.10,
        risk_reject_rate=0,
    )[0] == "promote_candidate_possible"
    assert _recommendation(
        config=registry.get("quinella"),
        roi=0.01,
        profit_factor=1.00,
        coverage=0.10,
        max_drawdown_contribution=0.10,
        hhi=0.10,
        oos_stability=0.20,
        risk_reject_rate=0,
    )[0] == "keep_shadow"

    opportunities, counters = _decision_opportunities(
        [
            {"event_type": "Heartbeat", "payload": {}},
            {"event_type": "BetSubmitted", "payload": {"bet_type": "mystery"}},
            {"event_type": "BetRejected", "payload": {"horse_id": "H01", "race_id": "R1"}},
        ],
        registry=registry,
    )
    assert opportunities["win"] == 1
    assert counters["production_execution_unknown_bet_type_count"] == 1

    violations = _violation_counts(
        rows=[{"bet_type": "exacta"}, {"bet_type": "unknown"}],
        events=[
            {"event_type": "BetSubmitted", "payload": {"bet_type": "quinella", "legs": ["H01", "H02"]}},
            {
                "event_type": "BetRejected",
                "payload": {
                    "bet_type": "trio",
                    "legs": ["H01", "H02", "H03"],
                    "reason": "shadow_only_execution_rejected",
                },
            },
            {"event_type": "BetAccepted", "payload": {"bet_type": "unknown"}},
        ],
        registry=registry,
    )
    assert violations["disabled_bet_type_candidate_count"] == 1
    assert violations["shadow_only_violation_count"] >= 2
    assert violations["production_execution_unknown_bet_type_count"] == 1
