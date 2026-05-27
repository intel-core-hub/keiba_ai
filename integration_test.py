# integration_test.py

import random
import traceback

from main import SurvivalOS


# =====================================================
# Integration Test
# =====================================================

class IntegrationTest:
    """
    Full System Integration Test

    目的:
    - 全層接続確認
    - runtime error検出
    - state transition確認
    - shutdown確認
    - survival flow確認

    最重要:
    「全部繋げると壊れる」
    を防ぐ
    """

    def __init__(self):

        self.system = SurvivalOS()

        self.total_races = 0

        self.total_bets = 0

        self.total_profit = 0

        self.errors = []

    # =================================================
    # Generate Race
    # =================================================

    def generate_race(
        self,
        race_id,
    ):

        """
        疑似レース生成
        """

        horses = []

        horse_count = random.randint(
            8,
            18,
        )

        for i in range(horse_count):

            odds = round(

                random.uniform(
                    1.3,
                    30,
                ),

                2,
            )

            horses.append({

                "selection":
                    f"Horse_{i}",

                "odds":
                    odds,

                "features": {

                    "rank_score":
                        random.uniform(
                            0,
                            1,
                        ),

                    "speed_index":
                        random.uniform(
                            50,
                            120,
                        ),

                    "odds_value":
                        random.uniform(
                            0,
                            1,
                        ),

                    "form":
                        random.uniform(
                            0,
                            1,
                        ),
                },
            })

        return {

            "race_id": race_id,

            "horses": horses,
        }

    # =================================================
    # Simulate Winners
    # =================================================

    def simulate_winner(
        self,
        horses,
    ):

        """
        オッズベース勝者生成

        人気馬ほど勝ちやすい
        """

        weights = []

        for h in horses:

            odds = h["odds"]

            weight = 1 / odds

            weights.append(weight)

        total = sum(weights)

        probs = [
            w / total
            for w in weights
        ]

        winner = random.choices(

            horses,

            weights=probs,

            k=1,
        )[0]

        return [winner["selection"]]

    # =================================================
    # Single Race Test
    # =================================================

    def test_single_race(
        self,
        race_id,
    ):

        race = self.generate_race(
            race_id
        )

        decisions = (
            self.system.process_race(

                race_id=(
                    race["race_id"]
                ),

                candidates=(
                    race["horses"]
                ),
            )
        )

        winners = self.simulate_winner(
            race["horses"]
        )

        self.system.settle_race(

            decisions=decisions,

            winners=winners,
        )

        # -----------------------------------------
        # stats
        # -----------------------------------------

        self.total_races += 1

        self.total_bets += len(
            decisions
        )

        # rough profit estimation
        try:

            bankroll = (
                self.system
                .risk_manager
                .bankroll
            )

            initial = (
                self.system
                .capital
                .initial_capital
            )

            self.total_profit = (
                bankroll - initial
            )

        except:
            pass

        return {

            "race_id":
                race_id,

            "bets":
                len(decisions),

            "winners":
                winners,
        }

    # =================================================
    # Run Full Test
    # =================================================

    def run(
        self,
        races=100,
    ):

        print("\n====================")
        print("INTEGRATION TEST")
        print("====================")

        for i in range(races):

            race_id = (
                f"SIM_{i}"
            )

            try:

                result = (
                    self.test_single_race(
                        race_id
                    )
                )

                # -----------------------------------------
                # progress
                # -----------------------------------------

                if i % 10 == 0:

                    print(
                        f"\n[{i}] "
                        f"bets="
                        f"{result['bets']} "
                        f"profit="
                        f"{round(self.total_profit,2)}"
                    )

                    self.system.diagnostics()

                # -----------------------------------------
                # shutdown
                # -----------------------------------------

                if (
                    self.system
                    .self_destruct
                    .destroyed
                ):

                    print(
                        "\n[SELF DESTRUCT TRIGGERED]"
                    )

                    break

                if (
                    self.system
                    .capital
                    .should_shutdown()
                ):

                    print(
                        "\n[CAPITAL SHUTDOWN]"
                    )

                    break

            except Exception as e:

                error = {

                    "race_id":
                        race_id,

                    "error":
                        str(e),

                    "trace":
                        traceback.format_exc(),
                }

                self.errors.append(
                    error
                )

                print(
                    "\n[ERROR]",
                    race_id,
                )

                print(e)

        return self.summary()

    # =================================================
    # Summary
    # =================================================

    def summary(self):

        bankroll = (
            self.system
            .risk_manager
            .bankroll
        )

        capital_diag = (
            self.system
            .capital
            .diagnostics()
        )

        reliability = (
            self.system
            .reliability
            .analyze()
        )

        regime = (
            self.system
            .regime_detector
            .status()
        )

        meta = (
            self.system
            .meta_controller
            .diagnostics()
        )

        report = {

            # -----------------------------------------
            # runtime
            # -----------------------------------------

            "races":
                self.total_races,

            "bets":
                self.total_bets,

            "errors":
                len(self.errors),

            # -----------------------------------------
            # bankroll
            # -----------------------------------------

            "final_bankroll":
                round(
                    bankroll,
                    2,
                ),

            "profit":
                round(
                    self.total_profit,
                    2,
                ),

            # -----------------------------------------
            # capital
            # -----------------------------------------

            "capital_mode":
                capital_diag["mode"],

            "drawdown":
                capital_diag["drawdown"],

            "survival_score":
                capital_diag[
                    "survival_score"
                ],

            # -----------------------------------------
            # reliability
            # -----------------------------------------

            "ece":
                reliability.get(
                    "expected_calibration_error",
                    None,
                ),

            "max_gap":
                reliability.get(
                    "max_gap",
                    None,
                ),

            # -----------------------------------------
            # regime
            # -----------------------------------------

            "regime":
                regime["regime"],

            # -----------------------------------------
            # meta
            # -----------------------------------------

            "meta_state":
                meta["current_state"],

            # -----------------------------------------
            # self destruct
            # -----------------------------------------

            "destroyed":
                self.system
                .self_destruct
                .destroyed,
        }

        print("\n====================")
        print("FINAL SUMMARY")
        print("====================")

        for k, v in report.items():

            print(f"{k}: {v}")

        # =================================================
        # Error Dump
        # =================================================

        if len(self.errors) > 0:

            print("\n====================")
            print("ERRORS")
            print("====================")

            for e in self.errors[:5]:

                print("\n---")

                print(
                    "race:",
                    e["race_id"]
                )

                print(
                    "error:",
                    e["error"]
                )

        return report


# =====================================================
# Main
# =====================================================

if __name__ == "__main__":

    test = IntegrationTest()

    report = test.run(
        races=200
    )