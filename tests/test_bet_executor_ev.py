"""Tests for BetExecutor odds/EV logging contract."""

from __future__ import annotations

import csv
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.betting.decision_engine import Decision
from core.execution.bet_executor import BetExecutor


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


if __name__ == "__main__":
    test_bet_executor_writes_ev_and_confirmed_odds()
    print("ok")
