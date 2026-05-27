# core/monitoring/diagnostics_engine.py

from typing import Dict, List, Optional, Any
from dataclasses import dataclass
import logging
from pathlib import Path
import json

logger = logging.getLogger(__name__)


@dataclass
class DiagnosticFinding:
    """診断結果"""
    category: str  # "model", "risk", "execution", "strategy"
    severity: str  # "INFO", "WARNING", "CRITICAL"
    message: str
    recommendation: str


class DiagnosticsEngine:
    """
    自動診断エンジン

    ログからシステムの問題を検出し、
    自動的に改善提案を生成
    """

    def __init__(self):
        """初期化"""
        self.findings: List[DiagnosticFinding] = []

    # =================================================
    # Model Diagnostics
    # =================================================

    def diagnose_model_performance(
        self,
        recent_predictions: List[Dict[str, Any]],
        threshold_accuracy: float = 0.55,
    ) -> List[DiagnosticFinding]:
        """
        モデルパフォーマンスを診断

        Args:
            recent_predictions: 最近の予測リスト
            threshold_accuracy: 精度の閾値

        Returns:
            診断結果リスト
        """
        findings = []

        if not recent_predictions:
            return findings

        # 精度を計算
        correct = sum(
            1 for p in recent_predictions if p.get("correct", False)
        )
        accuracy = correct / len(recent_predictions)

        if accuracy < threshold_accuracy:
            findings.append(
                DiagnosticFinding(
                    category="model",
                    severity="WARNING",
                    message=f"Model accuracy low: {accuracy:.1%}",
                    recommendation="Retrain model with recent data",
                )
            )

        # Brier Score を確認
        brier_scores = [p.get("brier", 0.5) for p in recent_predictions]
        avg_brier = sum(brier_scores) / len(brier_scores)

        if avg_brier > 0.30:
            findings.append(
                DiagnosticFinding(
                    category="model",
                    severity="WARNING",
                    message=f"Poor calibration: Brier={avg_brier:.4f}",
                    recommendation="Apply calibration correction",
                )
            )

        # モデルの不安定性を検出
        variance = self._calculate_variance(brier_scores)
        if variance > 0.1:
            findings.append(
                DiagnosticFinding(
                    category="model",
                    severity="WARNING",
                    message=f"Model instability detected: variance={variance:.4f}",
                    recommendation="Check for data quality issues or concept drift",
                )
            )

        return findings

    # =================================================
    # Risk Diagnostics
    # =================================================

    def diagnose_risk_management(
        self,
        recent_bets: List[Dict[str, Any]],
        bankroll: float,
    ) -> List[DiagnosticFinding]:
        """
        リスク管理を診断

        Args:
            recent_bets: 最近のベットリスト
            bankroll: 現在のバンクロール

        Returns:
            診断結果リスト
        """
        findings = []

        if not recent_bets:
            return findings

        # 最大ベットサイズを確認
        bet_sizes = [b.get("size", 0) for b in recent_bets]
        max_bet = max(bet_sizes)
        max_bet_ratio = max_bet / bankroll if bankroll > 0 else 0

        if max_bet_ratio > 0.15:
            findings.append(
                DiagnosticFinding(
                    category="risk",
                    severity="WARNING",
                    message=f"Bet size excessive: {max_bet_ratio:.1%} of bankroll",
                    recommendation="Reduce individual bet sizes",
                )
            )

        # 連続損失を検出
        consecutive_losses = self._count_consecutive_losses(recent_bets)
        if consecutive_losses > 5:
            findings.append(
                DiagnosticFinding(
                    category="risk",
                    severity="CRITICAL",
                    message=f"Losing streak: {consecutive_losses} consecutive losses",
                    recommendation="Take a break and review strategy",
                )
            )

        return findings

    # =================================================
    # Execution Diagnostics
    # =================================================

    def diagnose_execution(
        self,
        recent_bets: List[Dict[str, Any]],
    ) -> List[DiagnosticFinding]:
        """
        実行品質を診断

        Args:
            recent_bets: 最近のベットリスト

        Returns:
            診断結果リスト
        """
        findings = []

        if not recent_bets:
            return findings

        # スリップを確認
        slippages = [
            b.get("odds_slip", 0) for b in recent_bets if "odds_slip" in b
        ]

        if slippages:
            avg_slip = sum(slippages) / len(slippages)
            if avg_slip > 0.05:
                findings.append(
                    DiagnosticFinding(
                        category="execution",
                        severity="WARNING",
                        message=f"High average odds slip: {avg_slip:.1%}",
                        recommendation="Use limit orders or adjust timing",
                    )
                )

        # 執行失敗を確認
        failed_executions = sum(
            1 for b in recent_bets if b.get("executed", True) is False
        )
        failure_rate = (
            failed_executions / len(recent_bets)
            if recent_bets
            else 0
        )

        if failure_rate > 0.05:
            findings.append(
                DiagnosticFinding(
                    category="execution",
                    severity="WARNING",
                    message=f"Execution failures: {failure_rate:.1%}",
                    recommendation="Check connectivity and order flow",
                )
            )

        return findings

    # =================================================
    # Strategy Diagnostics
    # =================================================

    def diagnose_strategy(
        self,
        strategy_performance: Dict[str, Any],
    ) -> List[DiagnosticFinding]:
        """
        戦略パフォーマンスを診断

        Args:
            strategy_performance: 戦略パフォーマンス情報

        Returns:
            診断結果リスト
        """
        findings = []

        # ROI を確認
        roi = strategy_performance.get("roi", 0)
        if roi < 0:
            findings.append(
                DiagnosticFinding(
                    category="strategy",
                    severity="CRITICAL",
                    message=f"Negative ROI: {roi:.1%}",
                    recommendation="Stop trading immediately and review strategy",
                )
            )

        # Sharpe Ratio を確認
        sharpe = strategy_performance.get("sharpe_ratio", 0)
        if sharpe < 1.0:
            findings.append(
                DiagnosticFinding(
                    category="strategy",
                    severity="WARNING",
                    message=f"Low Sharpe Ratio: {sharpe:.2f}",
                    recommendation="Optimize risk-adjusted returns",
                )
            )

        # Win rate を確認
        win_rate = strategy_performance.get("win_rate", 0)
        if win_rate < 0.40:
            findings.append(
                DiagnosticFinding(
                    category="strategy",
                    severity="WARNING",
                    message=f"Low win rate: {win_rate:.1%}",
                    recommendation="Increase edge detection or tighten filters",
                )
            )

        return findings

    # =================================================
    # Full Diagnosis
    # =================================================

    def run_full_diagnosis(
        self,
        predictions: List[Dict[str, Any]],
        bets: List[Dict[str, Any]],
        bankroll: float,
        strategy_perf: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        完全な診断を実行

        Args:
            predictions: 予測ログ
            bets: ベットログ
            bankroll: 現在のバンクロール
            strategy_perf: 戦略パフォーマンス

        Returns:
            診断レポート
        """
        findings = []

        # 各領域を診断
        findings.extend(self.diagnose_model_performance(predictions))
        findings.extend(self.diagnose_risk_management(bets, bankroll))
        findings.extend(self.diagnose_execution(bets))
        findings.extend(self.diagnose_strategy(strategy_perf))

        # 重要度でソート
        severity_order = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}
        findings.sort(
            key=lambda f: severity_order.get(f.severity, 3)
        )

        # レポートを生成
        report = {
            "timestamp": str(self._get_timestamp()),
            "total_findings": len(findings),
            "critical_count": sum(
                1 for f in findings if f.severity == "CRITICAL"
            ),
            "warning_count": sum(
                1 for f in findings if f.severity == "WARNING"
            ),
            "findings": [
                {
                    "category": f.category,
                    "severity": f.severity,
                    "message": f.message,
                    "recommendation": f.recommendation,
                }
                for f in findings
            ],
        }

        self.findings = findings
        return report

    # =================================================
    # Utilities
    # =================================================

    @staticmethod
    def _calculate_variance(values: List[float]) -> float:
        """分散を計算"""
        if not values or len(values) < 2:
            return 0.0

        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / len(values)
        return variance

    @staticmethod
    def _count_consecutive_losses(bets: List[Dict[str, Any]]) -> int:
        """連続損失の数を数える"""
        consecutive = 0
        max_consecutive = 0

        for bet in bets:
            if bet.get("result") == "loss":
                consecutive += 1
                max_consecutive = max(max_consecutive, consecutive)
            else:
                consecutive = 0

        return max_consecutive

    @staticmethod
    def _get_timestamp() -> str:
        """タイムスタンプを取得"""
        from core.utilities import now_jst
        return now_jst().isoformat()

    def export_report(
        self,
        report: Dict[str, Any],
        filepath: Optional[Path] = None,
    ) -> str:
        """
        診断レポートをエクスポート

        Args:
            report: レポート辞書
            filepath: 保存先（Noneの場合は JSON 文字列を返す）

        Returns:
            JSON 文字列またはファイルパス
        """
        json_str = json.dumps(report, ensure_ascii=False, indent=2)

        if filepath:
            filepath = Path(filepath)
            filepath.parent.mkdir(parents=True, exist_ok=True)
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(json_str)
            return str(filepath)

        return json_str
