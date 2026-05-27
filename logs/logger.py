# logs/logger.py

import csv
import os
from datetime import datetime


class Logger:

    def __init__(self):

        os.makedirs("logs", exist_ok=True)

        self.bets_file = "logs/bets.csv"
        self.race_file = "logs/races.csv"
        self.diag_file = "logs/diagnostics.csv"

        self._init_file(self.bets_file, [
            "timestamp",
            "race_id",
            "selection",
            "probability",
            "odds",
            "edge",
            "bet_size",
            "result_id",
        ])

        self._init_file(self.race_file, [
            "timestamp",
            "race_id",
            "bankroll",
            "total_risk",
            "bet_count",
        ])

        self._init_file(self.diag_file, [
            "timestamp",
            "bankroll",
            "drawdown",
            "profit_ratio",
            "risk_multiplier",
        ])

    # ------------------------------------------------
    # 初期化
    # ------------------------------------------------

    def _init_file(self, path, header):

        if not os.path.exists(path):
            with open(path, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(header)

    # ------------------------------------------------
    # BET LOG
    # ------------------------------------------------

    def log_bet(self, decision, bankroll):

        result_id = (
            f"{decision.race_id}_"
            f"{decision.selection}_"
            f"{datetime.now().timestamp()}"
        )

        with open(self.bets_file, "a", newline="", encoding="utf-8") as f:

            csv.writer(f).writerow([
                datetime.now().isoformat(),
                decision.race_id,
                decision.selection,
                round(decision.probability, 5),
                decision.odds,
                round(decision.edge, 5),
                decision.bet_size,
                result_id,
            ])

        return result_id

    # ------------------------------------------------
    # RACE SUMMARY（超重要）
    # ------------------------------------------------

    def log_race_summary(self, race_id, bankroll, total_risk, bet_count):

        with open(self.race_file, "a", newline="", encoding="utf-8") as f:

            csv.writer(f).writerow([
                datetime.now().isoformat(),
                race_id,
                bankroll,
                total_risk,
                bet_count,
            ])

    # ------------------------------------------------
    # DIAGNOSTICS LOG（最重要）
    # ------------------------------------------------

    def log_diagnostics(self, status):

        with open(self.diag_file, "a", newline="", encoding="utf-8") as f:

            csv.writer(f).writerow([
                datetime.now().isoformat(),
                status["bankroll"],
                status["drawdown"],
                status["profit_ratio"],
                status["risk_multiplier"],
            ])