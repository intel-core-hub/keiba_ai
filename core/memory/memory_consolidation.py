# core/memory/memory_consolidation.py

from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


@dataclass
class ConsolidationReport:
    """統合レポート"""
    period: str
    original_entries: int
    consolidated_entries: int
    compression_ratio: float
    summary: str


class MemoryConsolidation:
    """
    メモリ統合エンジン

    目的:
    - 古いメモリを圧縮
    - 重要なパターンを保持
    - 冗長なデータを削除

    戦略:
    1. 古いレコードをサマリーに変換
    2. 類似パターンを統合
    3. 低信頼度のパターンを削除
    """

    def __init__(self):
        """初期化"""
        self.consolidation_history: List[ConsolidationReport] = []

    # =================================================
    # Pattern Summarization
    # =================================================

    def summarize_bets(
        self,
        bets: List[Dict[str, Any]],
        period: str = "weekly",
    ) -> Dict[str, Any]:
        """
        ベットをサマリーに変換

        Args:
            bets: ベットリスト
            period: 期間（"daily", "weekly", "monthly"）

        Returns:
            サマリー
        """
        if not bets:
            return {}

        # グループ化（ベットタイプ別）
        by_type = {}
        for bet in bets:
            bet_type = bet.get("bet_type", "unknown")
            if bet_type not in by_type:
                by_type[bet_type] = []
            by_type[bet_type].append(bet)

        # 各タイプの統計
        summary = {
            "period": period,
            "total_bets": len(bets),
            "by_type": {},
        }

        for bet_type, type_bets in by_type.items():
            wins = sum(
                1 for b in type_bets if b.get("result") == "win"
            )
            total_amount = sum(b.get("bet_size", 0) for b in type_bets)
            total_payout = sum(b.get("payout", 0) for b in type_bets)

            summary["by_type"][bet_type] = {
                "count": len(type_bets),
                "wins": wins,
                "win_rate": wins / len(type_bets) * 100 if type_bets else 0,
                "total_amount": total_amount,
                "total_payout": total_payout,
                "roi": (
                    (total_payout - total_amount) / total_amount * 100
                    if total_amount > 0 else 0
                ),
            }

        return summary

    def summarize_patterns(
        self,
        patterns: Dict[str, Any],
        min_frequency: int = 5,
    ) -> Dict[str, Any]:
        """
        パターンをサマリーに変換

        低頻度のパターンを削除して集約

        Args:
            patterns: パターン辞書
            min_frequency: 最小頻度

        Returns:
            集約パターン
        """
        consolidated = {}

        for key, pattern in patterns.items():
            frequency = pattern.get("frequency", 1)

            # 低頻度は削除
            if frequency < min_frequency:
                logger.debug(f"Dropping pattern: {key} (freq={frequency})")
                continue

            # 高い信頼度のパターンのみ保持
            confidence = pattern.get("confidence", 0.5)
            if confidence > 0.7:
                consolidated[key] = pattern

        return consolidated

    # =================================================
    # Redundancy Detection
    # =================================================

    def find_duplicate_patterns(
        self,
        patterns: List[Dict[str, Any]],
        similarity_threshold: float = 0.85,
    ) -> List[List[int]]:
        """
        重複パターンを検出

        Args:
            patterns: パターンリスト
            similarity_threshold: 類似度の閾値

        Returns:
            重複インデックスのグループ
        """
        duplicates = []

        for i in range(len(patterns)):
            for j in range(i + 1, len(patterns)):
                similarity = self._calculate_similarity(
                    patterns[i], patterns[j]
                )

                if similarity > similarity_threshold:
                    # 既にグループに属しているか確認
                    found_group = None
                    for group in duplicates:
                        if i in group:
                            found_group = group
                            break

                    if found_group is not None:
                        found_group.append(j)
                    else:
                        duplicates.append([i, j])

        return duplicates

    @staticmethod
    def _calculate_similarity(
        pattern1: Dict[str, Any],
        pattern2: Dict[str, Any],
    ) -> float:
        """
        2つのパターンの類似度を計算

        Args:
            pattern1: パターン1
            pattern2: パターン2

        Returns:
            類似度（0-1）
        """
        # 簡易的な実装：shared keys / total keys
        keys1 = set(pattern1.keys())
        keys2 = set(pattern2.keys())

        if not keys1 or not keys2:
            return 0.0

        common = len(keys1 & keys2)
        total = len(keys1 | keys2)

        return common / total if total > 0 else 0.0

    # =================================================
    # Consolidation
    # =================================================

    def consolidate_old_records(
        self,
        records: List[Dict[str, Any]],
        days_threshold: int = 30,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        古いレコードを統合

        Args:
            records: レコードリスト
            days_threshold: これ以上前のレコードを統合

        Returns:
            (新しいレコード, サマリー)
        """
        from core.utilities import now_jst

        current_time = now_jst()
        cutoff_time = current_time - timedelta(days=days_threshold)

        old_records = []
        new_records = []

        for record in records:
            timestamp_str = record.get("timestamp", "")
            try:
                timestamp = datetime.fromisoformat(timestamp_str)
                if timestamp < cutoff_time:
                    old_records.append(record)
                else:
                    new_records.append(record)
            except (ValueError, TypeError):
                new_records.append(record)

        # 古いレコードをサマリーに
        summary = self.summarize_bets(old_records, period="consolidated")

        return new_records, summary

    def merge_similar_patterns(
        self,
        pattern_groups: List[List[Dict[str, Any]]],
    ) -> List[Dict[str, Any]]:
        """
        類似パターンを統合

        Args:
            pattern_groups: パターングループリスト

        Returns:
            統合パターンリスト
        """
        merged = []

        for group in pattern_groups:
            if not group:
                continue

            # グループの統計を取得
            avg_confidence = sum(
                p.get("confidence", 0.5) for p in group
            ) / len(group)

            total_frequency = sum(
                p.get("frequency", 1) for p in group
            )

            # マージ済みパターンを作成
            merged_pattern = {
                "condition": group[0].get("condition", "unknown"),
                "outcome": group[0].get("outcome", "unknown"),
                "confidence": avg_confidence,
                "frequency": total_frequency,
                "merged_from": len(group),
            }

            merged.append(merged_pattern)

        return merged

    # =================================================
    # Cleanup
    # =================================================

    def cleanup_low_confidence_patterns(
        self,
        patterns: Dict[str, Any],
        confidence_threshold: float = 0.5,
    ) -> Tuple[Dict[str, Any], int]:
        """
        低信頼度パターンをクリーンアップ

        Args:
            patterns: パターン辞書
            confidence_threshold: 信頼度の閾値

        Returns:
            (クリーンアップ済みパターン, 削除数)
        """
        cleaned = {}
        removed_count = 0

        for key, pattern in patterns.items():
            confidence = pattern.get("confidence", 0.5)

            if confidence >= confidence_threshold:
                cleaned[key] = pattern
            else:
                removed_count += 1
                logger.debug(
                    f"Removed pattern: {key} (confidence={confidence})"
                )

        return cleaned, removed_count

    def remove_stale_entries(
        self,
        entries: List[Dict[str, Any]],
        days_old: int = 365,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        古いエントリを削除

        Args:
            entries: エントリリスト
            days_old: これ以上前のエントリを削除

        Returns:
            (フィルタ済みエントリ, 削除数)
        """
        from core.utilities import now_jst

        current_time = now_jst()
        cutoff_time = current_time - timedelta(days=days_old)

        kept = []
        removed_count = 0

        for entry in entries:
            timestamp_str = entry.get("timestamp", "")
            try:
                timestamp = datetime.fromisoformat(timestamp_str)
                if timestamp >= cutoff_time:
                    kept.append(entry)
                else:
                    removed_count += 1
            except (ValueError, TypeError):
                kept.append(entry)

        return kept, removed_count

    # =================================================
    # Reporting
    # =================================================

    def generate_consolidation_report(
        self,
        original_count: int,
        consolidated_count: int,
        period: str = "weekly",
    ) -> ConsolidationReport:
        """
        統合レポートを生成

        Args:
            original_count: 元のエントリ数
            consolidated_count: 統合後のエントリ数
            period: 期間

        Returns:
            ConsolidationReport
        """
        compression_ratio = (
            1.0 - (consolidated_count / original_count)
            if original_count > 0 else 0.0
        )

        report = ConsolidationReport(
            period=period,
            original_entries=original_count,
            consolidated_entries=consolidated_count,
            compression_ratio=compression_ratio,
            summary=f"Reduced from {original_count} to {consolidated_count} "
                    f"({compression_ratio*100:.1f}% compression)",
        )

        self.consolidation_history.append(report)
        return report

    def get_consolidation_history(
        self,
        limit: Optional[int] = None,
    ) -> List[ConsolidationReport]:
        """
        統合履歴を取得

        Args:
            limit: 取得件数

        Returns:
            ConsolidationReport リスト
        """
        if limit:
            return self.consolidation_history[-limit:]
        return self.consolidation_history

    # =================================================
    # Statistics
    # =================================================

    def analyze_memory_efficiency(
        self,
        patterns: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        メモリ効率を分析

        Args:
            patterns: パターン辞書

        Returns:
            分析結果
        """
        if not patterns:
            return {}

        confidences = [
            p.get("confidence", 0.5) for p in patterns.values()
        ]

        frequencies = [
            p.get("frequency", 1) for p in patterns.values()
        ]

        return {
            "total_patterns": len(patterns),
            "avg_confidence": sum(confidences) / len(confidences),
            "max_confidence": max(confidences),
            "min_confidence": min(confidences),
            "avg_frequency": sum(frequencies) / len(frequencies),
            "total_instances": sum(frequencies),
        }
