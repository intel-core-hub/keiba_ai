"""Smoke test for edge & bet sizing changes."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.prediction.edge_calculator import EdgeCalculator
from core.bet_sizer import BetConfig, BetSizer


def main():
    ec = EdgeCalculator()
    print("EdgeCalculator odds_slip", ec.odds_slip)
    print(ec.calculate_edge(0.25, 5.0))

    cfg = BetConfig()
    cfg.odds_slip = 0.05
    bs = BetSizer(config=cfg)
    print("core.BetSizer odds_slip", bs.cfg.odds_slip, "expected_edge", bs.expected_edge(0.2, 5.0))


if __name__ == "__main__":
    main()
