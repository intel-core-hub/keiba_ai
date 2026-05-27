# strategies/market_ai.py

import numpy as np
from typing import List, Dict, Optional
from dataclasses import dataclass
from core.utilities import now_jst


@dataclass
class OddsSnapshot:
    """
    オッズ情報
    """
    horse_id: str
    win_odds: float
    place_odds: float
    market_prob: float  # 市場が織り込んでいる確率


@dataclass
class MarketBetDecision:
    """
    市場連動ベット決定
    """
    race_id: str
    horse_id: str
    bet_type: str  # "win" or "place"
    bet_size: float
    edge: float
    timestamp: str


class MarketAI:
    name = "market_ai"
    """
    市場オッズ連動戦略

    目的:
    - 市場オッズと AI 予測の乖離を検出
    - 市場が過剰に割引いている馬を狙う
    - 市場が過剰評価している馬を避ける

    思想:
    「AI vs 市場」
    の効率フロンティア
    """

    def __init__(
        self,
        predictor=None,
        bet_sizer=None,
        min_edge_threshold: float = 0.05,
        max_odds_ratio: float = 2.5,
        market_efficiency: float = 0.85,
    ):
        """
        初期化

        Args:
            min_edge_threshold: 最小エッジ閾値
            max_odds_ratio: 最大オッズ比率（市場が高すぎる警告）
            market_efficiency: 市場効率性（1.0 = 完全効率）
        """
        self.min_edge_threshold = min_edge_threshold
        self.max_odds_ratio = max_odds_ratio
        self.market_efficiency = market_efficiency
        self.predictor = predictor
        self.bet_sizer = bet_sizer
        self._last_metrics = {
            "sharpe": 0.0,
            "profit": 0.0,
            "drawdown": 0.0,
            "volatility": 0.0,
        }

    # =================================================
    # Market Probability Extraction
    # =================================================

    def extract_market_probability(
        self,
        odds: float,
        commission: float = 0.25,
    ) -> float:
        """
        オッズから市場確率を抽出

        市場確率 = (1 - commission) / odds

        Args:
            odds: オッズ
            commission: 競馬会の手数料率

        Returns:
            市場確率
        """
        if odds <= 1.0:
            return 0.0

        # 市場が織り込んでいる確率
        implied_prob = 1.0 / odds

        # 委託金を除去（簡易版）
        market_prob = implied_prob / (1 - commission)

        # 1を超えないように正規化
        return min(market_prob, 1.0)

    # =================================================
    # AI vs Market Comparison
    # =================================================

    def calculate_edge(
        self,
        ai_prob: float,
        market_prob: float,
        odds: float,
    ) -> float:
        """
        エッジを計算

        Edge = AI確率 * オッズ - 1

        Args:
            ai_prob: AI が推定した確率
            market_prob: 市場が織り込んでいる確率
            odds: オッズ

        Returns:
            エッジ（期待値）
        """
        # AI が正しい場合の期待値
        expected_value = ai_prob * odds - 1.0

        # 市場との乖離度
        prob_gap = ai_prob - market_prob

        # 調整済みエッジ
        adjusted_edge = expected_value * (1.0 + prob_gap)

        return adjusted_edge

    def find_value_bets(
        self,
        horses: Dict[str, dict],  # horse_id -> {ai_prob, odds, ...}
    ) -> List[Dict[str, any]]:
        """
        バリュー馬を検出

        市場が割引いている馬を見つける

        Args:
            horses: 馬情報辞書

        Returns:
            バリュー馬リスト
        """
        value_bets = []

        for horse_id, info in horses.items():
            ai_prob = info.get("ai_prob", 0.0)
            odds = info.get("odds", 0.0)

            if odds <= 1.0 or ai_prob <= 0.0:
                continue

            # 市場確率を抽出
            market_prob = self.extract_market_probability(odds)

            # エッジを計算
            edge = self.calculate_edge(ai_prob, market_prob, odds)

            # 市場との乖離度
            gap = ai_prob - market_prob

            if edge > self.min_edge_threshold:
                value_bets.append({
                    "horse_id": horse_id,
                    "ai_prob": ai_prob,
                    "market_prob": market_prob,
                    "odds": odds,
                    "edge": edge,
                    "gap": gap,
                })

        # エッジでソート
        value_bets.sort(key=lambda x: x["edge"], reverse=True)

        return value_bets

    # =================================================
    # Regime-based Strategy
    # =================================================

    def adjust_for_regime(
        self,
        edge: float,
        regime: str,
    ) -> float:
        """
        レジームに基づいてエッジを調整

        Args:
            edge: 計算済みエッジ
            regime: レジーム（NORMAL, FAVORITE_DOMINANCE, CHAOS）

        Returns:
            調整後のエッジ
        """
        multipliers = {
            "NORMAL": 1.0,
            "FAVORITE_DOMINANCE": 0.8,
            "CHAOS": 0.5,
            "EFFICIENT": 0.3,
        }

        multiplier = multipliers.get(regime, 1.0)
        return edge * multiplier

    # =================================================
    # Overbet Detection
    # =================================================

    def detect_overbet(
        self,
        horse_id: str,
        odds: float,
        ai_prob: float,
        market_consensus_odds: float,
    ) -> Optional[str]:
        """
        市場が過剰評価している馬を検出

        Args:
            horse_id: 馬ID
            odds: このブックメーカーのオッズ
            ai_prob: AI 推定確率
            market_consensus_odds: 市場コンセンサスオッズ

        Returns:
            警告メッセージ（過剰評価の場合）
        """
        odds_ratio = market_consensus_odds / max(odds, 1.0)

        if odds_ratio > self.max_odds_ratio:
            return f"Overbet detected: {horse_id} (ratio={odds_ratio:.2f})"

        # AI が低確率と判定しているのに市場が高評価の場合
        if ai_prob < 0.10 and odds < 10.0:
            return f"Market overestimation: {horse_id} (AI={ai_prob:.2%}, odds={odds})"

        return None

    # =================================================
    # Decision Making
    # =================================================

    def make_decision(
        self,
        race_id: str,
        horses: Dict[str, dict],
        bankroll: float,
        regime: str = "NORMAL",
    ) -> Optional[MarketBetDecision]:
        """
        マーケット戦略に基づいて決定

        Args:
            race_id: レースID
            horses: 馬情報辞書
            bankroll: バンクロール
            regime: マーケットレジーム

        Returns:
            MarketBetDecision またはNone
        """
        # バリュー馬を検出
        value_bets = self.find_value_bets(horses)

        if not value_bets:
            return None

        # トップの馬を選択
        best_bet = value_bets[0]

        # レジームで調整
        adjusted_edge = self.adjust_for_regime(
            best_bet["edge"], regime
        )

        if adjusted_edge < self.min_edge_threshold:
            return None

        # ベットサイズ（簡易Kelly）
        odds = best_bet["odds"]
        kelly_fraction = 0.25
        bet_fraction = (best_bet["ai_prob"] * odds - 1) / odds * kelly_fraction
        bet_size = bankroll * max(0.0, bet_fraction)

        if bet_size <= 0:
            return None

        return MarketBetDecision(
            race_id=race_id,
            horse_id=best_bet["horse_id"],
            bet_type="win",
            bet_size=bet_size,
            edge=adjusted_edge,
            timestamp=now_jst().isoformat(),
        )

    # =================================================
    # Analysis
    # =================================================

    def market_efficiency_analysis(
        self,
        horses: Dict[str, dict],
    ) -> Dict[str, float]:
        """
        市場効率性の分析

        Args:
            horses: 馬情報辞書

        Returns:
            分析結果
        """
        gaps = []
        for horse_id, info in horses.items():
            ai_prob = info.get("ai_prob", 0.0)
            odds = info.get("odds", 1.0)

            if odds > 1.0 and ai_prob > 0.0:
                market_prob = self.extract_market_probability(odds)
                gap = abs(ai_prob - market_prob)
                gaps.append(gap)

        if not gaps:
            return {"avg_gap": 0.0, "max_gap": 0.0}

        return {
            "avg_gap": np.mean(gaps),
            "max_gap": np.max(gaps),
            "std_gap": np.std(gaps),
            "efficiency_score": 1.0 - np.mean(gaps),
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


class MarketStrategy:
    name = "market_ai"

    def __init__(self, predictor=None, bet_sizer=None, **kwargs):
        self.predictor = predictor
        self.bet_sizer = bet_sizer
        self.impl = MarketAI(**{k: v for k, v in kwargs.items()})

    def run(self, races: List[dict], weight: float = 1.0):
        decisions = []
        bankroll = weight
        for race in races:
            race_id = race.get("race_id") or race.get("id")
            horses_info = race.get("horses") or {}

            # ensure dict format horse_id -> info
            horses_dict = horses_info if isinstance(horses_info, dict) else {h.get("id") or h.get("horse_id"): h for h in horses_info}

            decision = self.impl.make_decision(race_id, horses_dict, bankroll, regime=race.get("regime", "NORMAL"))
            if decision is not None:
                decisions.append(decision)

        return decisions

    def metrics(self):
        return {"sharpe": 0.0, "profit": 0.0, "drawdown": 0.0, "volatility": 0.0}
