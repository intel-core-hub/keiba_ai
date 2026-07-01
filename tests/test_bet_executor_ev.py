"""Tests for BetExecutor odds/EV logging contract."""

from __future__ import annotations

import csv
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.betting.decision_engine import Decision
from core.execution.bet_executor import BetExecutor


def _with_risk_clamp_proof(decision):
  decision.risk_limits_hash = "risk-hash"
  decision.risk_clamp_reason = "risk_clamp_allowed"
  decision.risk_clamp_allowed = True
  decision.policy_hash = "policy-hash"
  decision.model_hash = "model-hash"
  decision.odds_snapshot_hash = "odds-hash"
  decision.feature_snapshot_hash = "feature-hash"
  return decision


class _StubRisk:
  bankroll = 100_000.0

  def status(self):
    return {
      "bankroll": self.bankroll,
      "drawdown": 0.0,
      "risk_multiplier": 1.0,
      "lose_streak": 0,
      "win_streak": 0,
      "race_risk_used": 0.0,
    }


def _read_last_row(path: Path) -> dict:
  with path.open(encoding="utf-8") as handle:
    rows = list(csv.DictReader(handle))
  return rows[-1]


def _read_jsonl(path: Path) -> list[dict]:
  with path.open(encoding="utf-8") as handle:
    return [json.loads(line) for line in handle if line.strip()]


def test_bet_executor_writes_ev_and_confirmed_odds():
  with tempfile.TemporaryDirectory() as tmp:
    log_path = Path(tmp) / "bets.csv"
    executor = BetExecutor(
      risk_manager=_StubRisk(),
      log_path=str(log_path),
      shadow_mode=True,
      safe_mode=True,
      odds_confirmer=lambda info: float(info["predicted_odds"]) * 0.95,
    )

    decision = _with_risk_clamp_proof(Decision(
      race_id="R1",
      selection="H1",
      probability=0.2,
      calibrated_probability=0.18,
      market_probability=0.1,
      odds=10.0,
      edge=0.05,
      expected_value=0.8,
      uncertainty_score=0.1,
      edge_quality=0.7,
      bet_size=500,
    ))

    executor.execute_bet(decision)
    row = _read_last_row(log_path)

    assert row["predicted_odds"] == "10.0"
    assert float(row["confirmed_odds"]) == 9.5
    assert float(row["expected_value"]) == 0.8
    assert float(row["slippage_pct"]) < 0
    assert row["mode"] == "SHADOW_MODE"

    executor.update_result(decision, hit=1, profit=4500.0)
    settled = _read_last_row(log_path)
    assert settled["hit"] == "1"
    assert float(settled["profit"]) == 4500.0


def test_bet_executor_blocks_manual_decision_without_risk_clamp_proof():
  calls = {"count": 0}

  def api_client(info):
    calls["count"] += 1
    return {"status": "submitted"}

  with tempfile.TemporaryDirectory() as tmp:
    executor = BetExecutor(
      risk_manager=_StubRisk(),
      log_path=str(Path(tmp) / "bets.csv"),
      shadow_mode=False,
      safe_mode=True,
      api_client=api_client,
    )
    decision = Decision(
      race_id="R1",
      selection="H1",
      probability=0.2,
      calibrated_probability=0.18,
      market_probability=0.1,
      odds=10.0,
      edge=0.05,
      expected_value=0.8,
      uncertainty_score=0.1,
      edge_quality=0.7,
      bet_size=500,
    )

    result = executor.execute_bet(decision)

    assert result["blocked"] is True
    assert result["state"] == "NO_BET"
    assert result["reason"] == "missing_odds"
    assert calls["count"] == 0


def test_bet_executor_allows_valid_risk_clamp_proof_in_shadow_mode():
  with tempfile.TemporaryDirectory() as tmp:
    executor = BetExecutor(
      risk_manager=_StubRisk(),
      log_path=str(Path(tmp) / "bets.csv"),
      shadow_mode=True,
      safe_mode=True,
    )
    decision = _with_risk_clamp_proof(Decision(
      race_id="R1",
      selection="H1",
      probability=0.2,
      calibrated_probability=0.18,
      market_probability=0.1,
      odds=10.0,
      edge=0.05,
      expected_value=0.8,
      uncertainty_score=0.1,
      edge_quality=0.7,
      bet_size=500,
    ))

    result = executor.execute_bet(decision)

    assert result["blocked"] is False
    assert result["api_result"]["status"] == "shadow"


def test_bet_executor_writes_shadow_audit_event_lifecycle():
  with tempfile.TemporaryDirectory() as tmp:
    tmp_path = Path(tmp)
    executor = BetExecutor(
      risk_manager=_StubRisk(),
      decision_log_path=str(tmp_path / "decisions.jsonl"),
      csv_report_path=str(tmp_path / "bets.csv"),
      shadow_mode=True,
      safe_mode=True,
    )
    decision = _with_risk_clamp_proof(Decision(
      race_id="R1",
      selection="H1",
      probability=0.2,
      calibrated_probability=0.18,
      market_probability=0.1,
      odds=10.0,
      edge=0.05,
      expected_value=0.8,
      uncertainty_score=0.1,
      edge_quality=0.7,
      bet_size=500,
    ))

    executor.execute_bet(decision)
    executor.update_result(decision, hit=1, profit=4500.0)
    events = _read_jsonl(tmp_path / "decisions.jsonl")

    assert [event["event_type"] for event in events] == [
      "OddsSnapshotReceived",
      "FeatureSnapshotBuilt",
      "PredictionMade",
      "RiskClampEvaluated",
      "BetSubmitted",
      "BetRejected",
      "RaceSettled",
      "BankrollUpdated",
    ]
    assert "BetAccepted" not in {event["event_type"] for event in events}
    previous = None
    for event in events:
      assert event["event_id"]
      assert event["occurred_at_utc"]
      assert event["race_id"] == "R1"
      assert isinstance(event["payload"], dict)
      assert event["previous_hash"] == previous
      assert event["entry_hash"]
      previous = event["entry_hash"]
    submitted = next(event for event in events if event["event_type"] == "BetSubmitted")
    rejected = next(event for event in events if event["event_type"] == "BetRejected")
    settled = next(event for event in events if event["event_type"] == "RaceSettled")
    for key in (
      "odds_snapshot_hash",
      "feature_snapshot_hash",
      "model_hash",
      "calibration_hash",
      "bankroll_hash",
      "policy_hash",
      "risk_limits_hash",
    ):
      assert submitted["payload"][key]
      assert rejected["payload"][key]
      assert settled["payload"][key]


def test_bet_executor_does_not_submit_when_riskclamp_rejects():
  with tempfile.TemporaryDirectory() as tmp:
    tmp_path = Path(tmp)
    executor = BetExecutor(
      risk_manager=_StubRisk(),
      decision_log_path=str(tmp_path / "decisions.jsonl"),
      csv_report_path=str(tmp_path / "bets.csv"),
      shadow_mode=True,
      safe_mode=True,
    )
    decision = _with_risk_clamp_proof(Decision(
      race_id="R1",
      selection="H1",
      probability=0.2,
      calibrated_probability=0.18,
      market_probability=0.1,
      odds=10.0,
      edge=0.05,
      expected_value=0.8,
      uncertainty_score=0.1,
      edge_quality=0.7,
      bet_size=500,
    ))
    decision.odds_snapshot_hash = ""

    result = executor.execute_bet(decision)
    events = _read_jsonl(tmp_path / "decisions.jsonl")

    assert result["blocked"] is True
    assert "RiskClampEvaluated" in [event["event_type"] for event in events]
    assert "BetSubmitted" not in [event["event_type"] for event in events]


def test_bet_executor_blocks_false_risk_clamp_proof():
  with tempfile.TemporaryDirectory() as tmp:
    executor = BetExecutor(
      risk_manager=_StubRisk(),
      log_path=str(Path(tmp) / "bets.csv"),
      shadow_mode=True,
      safe_mode=True,
    )
    decision = _with_risk_clamp_proof(Decision(
      race_id="R1",
      selection="H1",
      probability=0.2,
      calibrated_probability=0.18,
      market_probability=0.1,
      odds=10.0,
      edge=0.05,
      expected_value=0.8,
      uncertainty_score=0.1,
      edge_quality=0.7,
      bet_size=500,
    ))
    decision.risk_clamp_allowed = False

    result = executor.execute_bet(decision)

    assert result["blocked"] is True
    assert result["reason"] == "risk_limits_invalid"


def test_bet_executor_blocks_missing_snapshot_hash_proof():
  with tempfile.TemporaryDirectory() as tmp:
    executor = BetExecutor(
      risk_manager=_StubRisk(),
      log_path=str(Path(tmp) / "bets.csv"),
      shadow_mode=True,
      safe_mode=True,
    )
    decision = _with_risk_clamp_proof(Decision(
      race_id="R1",
      selection="H1",
      probability=0.2,
      calibrated_probability=0.18,
      market_probability=0.1,
      odds=10.0,
      edge=0.05,
      expected_value=0.8,
      uncertainty_score=0.1,
      edge_quality=0.7,
      bet_size=500,
    ))
    decision.odds_snapshot_hash = ""

    result = executor.execute_bet(decision)

    assert result["blocked"] is True
    assert result["reason"] == "missing_odds"


if __name__ == "__main__":
    test_bet_executor_writes_ev_and_confirmed_odds()
    print("ok")
