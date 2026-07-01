from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("SHADOW_MODE", "1")
os.environ.setdefault("SAFE_MODE", "1")

from core.bet_sizer import BetSizer
from core.betting.decision_engine import DecisionEngine
from core.execution.bet_executor import BetExecutor
from core.execution.calibration_refit import CalibrationRefitJob
from core.prediction.calibration import ProbabilityCalibrator
from core.prediction.edge_calculator import EdgeCalculator
from core.predictor import Predictor
from core.risk_manager import RiskManager
from execution.phase2_loop import Phase2OperationalLoop


def _coerce(value: str) -> Any:
    text = str(value).strip()
    if text == "":
        return ""
    for caster in (int, float):
        try:
            return caster(text)
        except ValueError:
            pass
    if text.lower() in {"true", "false"}:
        return text.lower() == "true"
    return text


def _load_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(path)
    if path.suffix.lower() == ".jsonl":
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return [{key: _coerce(value) for key, value in row.items()} for row in csv.DictReader(handle)]


def _features(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("features")
    if isinstance(raw, dict):
        features = dict(raw)
    elif isinstance(raw, str) and raw.strip():
        features = json.loads(raw)
    else:
        reserved = {
            "race_id",
            "selection",
            "selection_id",
            "horse_id",
            "horse_number",
            "odds",
            "hit",
            "target_win",
            "outcome",
            "winner",
            "odds_snapshot_hash",
            "feature_snapshot_hash",
        }
        features = {key: value for key, value in row.items() if key not in reserved and value != ""}
    return features


def _candidate(row: dict[str, Any]) -> dict[str, Any]:
    race_id = str(row.get("race_id") or "").strip()
    selection = str(row.get("selection") or row.get("selection_id") or row.get("horse_id") or row.get("horse_number") or "").strip()
    if not race_id or not selection:
        raise ValueError("each input row must include race_id and selection/horse_id")
    odds = float(row.get("odds") or 0.0)
    if odds <= 1.0:
        raise ValueError(f"invalid odds for {race_id}:{selection}: {odds}")
    return {
        "race_id": race_id,
        "selection": selection,
        "odds": odds,
        "features": _features(row),
        "odds_snapshot_hash": str(row.get("odds_snapshot_hash") or f"{race_id}:{selection}:odds"),
        "feature_snapshot_hash": str(row.get("feature_snapshot_hash") or f"{race_id}:{selection}:features"),
    }


def _outcomes(rows: list[dict[str, Any]]) -> dict[str, dict[str, bool]]:
    by_race: dict[str, dict[str, bool]] = {}
    for row in rows:
        race_id = str(row.get("race_id") or "").strip()
        selection = str(row.get("selection") or row.get("selection_id") or row.get("horse_id") or row.get("horse_number") or "").strip()
        if not race_id or not selection:
            continue
        if "hit" in row and row["hit"] != "":
            hit = bool(int(row["hit"]))
        elif "target_win" in row and row["target_win"] != "":
            hit = bool(int(row["target_win"]))
        elif "winner" in row and row["winner"] != "":
            hit = str(row["winner"]) == selection
        elif "outcome" in row and row["outcome"] != "":
            hit = str(row["outcome"]).lower() in {"1", "true", "win", "winner"}
        else:
            continue
        by_race.setdefault(race_id, {})[selection] = hit
    return by_race


def build_loop(decision_log_path: Path, csv_report_path: Path) -> Phase2OperationalLoop:
    risk = RiskManager()
    calibrator = CalibrationRefitJob(auto_refit_enabled=False).load_calibrator(ProbabilityCalibrator())
    engine = DecisionEngine(
        predictor=Predictor(),
        bet_sizer=BetSizer(risk_manager=risk),
        risk_manager=risk,
        edge_calculator=EdgeCalculator(),
        calibrator=calibrator,
    )
    executor = BetExecutor(
        risk_manager=risk,
        decision_log_path=str(decision_log_path),
        csv_report_path=str(csv_report_path),
        shadow_mode=True,
        safe_mode=True,
    )
    return Phase2OperationalLoop(decision_engine=engine, bet_executor=executor, bets_log_path=str(csv_report_path))


def run_shadow_file(input_path: Path, decision_log_path: Path, csv_report_path: Path, *, settle: bool = False) -> dict[str, Any]:
    rows = _load_rows(input_path)
    candidates_by_race: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        candidate = _candidate(row)
        candidates_by_race.setdefault(candidate["race_id"], []).append(candidate)

    loop = build_loop(decision_log_path, csv_report_path)
    outcome_by_race = _outcomes(rows)
    submitted = 0
    settled = 0
    for race_id in sorted(candidates_by_race):
        decisions = loop.decide_race(race_id, candidates_by_race[race_id])
        submitted += len(decisions)
        if settle and race_id in outcome_by_race and decisions:
            loop.settle_race(race_id, decisions, outcome_by_race[race_id], regime="SHADOW")
            settled += len(decisions)
    return {
        "input": str(input_path),
        "races": len(candidates_by_race),
        "submitted_shadow_decisions": submitted,
        "settled_shadow_decisions": settled,
        "decision_log": str(decision_log_path),
        "csv_report": str(csv_report_path),
        "shadow_mode": True,
        "safe_mode": True,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Append strict shadow decisions from a real race/market input file")
    parser.add_argument("--input", required=True, help="CSV or JSONL with race_id, selection/horse_id, odds, and optional features")
    parser.add_argument("--decision-log", default="logs/decisions.jsonl")
    parser.add_argument("--csv-report", default="derived/bets.csv")
    parser.add_argument("--settle", action="store_true", help="Also log settlement events when hit/target_win/winner is present")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_shadow_file(
        Path(args.input),
        Path(args.decision_log),
        Path(args.csv_report),
        settle=args.settle,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
