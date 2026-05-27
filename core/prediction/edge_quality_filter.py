import numpy as np


class EdgeQualityFilter:

    def __init__(
        self,
        max_prob_gap=0.25,
        min_quality=0.4,
    ):
        self.max_prob_gap = max_prob_gap
        self.min_quality = min_quality

    # =========================
    # Quality Score
    # =========================
    def evaluate(
        self,
        ai_prob,
        market_prob,
        edge,
        odds,
        recent_brier=0.15,
        sample_size=50,
        uncertainty_score=None,
        drift_score=None,
        calibration_gap=None,
    ):

        scores = []

        # ----------------------
        # 1. 市場乖離ペナルティ
        # ----------------------
        prob_gap = abs(ai_prob - market_prob)

        gap_score = 1 - min(
            prob_gap / self.max_prob_gap,
            1.0,
        )
        scores.append(gap_score)

        # ----------------------
        # 2. オッズ帯信頼度
        # ----------------------
        if odds < 5:
            odds_score = 1.0
        elif odds < 15:
            odds_score = 0.8
        else:
            odds_score = 0.5

        scores.append(odds_score)

        # ----------------------
        # 3. サンプル数
        # ----------------------
        sample_score = min(sample_size / 100, 1.0)
        scores.append(sample_score)

        # ----------------------
        # 4. モデル状態（Brier）
        # ----------------------
        model_score = np.clip(
            1 - recent_brier,
            0,
            1,
        )
        scores.append(model_score)

        # ----------------------
        # 5. 巨大Edge抑制
        # ----------------------
        edge_penalty = np.exp(-abs(edge) * 5)
        scores.append(edge_penalty)

        # ----------------------
        # 6. uncertainty / drift penalty
        # ----------------------
        uncertainty_penalty = 1.0
        if uncertainty_score is not None:
            uncertainty_penalty *= float(np.clip(1 - float(uncertainty_score) * 0.65, 0.20, 1.0))
        if drift_score is not None:
            uncertainty_penalty *= float(np.clip(1 - float(drift_score) * 1.50, 0.25, 1.0))
        if calibration_gap is not None:
            uncertainty_penalty *= float(np.clip(1 - float(calibration_gap) * 2.0, 0.35, 1.0))
        scores.append(uncertainty_penalty)

        quality = float(np.mean(scores))

        return quality

    # =========================
    # 最終購入判定
    # =========================
    def is_high_quality(self, quality):
        return quality >= self.min_quality