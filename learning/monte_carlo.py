# learning/monte_carlo.py

import numpy as np


class MonteCarloSurvivalSimulator:
    """
    Survival Monte Carlo Engine

    目的:
    - risk of ruin
    - drawdown distribution
    - bankroll survival
    - Kelly安全性検証

    を確認する

    最重要:
    「期待値」ではなく
    「生き残れるか」
    """

    def __init__(
        self,
        initial_bankroll=20000,
        ruin_threshold=0.3,
    ):

        self.initial_bankroll = (
            initial_bankroll
        )

        # 70% lossで死亡
        self.ruin_threshold = (
            ruin_threshold
        )

    # =================================================
    # Single Simulation
    # =================================================

    def run_simulation(
        self,
        probabilities,
        odds,
        stakes,
        n_bets=None,
    ):

        bankroll = self.initial_bankroll

        peak = bankroll

        bankroll_curve = [bankroll]

        ruin = False

        if n_bets is None:
            n_bets = len(probabilities)

        for i in range(n_bets):

            p = probabilities[
                i % len(probabilities)
            ]

            o = odds[
                i % len(odds)
            ]

            stake = stakes[
                i % len(stakes)
            ]

            # -----------------------------------------
            # survival protection
            # -----------------------------------------

            if stake > bankroll:
                stake = bankroll

            if bankroll <= 0:
                ruin = True
                break

            # -----------------------------------------
            # random outcome
            # -----------------------------------------

            hit = np.random.rand() < p

            # -----------------------------------------
            # profit
            # -----------------------------------------

            if hit:

                profit = (
                    stake * (o - 1)
                )

            else:

                profit = -stake

            bankroll += profit

            peak = max(peak, bankroll)

            bankroll_curve.append(bankroll)

            # -----------------------------------------
            # ruin detection
            # -----------------------------------------

            if bankroll < (
                self.initial_bankroll
                * self.ruin_threshold
            ):

                ruin = True
                break

        # -----------------------------------------
        # drawdown
        # -----------------------------------------

        curve = np.array(bankroll_curve)

        peaks = np.maximum.accumulate(
            curve
        )

        dd = 1 - curve / peaks

        max_dd = np.max(dd)

        return {
            "final_bankroll": bankroll,
            "max_drawdown": float(max_dd),
            "ruin": ruin,
            "curve": bankroll_curve,
        }

    # =================================================
    # Batch Simulation
    # =================================================

    def simulate(
        self,
        probabilities,
        odds,
        stakes,
        simulations=1000,
        n_bets=500,
    ):

        finals = []

        drawdowns = []

        ruins = 0

        for _ in range(simulations):

            result = self.run_simulation(
                probabilities,
                odds,
                stakes,
                n_bets=n_bets,
            )

            finals.append(
                result["final_bankroll"]
            )

            drawdowns.append(
                result["max_drawdown"]
            )

            if result["ruin"]:
                ruins += 1

        # -----------------------------------------
        # statistics
        # -----------------------------------------

        ruin_prob = ruins / simulations

        median_final = np.median(finals)

        mean_final = np.mean(finals)

        worst_final = np.min(finals)

        best_final = np.max(finals)

        median_dd = np.median(drawdowns)

        worst_dd = np.max(drawdowns)

        # -----------------------------------------
        # survival score
        # -----------------------------------------

        survival_score = 1.0

        if ruin_prob > 0.25:
            survival_score *= 0.5

        elif ruin_prob > 0.10:
            survival_score *= 0.75

        if worst_dd > 0.5:
            survival_score *= 0.7

        # -----------------------------------------
        # report
        # -----------------------------------------

        return {
            "simulations": simulations,

            "ruin_probability": round(
                ruin_prob,
                4,
            ),

            "median_final_bankroll": round(
                median_final,
                2,
            ),

            "mean_final_bankroll": round(
                mean_final,
                2,
            ),

            "worst_final_bankroll": round(
                worst_final,
                2,
            ),

            "best_final_bankroll": round(
                best_final,
                2,
            ),

            "median_drawdown": round(
                median_dd,
                4,
            ),

            "worst_drawdown": round(
                worst_dd,
                4,
            ),

            "survival_score": round(
                survival_score,
                4,
            ),
        }

    # =================================================
    # Kelly Stress Test
    # =================================================

    def kelly_stress_test(
        self,
        probabilities,
        odds,
        bankroll,
        kelly_fractions=[
            0.1,
            0.25,
            0.5,
            1.0,
        ],
    ):

        results = {}

        for frac in kelly_fractions:

            stakes = []

            for p, o in zip(
                probabilities,
                odds,
            ):

                b = o - 1

                if b <= 0:
                    stakes.append(0)
                    continue

                q = 1 - p

                kelly = (
                    (b * p - q) / b
                )

                kelly = max(kelly, 0)

                stake = (
                    bankroll
                    * kelly
                    * frac
                )

                stakes.append(stake)

            report = self.simulate(
                probabilities,
                odds,
                stakes,
                simulations=500,
                n_bets=300,
            )

            results[
                f"{frac} Kelly"
            ] = report

        return results