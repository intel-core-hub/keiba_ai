# strategies/explorer_ai.py

import numpy as np
from typing import List, Dict, Optional
from dataclasses import dataclass
from core.utilities import now_jst


@dataclass
class ExplorerBetDecision:
    """
    エクスプローラー馬券決定
    """
    race_id: str
    horse_id: str
    bet_type: str  # "place" or "exacta"
    bet_size: float
    odds: float
    exploration_score: float
    timestamp: str


class ExplorerAI:
    name = "explorer_ai"
    """
    高オッズ探索戦略（穴馬狙い）

    目的:
    - 市場が過剰に割引いている馬を活用
    - 高オッズ馬での大きなプロフィット機会を捕捉
    - regime=CHAOS では休止（不確実性が高い）

    思想:
    「みんなが避けている馬」
    にこそ
    「価値がある」
    """

    def __init__(
        self,
        predictor=None,
        bet_sizer=None,
        min_odds: float = 10.0,
        max_odds: float = 50.0,
        min_ai_prob: float = 0.08,
        exploration_threshold: float = 0.15,
    ):
        """
        初期化

        Args:
            min_odds: 最小オッズ（穴馬の定義下限）
            max_odds: 最大オッズ（現実的な上限）
            min_ai_prob: 最小AI確率（ゴミは避ける）
            exploration_threshold: 探索スコアの閾値
        """
        self.min_odds = min_odds
        self.max_odds = max_odds
        self.min_ai_prob = min_ai_prob
        self.exploration_threshold = exploration_threshold
        self.predictor = predictor
        self.bet_sizer = bet_sizer
        self._last_metrics = {
            "sharpe": 0.0,
            "profit": 0.0,
            "drawdown": 0.0,
            "volatility": 0.0,
        }

    # =================================================
    # Dark Horse Detection
    # =================================================

    def find_dark_horses(
        self,
        horses: Dict[str, dict],
    ) -> List[Dict[str, any]]:
        """
        穴馬を検出

        条件:
        - オッズが高い（min_odds 以上）
        - AI が合理的な確率を付けている
        - 市場が過剰に割引いている

        Args:
            horses: 馬情報辞書

        Returns:
            穴馬リスト
        """
        dark_horses = []

        for horse_id, info in horses.items():
            ai_prob = info.get("ai_prob", 0.0)
            odds = info.get("odds", 0.0)

            # フィルタ条件
            if odds < self.min_odds or odds > self.max_odds:
                continue

            if ai_prob < self.min_ai_prob:
                continue

            # 市場確率を推定
            market_implied_prob = 1.0 / odds if odds > 1.0 else 0.0

            # AI と市場の乖離度
            divergence = ai_prob / max(market_implied_prob, 0.01)

            # 期待値
            ev = ai_prob * odds - 1.0

            dark_horses.append({
                "horse_id": horse_id,
                "odds": odds,
                "ai_prob": ai_prob,
                "market_prob": market_implied_prob,
                "divergence": divergence,
                "ev": ev,
            })

        return dark_horses

    # =================================================
    # Exploration Score
    # =================================================

    def calculate_exploration_score(
        self,
        odds: float,
        ai_prob: float,
        form_quality: float = 0.5,
        regime: str = "NORMAL",
    ) -> float:
        """
        探索スコアを計算

        高スコア = 調査する価値がある

        Args:
            odds: オッズ
            ai_prob: AI 推定確率
            form_quality: フォーム品質（0-1）
            regime: マーケットレジーム

        Returns:
            探索スコア（0-1）
        """
        # 基本スコア = EV を正規化
        ev = ai_prob * odds - 1.0
        ev_score = max(0.0, min(1.0, ev / 2.0))  # 0-200% EV を 0-1 に正規化

        # オッズスコア（高いほど価値がある）
        odds_score = min(1.0, (odds - self.min_odds) / self.max_odds)

        # フォーム品質スコア
        form_score = form_quality

        # レジーム調整
        regime_multiplier = {
            "NORMAL": 1.0,
            "FAVORITE_DOMINANCE": 1.2,  # 穴馬が有利になる状況
            "CHAOS": 0.0,  # 禁止
            "EFFICIENT": 0.5,
        }
        regime_mult = regime_multiplier.get(regime, 1.0)

        if regime_mult == 0.0:
            return 0.0

        # 総合スコア
        exploration_score = (
            ev_score * 0.4 +
            odds_score * 0.3 +
            form_score * 0.3
        ) * regime_mult

        return exploration_score

    # =================================================
    # Bet Type Selection
    # =================================================

    def select_bet_type(
        self,
        exploration_score: float,
        odds: float,
    ) -> str:
        """
        ベットタイプを選択

        Args:
            exploration_score: 探索スコア
            odds: オッズ

        Returns:
            ベットタイプ（"place" or "exacta"）
        """
        # スコアが高い場合は連下もサポート
        if exploration_score > 0.7 and odds > 20.0:
            return "exacta"  # 連下で大きく狙う

        return "place"  # 安全に馬連で狙う

    # =================================================
    # Regime Check
    # =================================================

    def is_tradable_regime(
        self,
        regime: str,
    ) -> bool:
        """
        取引可能なレジームかを判定

        CHAOS では休止する（確実性が低い）

        Args:
            regime: マーケットレジーム

        Returns:
            取引可能なら True
        """
        forbidden_regimes = ["CHAOS", "EFFICIENT"]
        return regime not in forbidden_regimes

    # =================================================
    # Position Sizing
    # =================================================

    def calculate_position_size(
        self,
        exploration_score: float,
        odds: float,
        bankroll: float,
    ) -> float:
        """
        ポジションサイズを計算

        Args:
            exploration_score: 探索スコア
            odds: オッズ
            bankroll: バンクロール

        Returns:
            ベットサイズ
        """
        # 探索スコアが低い場合は控えめに
        if exploration_score < self.exploration_threshold:
            return 0.0

        # 高オッズへの投資は控えめに（リスク管理）
        odds_factor = 1.0 / np.log10(odds)  # オッズが高いほど小さくなる

        # ベット割合
        base_fraction = 0.05  # 5% ベース
        bet_fraction = base_fraction * exploration_score * odds_factor

        bet_size = bankroll * bet_fraction

        return bet_size

    # =================================================
    # Decision Making
    # =================================================

    def make_decision(
        self,
        race_id: str,
        horses: Dict[str, dict],
        bankroll: float,
        regime: str = "NORMAL",
    ) -> Optional[ExplorerBetDecision]:
        """
        探索戦略に基づいて決定

        Args:
            race_id: レースID
            horses: 馬情報辞書
            bankroll: バンクロール
            regime: マーケットレジーム

        Returns:
            ExplorerBetDecision またはNone
        """
        # レジームチェック
        if not self.is_tradable_regime(regime):
            return None

        # 穴馬を検出
        dark_horses = self.find_dark_horses(horses)

        if not dark_horses:
            return None

        # 各穴馬の探索スコアを計算
        scored_horses = []
        for horse in dark_horses:
            horse_info = horses[horse["horse_id"]]
            form_quality = horse_info.get("form_quality", 0.5)

            score = self.calculate_exploration_score(
                horse["odds"],
                horse["ai_prob"],
                form_quality,
                regime,
            )

            if score > self.exploration_threshold:
                scored_horses.append((horse, score))

        if not scored_horses:
            return None

        # トップスコアの馬を選択
        best_horse, best_score = max(scored_horses, key=lambda x: x[1])

        # ベットサイズを計算
        bet_size = self.calculate_position_size(
            best_score, best_horse["odds"], bankroll
        )

        if bet_size <= 0:
            return None

        # ベットタイプを選択
        bet_type = self.select_bet_type(best_score, best_horse["odds"])

        return ExplorerBetDecision(
            race_id=race_id,
            horse_id=best_horse["horse_id"],
            bet_type=bet_type,
            bet_size=bet_size,
            odds=best_horse["odds"],
            exploration_score=best_score,
            timestamp=now_jst().isoformat(),
        )

    # =================================================
    # Analysis
    # =================================================

    def dark_horse_analysis(
        self,
        horses: Dict[str, dict],
    ) -> Dict[str, any]:
        """
        穴馬分析

        Args:
            horses: 馬情報辞書

        Returns:
            分析結果
        """
        dark_horses = self.find_dark_horses(horses)

        if not dark_horses:
            return {"count": 0, "total_ev": 0.0}

        total_ev = sum(h["ev"] for h in dark_horses)
        avg_ev = total_ev / len(dark_horses)
        avg_divergence = np.mean([h["divergence"] for h in dark_horses])

        return {
            "count": len(dark_horses),
            "total_ev": total_ev,
            "avg_ev": avg_ev,
            "avg_divergence": avg_divergence,
            "best_opportunity": dark_horses[0] if dark_horses else None,
        }

    def run(self, races: List[dict], weight: float):
        decisions = []
        bet_sizes = []

        for race in races:
            race_id = race.get("race_id") or race.get("id") or "UNKNOWN"
            horses_info = race.get("horses") or {}
            horses_dict = horses_info if isinstance(horses_info, dict) else {
                str(h.get("id") or h.get("horse_id") or h.get("selection") or ""): h
                for h in horses_info
            }

            decision = self.make_decision(
                race_id=race_id,
                horses=horses_dict,
                bankroll=float(weight),
                regime=race.get("regime", "NORMAL"),
            )
            if decision is not None:
                decisions.append(decision)
                bet_sizes.append(float(decision.bet_size))

        self._last_metrics = {
            "sharpe": 0.0,
            "profit": 0.0,
            "drawdown": 0.0,
            "volatility": float(np.std(bet_sizes)) if bet_sizes else 0.0,
        }

        return decisions

    def metrics(self):
        return dict(self._last_metrics)


# ---------------------------------------------------------------------------
# Compatibility adapter for PortfolioManager / MetaEvaluator
# ---------------------------------------------------------------------------


class ExplorerStrategy:
    name = "explorer_ai"

    def __init__(self, predictor=None, bet_sizer=None, **kwargs):
        self.predictor = predictor
        self.bet_sizer = bet_sizer
        self.impl = ExplorerAI(**{k: v for k, v in kwargs.items()})

    def run(self, races: List[dict], weight: float = 1.0):
        decisions = []
        bankroll = weight
        for race in races:
            race_id = race.get("race_id") or race.get("id")
            horses_info = race.get("horses") or {}

            # Convert to dict if list provided
            horses_dict = horses_info if isinstance(horses_info, dict) else {h.get("id") or h.get("horse_id"): h for h in horses_info}

            decision = self.impl.make_decision(race_id, horses_dict, bankroll, regime=race.get("regime", "NORMAL"))
            if decision is not None:
                decisions.append(decision)

        return decisions

    def metrics(self):
        return {"sharpe": 0.0, "profit": 0.0, "drawdown": 0.0, "volatility": 0.0}
