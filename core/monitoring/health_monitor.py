# core/monitoring/health_monitor.py

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class HealthStatus(Enum):
    """健全性ステータス"""
    HEALTHY = "HEALTHY"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass
class HealthCheck:
    """ヘルスチェック結果"""
    metric: str
    status: HealthStatus
    current_value: float
    threshold: float
    message: str


class HealthMonitor:
    """
    システムの健全性監視

    監視項目:
    - Bankroll（資本金）
    - Brier Score（キャリブレーション）
    - Drawdown（最大下落）
    - Win Rate（勝率）
    - Model Performance（モデル精度）
    """

    def __init__(self):
        """初期化"""
        # Bankroll 閾値
        self.bankroll_warning = 0.15  # 初期金の 85%
        self.bankroll_critical = 0.25  # 初期金の 75%

        # Brier Score 閾値（低いほど良い）
        self.brier_warning = 0.25
        self.brier_critical = 0.35

        # Drawdown 閾値
        self.dd_warning = 0.15
        self.dd_critical = 0.25

        # Win Rate 閾値
        self.wr_warning = 0.40
        self.wr_critical = 0.30

        # Check history
        self.history: List[Dict[str, HealthCheck]] = []

    # =================================================
    # Bankroll Check
    # =================================================

    def check_bankroll(
        self,
        current_bankroll: float,
        initial_bankroll: float,
    ) -> HealthCheck:
        """
        バンクロールをチェック

        Args:
            current_bankroll: 現在のバンクロール
            initial_bankroll: 初期バンクロール

        Returns:
            HealthCheck
        """
        if initial_bankroll <= 0:
            return HealthCheck(
                metric="bankroll",
                status=HealthStatus.CRITICAL,
                current_value=0.0,
                threshold=self.bankroll_critical,
                message="Initial bankroll is 0 or negative",
            )

        drawdown = (initial_bankroll - current_bankroll) / initial_bankroll

        if drawdown >= self.bankroll_critical:
            status = HealthStatus.CRITICAL
            message = f"Critical drawdown: {drawdown:.1%}"
        elif drawdown >= self.bankroll_warning:
            status = HealthStatus.WARNING
            message = f"Warning drawdown: {drawdown:.1%}"
        else:
            status = HealthStatus.HEALTHY
            message = f"Bankroll OK: {drawdown:.1%}"

        return HealthCheck(
            metric="bankroll",
            status=status,
            current_value=current_bankroll,
            threshold=initial_bankroll * (1 - self.bankroll_critical),
            message=message,
        )

    # =================================================
    # Brier Score Check
    # =================================================

    def check_brier_score(
        self,
        brier_score: float,
    ) -> HealthCheck:
        """
        Brier Score をチェック

        低いほど良い（キャリブレーション良）

        Args:
            brier_score: Brier Score

        Returns:
            HealthCheck
        """
        if brier_score >= self.brier_critical:
            status = HealthStatus.CRITICAL
            message = f"Model poorly calibrated: {brier_score:.4f}"
        elif brier_score >= self.brier_warning:
            status = HealthStatus.WARNING
            message = f"Model calibration degrading: {brier_score:.4f}"
        else:
            status = HealthStatus.HEALTHY
            message = f"Model calibration good: {brier_score:.4f}"

        return HealthCheck(
            metric="brier_score",
            status=status,
            current_value=brier_score,
            threshold=self.brier_critical,
            message=message,
        )

    # =================================================
    # Drawdown Check
    # =================================================

    def check_drawdown(
        self,
        peak_bankroll: float,
        current_bankroll: float,
    ) -> HealthCheck:
        """
        Drawdown をチェック

        Args:
            peak_bankroll: ピーク時のバンクロール
            current_bankroll: 現在のバンクロール

        Returns:
            HealthCheck
        """
        if peak_bankroll <= 0:
            return HealthCheck(
                metric="drawdown",
                status=HealthStatus.CRITICAL,
                current_value=0.0,
                threshold=self.dd_critical,
                message="No peak established",
            )

        dd = (peak_bankroll - current_bankroll) / peak_bankroll

        if dd >= self.dd_critical:
            status = HealthStatus.CRITICAL
            message = f"Critical drawdown: {dd:.1%}"
        elif dd >= self.dd_warning:
            status = HealthStatus.WARNING
            message = f"Warning drawdown: {dd:.1%}"
        else:
            status = HealthStatus.HEALTHY
            message = f"Drawdown acceptable: {dd:.1%}"

        return HealthCheck(
            metric="drawdown",
            status=status,
            current_value=dd,
            threshold=self.dd_critical,
            message=message,
        )

    # =================================================
    # Win Rate Check
    # =================================================

    def check_win_rate(
        self,
        wins: int,
        total_bets: int,
    ) -> HealthCheck:
        """
        勝率をチェック

        Args:
            wins: 勝利数
            total_bets: 総ベット数

        Returns:
            HealthCheck
        """
        if total_bets == 0:
            wr = 0.0
        else:
            wr = wins / total_bets

        if wr <= self.wr_critical:
            status = HealthStatus.CRITICAL
            message = f"Win rate critically low: {wr:.1%}"
        elif wr <= self.wr_warning:
            status = HealthStatus.WARNING
            message = f"Win rate low: {wr:.1%}"
        else:
            status = HealthStatus.HEALTHY
            message = f"Win rate acceptable: {wr:.1%}"

        return HealthCheck(
            metric="win_rate",
            status=status,
            current_value=wr,
            threshold=self.wr_critical,
            message=message,
        )

    # =================================================
    # Overall Health
    # =================================================

    def overall_health(
        self,
        checks: List[HealthCheck],
    ) -> HealthStatus:
        """
        全体的な健全性を判定

        Args:
            checks: HealthCheck リスト

        Returns:
            全体のステータス
        """
        if any(c.status == HealthStatus.CRITICAL for c in checks):
            return HealthStatus.CRITICAL
        elif any(c.status == HealthStatus.WARNING for c in checks):
            return HealthStatus.WARNING
        else:
            return HealthStatus.HEALTHY

    def generate_health_report(
        self,
        bankroll_info: Dict,
        brier_score: float,
        win_rate_info: Dict,
    ) -> Tuple[HealthStatus, List[HealthCheck]]:
        """
        健全性レポートを生成

        Args:
            bankroll_info: {current, initial, peak}
            brier_score: Brier Score
            win_rate_info: {wins, total_bets}

        Returns:
            (全体ステータス, チェック結果リスト)
        """
        checks = []

        # Bankroll チェック
        checks.append(
            self.check_bankroll(
                bankroll_info["current"],
                bankroll_info["initial"],
            )
        )

        # Drawdown チェック
        checks.append(
            self.check_drawdown(
                bankroll_info["peak"],
                bankroll_info["current"],
            )
        )

        # Brier Score チェック
        checks.append(self.check_brier_score(brier_score))

        # Win Rate チェック
        checks.append(
            self.check_win_rate(
                win_rate_info["wins"],
                win_rate_info["total_bets"],
            )
        )

        # 全体ステータス
        overall = self.overall_health(checks)

        # 履歴に追加
        self.history.append({check.metric: check for check in checks})

        # ログ出力
        if overall == HealthStatus.CRITICAL:
            logger.critical(f"CRITICAL health issues detected")
        elif overall == HealthStatus.WARNING:
            logger.warning(f"Warning health issues detected")

        return overall, checks

    # =================================================
    # Threshold Adjustment
    # =================================================

    def adjust_thresholds(
        self,
        performance_percentile: float,
    ):
        """
        パフォーマンスに基づいて閾値を調整

        成績が良い場合は基準を上げる

        Args:
            performance_percentile: パフォーマンスパーセンタイル（0-100）
        """
        adjustment_factor = performance_percentile / 100.0

        # 基準を厳しくする
        self.brier_warning *= adjustment_factor
        self.wr_warning = 0.40 + (0.60 - 0.40) * adjustment_factor
