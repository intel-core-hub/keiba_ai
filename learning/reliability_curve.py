# learning/reliability_curve.py

import numpy as np
import pandas as pd


class ReliabilityCurveAnalyzer:
    """
    Reliability Curve Analyzer

    目的:
    - calibration可視化
    - probability帯別検証
    - overconfidence検知
    - underconfidence検知
    - survival reliability

    最重要思想:
    「AIがどこで嘘をつくか」
    を知る
    """

    def __init__(
        self,
        bins=10,
    ):

        self.bins = bins

        self.records = []

    # =================================================
    # Record
    # =================================================

    def record(
        self,
        probability,
        hit,
    ):

        self.records.append({
            "probability": probability,
            "hit": hit,
        })

        # memory cap
        self.records = self.records[-5000:]

    # =================================================
    # Batch Record
    # =================================================

    def batch_record(
        self,
        probabilities,
        hits,
    ):

        for p, h in zip(
            probabilities,
            hits,
        ):

            self.record(
                probability=p,
                hit=h,
            )

    # =================================================
    # Build DataFrame
    # =================================================

    def dataframe(self):

        if len(self.records) == 0:

            return pd.DataFrame()

        return pd.DataFrame(
            self.records
        )

    # =================================================
    # Bin Assignment
    # =================================================

    def assign_bins(
        self,
        df,
    ):

        bins = np.linspace(
            0,
            1,
            self.bins + 1,
        )

        df["bin"] = pd.cut(
            df["probability"],
            bins=bins,
            include_lowest=True,
        )

        return df

    # =================================================
    # Analyze
    # =================================================

    def analyze(self):

        df = self.dataframe()

        if len(df) == 0:

            return {
                "error": "no data"
            }

        df = self.assign_bins(df)

        grouped = (
            df.groupby("bin", observed=False)
            .agg({
                "probability": [
                    "mean",
                    "count",
                ],
                "hit": "mean",
            })
        )

        grouped.columns = [
            "avg_probability",
            "count",
            "actual_rate",
        ]

        grouped = grouped.reset_index()

        # -----------------------------------------
        # calibration gap
        # -----------------------------------------

        grouped["gap"] = abs(
            grouped["avg_probability"]
            -
            grouped["actual_rate"]
        )

        # -----------------------------------------
        # bias classification
        # -----------------------------------------

        grouped["bias"] = grouped.apply(
            lambda row:
            self.bias_type(
                row["avg_probability"],
                row["actual_rate"],
            ),
            axis=1,
        )

        # -----------------------------------------
        # survival risk
        # -----------------------------------------

        grouped["risk"] = grouped.apply(
            lambda row:
            self.risk_level(
                row["gap"],
                row["count"],
            ),
            axis=1,
        )

        # -----------------------------------------
        # expected calibration error
        # -----------------------------------------

        total = grouped["count"].sum()

        probs = df["probability"].to_numpy(dtype=float)
        hits = df["hit"].to_numpy(dtype=float)

        brier = float(np.mean((probs - hits) ** 2))

        ece = (
            (
                grouped["gap"]
                * grouped["count"]
            ).sum()
            / total
        )

        half = max(1, len(probs) // 2)
        first_half = probs[:half]
        second_half = probs[half:]
        if len(second_half) == 0:
            drift_score = 0.0
        else:
            drift_score = float(abs(first_half.mean() - second_half.mean()))

        # -----------------------------------------
        # maximum deception zone
        # -----------------------------------------

        worst_idx = grouped["gap"].idxmax()

        worst_row = grouped.iloc[
            worst_idx
        ]

        return {

            "brier_score":
                round(float(brier), 4),

            "brier":
                round(float(brier), 4),

            "expected_calibration_error":
                round(float(ece), 4),

            "ece":
                round(float(ece), 4),

            "reliability":
                round(float(max(0.0, 1.0 - ece)), 4),

            "drift_score":
                round(float(drift_score), 4),

            "max_gap":
                round(
                    float(
                        worst_row["gap"]
                    ),
                    4,
                ),

            "worst_zone":
                str(
                    worst_row["bin"]
                ),

            "worst_bias":
                worst_row["bias"],

            "bin_analysis":
                grouped.to_dict(
                    orient="records"
                ),
        }

    # =================================================
    # Bias Type
    # =================================================

    def bias_type(
        self,
        predicted,
        actual,
    ):

        diff = predicted - actual

        if diff > 0.08:

            return (
                "SEVERE_OVERCONFIDENCE"
            )

        if diff > 0.03:

            return "OVERCONFIDENCE"

        if diff < -0.08:

            return (
                "SEVERE_UNDERCONFIDENCE"
            )

        if diff < -0.03:

            return "UNDERCONFIDENCE"

        return "CALIBRATED"

    # =================================================
    # Risk Level
    # =================================================

    def risk_level(
        self,
        gap,
        count,
    ):

        """
        count少ない場所は
        判断保留
        """

        if count < 20:
            return "LOW_SAMPLE"

        if gap > 0.10:
            return "EXTREME"

        if gap > 0.06:
            return "HIGH"

        if gap > 0.03:
            return "MEDIUM"

        return "LOW"

    # =================================================
    # Confidence Zone Safety
    # =================================================

    def confidence_zone_safety(
        self,
        min_samples=20,
    ):

        analysis = self.analyze()

        if "bin_analysis" not in analysis:
            return {}

        safe = {}

        for row in analysis[
            "bin_analysis"
        ]:

            if row["count"] < min_samples:
                continue

            zone = str(row["bin"])

            safe[zone] = {

                "safe":
                    row["gap"] < 0.03,

                "gap":
                    round(
                        float(row["gap"]),
                        4,
                    ),

                "bias":
                    row["bias"],

                "risk":
                    row["risk"],
            }

        return safe

    # =================================================
    # Dangerous Zones
    # =================================================

    def dangerous_zones(
        self,
        threshold=0.06,
    ):

        analysis = self.analyze()

        if "bin_analysis" not in analysis:
            return []

        dangerous = []

        for row in analysis[
            "bin_analysis"
        ]:

            if row["gap"] >= threshold:

                dangerous.append({

                    "zone":
                        str(row["bin"]),

                    "gap":
                        round(
                            float(row["gap"]),
                            4,
                        ),

                    "bias":
                        row["bias"],

                    "samples":
                        int(row["count"]),
                })

        return dangerous

    # =================================================
    # Survival Recommendation
    # =================================================

    def recommendation(self):

        analysis = self.analyze()

        if "expected_calibration_error" not in analysis:

            return "NO_DATA"

        ece = analysis[
            "expected_calibration_error"
        ]

        max_gap = analysis[
            "max_gap"
        ]

        if max_gap > 0.12:

            return (
                "STOP_HIGH_CONFIDENCE_BETS"
            )

        if ece > 0.06:

            return (
                "RECALIBRATION_REQUIRED"
            )

        if ece > 0.03:

            return (
                "REDUCE_POSITION_SIZE"
            )

        return "SYSTEM_STABLE"