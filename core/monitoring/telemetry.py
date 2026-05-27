# core/monitoring/telemetry.py

from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class MetricPoint:
    """メトリクスのデータポイント"""
    timestamp: datetime
    value: float
    tags: Dict[str, str] = field(default_factory=dict)


@dataclass
class MetricsSnapshot:
    """メトリクスのスナップショット"""
    name: str
    current_value: float
    min_value: float
    max_value: float
    avg_value: float
    count: int
    timestamp: datetime


class Telemetry:
    """
    時系列メトリクス収集

    目的:
    - システム全体のメトリクスを記録
    - 時間経過によるトレンドを検出
    - アラート条件をチェック

    メトリクス:
    - bankroll（残金）
    - win_rate（勝率）
    - roi（リターン）
    - model_accuracy（モデル精度）
    - execution_time（執行時間）
    """

    def __init__(self, retention_days: int = 30):
        """
        初期化

        Args:
            retention_days: データ保持期間（日）
        """
        self.retention_days = retention_days
        self.metrics: Dict[str, List[MetricPoint]] = defaultdict(list)
        self.thresholds: Dict[str, Dict[str, float]] = {}

    # =================================================
    # Metric Recording
    # =================================================

    def record_metric(
        self,
        name: str,
        value: float,
        timestamp: Optional[datetime] = None,
        tags: Optional[Dict[str, str]] = None,
    ):
        """
        メトリクスを記録

        Args:
            name: メトリクス名
            value: 値
            timestamp: タイムスタンプ（Noneの場合は現在時刻）
            tags: タグ
        """
        from core.utilities import now_jst

        if timestamp is None:
            timestamp = now_jst()

        if tags is None:
            tags = {}

        point = MetricPoint(
            timestamp=timestamp,
            value=value,
            tags=tags,
        )

        self.metrics[name].append(point)

        # 古いデータを削除
        self._cleanup_old_data(name)

        # アラート条件をチェック
        self._check_thresholds(name, value)

    # =================================================
    # Trend Analysis
    # =================================================

    def get_metric_trend(
        self,
        name: str,
        window_hours: int = 24,
    ) -> Dict[str, Any]:
        """
        メトリクスのトレンドを取得

        Args:
            name: メトリクス名
            window_hours: 分析期間（時間）

        Returns:
            トレンド情報
        """
        from core.utilities import now_jst

        if name not in self.metrics:
            return {}

        current_time = now_jst()
        cutoff_time = current_time - timedelta(hours=window_hours)

        # 期間内のデータをフィルタ
        points = [
            p for p in self.metrics[name]
            if p.timestamp >= cutoff_time
        ]

        if not points:
            return {}

        values = [p.value for p in points]

        # 統計情報
        min_val = min(values)
        max_val = max(values)
        avg_val = sum(values) / len(values)

        # トレンド方向
        if len(values) >= 2:
            recent_avg = sum(values[-len(values)//2:]) / (len(values)//2)
            older_avg = sum(values[:len(values)//2]) / (len(values)//2)
            trend = "UP" if recent_avg > older_avg else "DOWN"
            trend_strength = abs(recent_avg - older_avg) / older_avg
        else:
            trend = "FLAT"
            trend_strength = 0.0

        return {
            "metric": name,
            "window_hours": window_hours,
            "count": len(points),
            "min": min_val,
            "max": max_val,
            "avg": avg_val,
            "current": values[-1] if values else None,
            "trend": trend,
            "trend_strength": trend_strength,
        }

    def get_volatility(
        self,
        name: str,
        window_hours: int = 24,
    ) -> float:
        """
        ボラティリティを計算

        Args:
            name: メトリクス名
            window_hours: 分析期間（時間）

        Returns:
            ボラティリティ
        """
        from core.utilities import now_jst

        if name not in self.metrics:
            return 0.0

        current_time = now_jst()
        cutoff_time = current_time - timedelta(hours=window_hours)

        points = [
            p for p in self.metrics[name]
            if p.timestamp >= cutoff_time
        ]

        if len(points) < 2:
            return 0.0

        values = [p.value for p in points]
        mean = sum(values) / len(values)

        # 分散を計算
        variance = sum((x - mean) ** 2 for x in values) / len(values)

        # 標準偏差
        volatility = variance ** 0.5

        return volatility

    # =================================================
    # Snapshot
    # =================================================

    def get_snapshot(
        self,
        name: str,
        window_hours: int = 24,
    ) -> Optional[MetricsSnapshot]:
        """
        メトリクスのスナップショットを取得

        Args:
            name: メトリクス名
            window_hours: 分析期間（時間）

        Returns:
            MetricsSnapshot
        """
        from core.utilities import now_jst

        if name not in self.metrics:
            return None

        current_time = now_jst()
        cutoff_time = current_time - timedelta(hours=window_hours)

        points = [
            p for p in self.metrics[name]
            if p.timestamp >= cutoff_time
        ]

        if not points:
            return None

        values = [p.value for p in points]

        return MetricsSnapshot(
            name=name,
            current_value=values[-1],
            min_value=min(values),
            max_value=max(values),
            avg_value=sum(values) / len(values),
            count=len(points),
            timestamp=current_time,
        )

    # =================================================
    # Threshold Management
    # =================================================

    def set_threshold(
        self,
        metric_name: str,
        warning_threshold: float,
        critical_threshold: float,
    ):
        """
        メトリクスの閾値を設定

        Args:
            metric_name: メトリクス名
            warning_threshold: 警告閾値
            critical_threshold: 危機的閾値
        """
        self.thresholds[metric_name] = {
            "warning": warning_threshold,
            "critical": critical_threshold,
        }

    def _check_thresholds(self, name: str, value: float):
        """閾値をチェック"""
        if name not in self.thresholds:
            return

        thresholds = self.thresholds[name]
        critical = thresholds.get("critical", float('inf'))
        warning = thresholds.get("warning", float('inf'))

        if value > critical:
            logger.critical(
                f"Critical threshold exceeded: {name}={value}"
            )
        elif value > warning:
            logger.warning(
                f"Warning threshold exceeded: {name}={value}"
            )

    # =================================================
    # Data Management
    # =================================================

    def _cleanup_old_data(self, name: str):
        """古いデータを削除"""
        from core.utilities import now_jst

        current_time = now_jst()
        cutoff_time = current_time - timedelta(days=self.retention_days)

        if name in self.metrics:
            self.metrics[name] = [
                p for p in self.metrics[name]
                if p.timestamp >= cutoff_time
            ]

    def clear_metric(self, name: str):
        """メトリクスをクリア"""
        if name in self.metrics:
            del self.metrics[name]

    def clear_all(self):
        """すべてのメトリクスをクリア"""
        self.metrics.clear()

    # =================================================
    # Export
    # =================================================

    def export_metrics(
        self,
        name: str,
        format: str = "json",
    ) -> str:
        """
        メトリクスをエクスポート

        Args:
            name: メトリクス名
            format: フォーマット（"json" or "csv"）

        Returns:
            フォーマット済みデータ
        """
        import json

        if name not in self.metrics:
            return ""

        points = self.metrics[name]

        if format == "json":
            data = [
                {
                    "timestamp": p.timestamp.isoformat(),
                    "value": p.value,
                    "tags": p.tags,
                }
                for p in points
            ]
            return json.dumps(data)

        elif format == "csv":
            lines = ["timestamp,value"]
            for p in points:
                lines.append(
                    f"{p.timestamp.isoformat()},{p.value}"
                )
            return "\n".join(lines)

        return ""

    # =================================================
    # Statistics
    # =================================================

    def get_statistics(
        self,
        name: str,
        window_hours: int = 24,
    ) -> Dict[str, float]:
        """
        統計情報を取得

        Args:
            name: メトリクス名
            window_hours: 分析期間（時間）

        Returns:
            統計情報
        """
        from core.utilities import now_jst

        if name not in self.metrics:
            return {}

        current_time = now_jst()
        cutoff_time = current_time - timedelta(hours=window_hours)

        points = [
            p for p in self.metrics[name]
            if p.timestamp >= cutoff_time
        ]

        if not points:
            return {}

        values = [p.value for p in points]

        # 中央値を計算
        sorted_values = sorted(values)
        n = len(sorted_values)
        if n % 2 == 0:
            median = (sorted_values[n//2-1] + sorted_values[n//2]) / 2
        else:
            median = sorted_values[n//2]

        # パーセンタイル
        p25_idx = max(0, n // 4)
        p75_idx = max(0, 3 * n // 4)
        p25 = sorted_values[p25_idx]
        p75 = sorted_values[p75_idx]

        return {
            "min": min(values),
            "max": max(values),
            "mean": sum(values) / len(values),
            "median": median,
            "p25": p25,
            "p75": p75,
            "std": (sum((x - sum(values)/len(values))**2 for x in values) / len(values)) ** 0.5,
            "count": len(values),
        }
