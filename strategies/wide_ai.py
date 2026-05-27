# strategies/wide_ai.py

import numpy as np
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from core.utilities import retry_http, now_jst


@dataclass
class Horse:
    """
    馬情報
    """
    id: str
    name: str
    odds: float
    win_prob: float
    form: str
    speed_index: float


@dataclass
class WideBetDecision:
    """
    ワイド馬券決定
    """
    race_id: str
    horses: List[Tuple[str, str]]  # (horse_id_1, horse_id_2)
    bet_size: float
    expected_value: float
    timestamp: str


class WideAI:
    name = "wide_ai"
    """
    ワイド馬券戦略

    目的:
    - 上位N頭を選定
    - 2頭の組み合わせでワイド購入
    - Kelly sizing で自動調整

    思想:
    「単勝の堅さ」
    ではなく
    「2頭の相対的優位性」
    を活用
    """

    def __init__(
        self,
        predictor=None,
        bet_sizer=None,
        kelly_fraction: float = 0.25,
        top_n: int = 3,
        min_expected_value: float = 0.05,
    ):
        """
        初期化

        Args:
            kelly_fraction: Kelly fraction (1/4 Kelly)
            top_n: 選定する上位頭数
            min_expected_value: 最小期待値
        """
        self.kelly_fraction = kelly_fraction
        self.top_n = top_n
        self.min_expected_value = min_expected_value
        self.predictor = predictor
        self.bet_sizer = bet_sizer
        self._last_metrics = {
            "sharpe": 0.0,
            "profit": 0.0,
            "drawdown": 0.0,
            "volatility": 0.0,
        }

    # =================================================
    # Horse Selection
    # =================================================

    def select_top_horses(
        self,
        horses: List[Horse],
    ) -> List[Horse]:
        """
        上位N頭を選定

        戦略:
        - win_prob * speed_index でランク付け
        - オッズの安心度も考慮

        Args:
            horses: 全馬情報

        Returns:
            上位N頭
        """
        # スコア計算
        scores = []
        for horse in horses:
            # 勝率とスピードインデックスの組み合わせ
            ai_score = horse.win_prob * horse.speed_index

            # オッズ安心度（低いほど良い）
            odds_factor = 1.0 / (1.0 + horse.odds / 10.0)

            # 総合スコア
            total_score = ai_score * 0.7 + odds_factor * 0.3

            scores.append((horse, total_score))

        # ソート
        scores.sort(key=lambda x: x[1], reverse=True)

        # 上位N頭を返す
        top_horses = [horse for horse, _ in scores[: self.top_n]]
        return top_horses

    # =================================================
    # Wide Combination
    # =================================================

    def generate_wide_combinations(
        self,
        horses: List[Horse],
    ) -> List[Tuple[Horse, Horse]]:
        """
        ワイド組み合わせを生成

        すべての上位N頭の2頭組み合わせ

        Args:
            horses: 上位N頭

        Returns:
            (horse1, horse2) のリスト
        """
        combinations = []
        n = len(horses)

        for i in range(n):
            for j in range(i + 1, n):
                combinations.append((horses[i], horses[j]))

        return combinations

    # =================================================
    # Expected Value Calculation
    # =================================================

    def wide_odds_estimate(
        self,
        horse1: Horse,
        horse2: Horse,
    ) -> float:
        """
        ワイド配当を推定

        簡易式:
        wide_odds ≈ 8.0 / (p1 * p2)

        Args:
            horse1: 馬1
            horse2: 馬2

        Returns:
            推定ワイド配当
        """
        # 両馬ともに入着する確率
        both_prob = horse1.win_prob * horse2.win_prob

        # 推定配当
        estimated_odds = 8.0 / max(both_prob, 0.01)

        return estimated_odds

    def wide_expected_value(
        self,
        horse1: Horse,
        horse2: Horse,
        bet_size: float = 100,
    ) -> Tuple[float, float]:
        """
        ワイド期待値を計算

        Args:
            horse1: 馬1
            horse2: 馬2
            bet_size: ベットサイズ

        Returns:
            (期待値, ワイド配当)
        """
        # 入着確率
        both_prob = horse1.win_prob * horse2.win_prob

        # 推定配当
        odds = self.wide_odds_estimate(horse1, horse2)

        # 期待値
        ev = both_prob * odds - 1.0

        return (ev, odds)

    # =================================================
    # Kelly Sizing
    # =================================================

    def kelly_bet_size(
        self,
        expected_value: float,
        odds: float,
        bankroll: float,
    ) -> float:
        """
        Kelly sizing でベットサイズを決定

        Kelly formula:
        f = (b*p - q) / b
        where:
          f: 資金の割合
          b: オッズ - 1
          p: 勝率
          q: 敗率

        Args:
            expected_value: 期待値（単位: 倍）
            odds: オッズ
            bankroll: バンクロール

        Returns:
            ベットサイズ
        """
        if expected_value <= 0:
            return 0.0

        # Kelly 計算
        # EV = odds * p - 1 なら
        # p = (EV + 1) / odds
        # q = 1 - p

        p = (expected_value + 1) / odds
        q = 1 - p

        if q <= 0:
            return 0.0

        # Kelly fraction
        kelly_frac = (odds - 1) * p - q
        kelly_frac = kelly_frac / (odds - 1)

        # 1/4 Kelly
        bet_fraction = kelly_frac * self.kelly_fraction

        # 負でないことを保証
        bet_fraction = max(0.0, bet_fraction)

        # ベットサイズ
        bet_size = bankroll * bet_fraction

        return bet_size

    # =================================================
    # Decision Making
    # =================================================

    def make_decision(
        self,
        race_id: str,
        horses: List[Horse],
        bankroll: float,
    ) -> Optional[WideBetDecision]:
        """
        ワイド馬券決定

        Args:
            race_id: レースID
            horses: 全馬情報
            bankroll: バンクロール

        Returns:
            WideBetDecision またはNone
        """
        # 上位N頭を選定
        top_horses = self.select_top_horses(horses)

        if len(top_horses) < 2:
            return None

        # 組み合わせを生成
        combinations = self.generate_wide_combinations(top_horses)

        # 各組み合わせの期待値を計算
        best_combination = None
        best_ev = -1.0
        best_odds = 0.0

        for horse1, horse2 in combinations:
            ev, odds = self.wide_expected_value(
                horse1, horse2, bet_size=100
            )

            if ev > best_ev:
                best_ev = ev
                best_combination = (horse1, horse2)
                best_odds = odds

        if best_combination is None or best_ev < self.min_expected_value:
            return None

        # Kelly sizing
        bet_size = self.kelly_bet_size(
            best_ev, best_odds, bankroll
        )

        if bet_size <= 0:
            return None

        horse1, horse2 = best_combination

        # 決定を返す
        return WideBetDecision(
            race_id=race_id,
            horses=[(horse1.id, horse2.id)],
            bet_size=bet_size,
            expected_value=best_ev,
            timestamp=now_jst().isoformat(),
        )

    # =================================================
    # Analysis
    # =================================================

    def edge_breakdown(
        self,
        horse1: Horse,
        horse2: Horse,
    ) -> Dict[str, float]:
        """
        エッジの分解分析

        Args:
            horse1: 馬1
            horse2: 馬2

        Returns:
            分析結果
        """
        p1 = horse1.win_prob
        p2 = horse2.win_prob

        both_prob = p1 * p2
        odds = self.wide_odds_estimate(horse1, horse2)

        return {
            "horse1_prob": p1,
            "horse2_prob": p2,
            "both_prob": both_prob,
            "estimated_odds": odds,
            "margin": odds * both_prob - 1.0,
        }

    def run(self, races: List[dict], weight: float):
        decisions = []
        total_size = 0.0

        for race in races:
            race_id = race.get("race_id") or race.get("id") or "UNKNOWN"
            horses_info = race.get("horses") or []
            horses = []
            for h in horses_info:
                horses.append(Horse(
                    id=str(h.get("id") or h.get("horse_id") or ""),
                    name=h.get("name", ""),
                    odds=float(h.get("odds", 1.0)),
                    win_prob=float(h.get("ai_prob", h.get("win_prob", 0.0))),
                    form=h.get("form", ""),
                    speed_index=float(h.get("speed_index", 1.0)),
                ))

            decision = self.make_decision(race_id=race_id, horses=horses, bankroll=float(weight))
            if decision is not None:
                decisions.append(decision)
                total_size += float(decision.bet_size)

        self._last_metrics = {
            "sharpe": 0.0,
            "profit": 0.0,
            "drawdown": 0.0,
            "volatility": 0.0,
        }
        if total_size > 0:
            self._last_metrics["volatility"] = float(np.std([d.bet_size for d in decisions])) if decisions else 0.0

        return decisions

    def metrics(self):
        return dict(self._last_metrics)


# ---------------------------------------------------------------------------
# Compatibility adapter for PortfolioManager / MetaEvaluator
# Provides the minimal interface: name, __init__(predictor, bet_sizer), run(races, weight), metrics()
# ---------------------------------------------------------------------------


class WideStrategy:
    name = "wide_ai"

    def __init__(self, predictor=None, bet_sizer=None, **kwargs):
        self.predictor = predictor
        self.bet_sizer = bet_sizer
        # pass any kwargs to internal WideAI implementation
        self.impl = WideAI(**{k: v for k, v in kwargs.items()})

    def run(self, races: List[dict], weight: float = 1.0):
        decisions = []
        bankroll = weight
        for race in races:
            race_id = race.get("race_id") or race.get("id")
            horses_info = race.get("horses") or []
            horses = []
            for h in horses_info:
                horses.append(Horse(
                    id=str(h.get("id") or h.get("horse_id") or ""),
                    name=h.get("name", ""),
                    odds=float(h.get("odds", 1.0)),
                    win_prob=float(h.get("ai_prob", h.get("win_prob", 0.0))),
                    form=h.get("form", ""),
                    speed_index=float(h.get("speed_index", 1.0)),
                ))

            decision = self.impl.make_decision(race_id, horses, bankroll)
            if decision is not None:
                decisions.append(decision)

        return decisions

    def metrics(self):
        return {"sharpe": 0.0, "profit": 0.0, "drawdown": 0.0, "volatility": 0.0}
