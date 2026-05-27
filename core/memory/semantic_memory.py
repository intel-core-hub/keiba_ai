# core/memory/semantic_memory.py

from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
import json
import hashlib


@dataclass
class PatternEntry:
    """パターン記録"""
    condition_hash: str
    condition_description: str
    outcome: str  # "win", "loss", "uncertain"
    confidence: float
    examples: List[str]  # ベットIDの例
    timestamp: str
    frequency: int = 1


class SemanticMemory:
    """
    意味記憶（セマンティック記憶）

    目的:
    - レース条件 → パフォーマンス結果のマッピング
    - パターンの学習と活用

    例:
    - 「コース=芝2000m + 天候=雨」→ 「WideAI は 60% 勝率」
    - 「市場オッズ=favorite_dominance」→ 「ExplorerAI は休止」
    """

    def __init__(self):
        """初期化"""
        self.patterns: Dict[str, PatternEntry] = {}
        self.condition_vocab: Dict[str, str] = {}

    # =================================================
    # Pattern Encoding
    # =================================================

    def encode_conditions(
        self,
        conditions: Dict[str, Any],
    ) -> str:
        """
        条件をハッシュにエンコード

        Args:
            conditions: 条件辞書

        Returns:
            ハッシュ値
        """
        # 辞書をソート済みJSONに変換
        sorted_json = json.dumps(
            conditions,
            sort_keys=True,
            default=str,
        )

        # SHA-256 でハッシュ
        hash_obj = hashlib.sha256(sorted_json.encode())
        return hash_obj.hexdigest()[:16]

    def describe_conditions(
        self,
        conditions: Dict[str, Any],
    ) -> str:
        """
        条件を人間が読める形式で記述

        Args:
            conditions: 条件辞書

        Returns:
            説明文字列
        """
        parts = []
        for key, value in conditions.items():
            parts.append(f"{key}={value}")

        return " + ".join(parts)

    # =================================================
    # Pattern Learning
    # =================================================

    def learn_pattern(
        self,
        conditions: Dict[str, Any],
        outcome: str,
        bet_id: str,
        confidence: float = 1.0,
    ):
        """
        パターンを学習

        Args:
            conditions: レース条件
            outcome: 結果
            bet_id: ベットID
            confidence: 信頼度
        """
        condition_hash = self.encode_conditions(conditions)
        condition_desc = self.describe_conditions(conditions)

        if condition_hash in self.patterns:
            # 既存パターンを更新
            entry = self.patterns[condition_hash]
            entry.frequency += 1
            entry.examples.append(bet_id)

            # 信頼度を加重平均で更新
            old_conf = entry.confidence
            new_conf = (
                (old_conf * (entry.frequency - 1) + confidence) /
                entry.frequency
            )
            entry.confidence = new_conf

        else:
            # 新規パターン
            entry = PatternEntry(
                condition_hash=condition_hash,
                condition_description=condition_desc,
                outcome=outcome,
                confidence=confidence,
                examples=[bet_id],
                timestamp=self._get_timestamp(),
            )
            self.patterns[condition_hash] = entry

    def forget_pattern(
        self,
        conditions: Dict[str, Any],
    ):
        """
        パターンを削除

        Args:
            conditions: レース条件
        """
        condition_hash = self.encode_conditions(conditions)
        if condition_hash in self.patterns:
            del self.patterns[condition_hash]

    # =================================================
    # Pattern Retrieval
    # =================================================

    def recall_pattern(
        self,
        conditions: Dict[str, Any],
    ) -> Optional[PatternEntry]:
        """
        パターンを回想

        Args:
            conditions: レース条件

        Returns:
            PatternEntry またはNone
        """
        condition_hash = self.encode_conditions(conditions)
        return self.patterns.get(condition_hash)

    def find_similar_patterns(
        self,
        conditions: Dict[str, Any],
        similarity_threshold: float = 0.7,
    ) -> List[PatternEntry]:
        """
        類似パターンを検索

        Args:
            conditions: レース条件
            similarity_threshold: 類似度の閾値

        Returns:
            類似パターンのリスト
        """
        similar = []

        for pattern in self.patterns.values():
            # 簡易的な類似度：キーの重複数 / 総キー数
            pattern_cond = json.loads(
                json.dumps(pattern.condition_description.split(" + "))
            )
            cond_keys = set(conditions.keys())

            # 実装簡略版：完全一致のパターンのみ
            if pattern.confidence > similarity_threshold:
                similar.append(pattern)

        return similar

    # =================================================
    # Pattern Analysis
    # =================================================

    def get_pattern_statistics(
        self,
        outcome: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        パターン統計を取得

        Args:
            outcome: 特定の結果でフィルタ（Noneの場合は全体）

        Returns:
            統計情報
        """
        if outcome:
            patterns = [
                p for p in self.patterns.values()
                if p.outcome == outcome
            ]
        else:
            patterns = list(self.patterns.values())

        if not patterns:
            return {
                "total_patterns": 0,
                "avg_confidence": 0.0,
                "total_examples": 0,
            }

        total_examples = sum(p.frequency for p in patterns)
        avg_confidence = (
            sum(p.confidence for p in patterns) / len(patterns)
        )

        return {
            "outcome": outcome,
            "total_patterns": len(patterns),
            "avg_confidence": avg_confidence,
            "total_examples": total_examples,
            "avg_frequency": total_examples / len(patterns),
        }

    def rank_patterns_by_confidence(
        self,
        top_n: Optional[int] = None,
    ) -> List[PatternEntry]:
        """
        パターンを信頼度でランク付け

        Args:
            top_n: トップN個を返す（Noneの場合は全体）

        Returns:
            ランク付けされたパターン
        """
        ranked = sorted(
            self.patterns.values(),
            key=lambda p: (p.confidence, p.frequency),
            reverse=True,
        )

        if top_n:
            return ranked[:top_n]
        return ranked

    # =================================================
    # Condition-specific Analysis
    # =================================================

    def analyze_condition_impact(
        self,
        condition_key: str,
    ) -> Dict[str, Any]:
        """
        特定の条件の影響を分析

        Args:
            condition_key: 条件キー（例: "course_type"）

        Returns:
            分析結果
        """
        impact = {}

        for pattern in self.patterns.values():
            if condition_key in pattern.condition_description:
                # 簡易的な抽出
                parts = pattern.condition_description.split(" + ")
                for part in parts:
                    if condition_key in part:
                        value = part.split("=")[1] if "=" in part else "unknown"

                        if value not in impact:
                            impact[value] = {
                                "count": 0,
                                "wins": 0,
                                "avg_confidence": 0.0,
                            }

                        impact[value]["count"] += pattern.frequency
                        if pattern.outcome == "win":
                            impact[value]["wins"] += pattern.frequency

        # 勝率を計算
        for value in impact:
            stats = impact[value]
            stats["win_rate"] = (
                stats["wins"] / stats["count"] * 100
                if stats["count"] > 0
                else 0.0
            )

        return impact

    # =================================================
    # Export / Import
    # =================================================

    def export_patterns(self) -> str:
        """
        パターンをJSON形式でエクスポート

        Returns:
            JSON文字列
        """
        data = {
            "patterns": [
                {
                    "condition_hash": p.condition_hash,
                    "condition_description": p.condition_description,
                    "outcome": p.outcome,
                    "confidence": p.confidence,
                    "frequency": p.frequency,
                    "examples": p.examples[:10],  # 最初の10個のみ
                    "timestamp": p.timestamp,
                }
                for p in self.patterns.values()
            ]
        }
        return json.dumps(data, ensure_ascii=False, indent=2)

    def import_patterns(self, json_str: str):
        """
        JSON からパターンをインポート

        Args:
            json_str: JSON文字列
        """
        data = json.loads(json_str)

        for p_data in data.get("patterns", []):
            entry = PatternEntry(
                condition_hash=p_data["condition_hash"],
                condition_description=p_data["condition_description"],
                outcome=p_data["outcome"],
                confidence=p_data["confidence"],
                examples=p_data["examples"],
                timestamp=p_data["timestamp"],
                frequency=p_data["frequency"],
            )
            self.patterns[entry.condition_hash] = entry

    # =================================================
    # Utilities
    # =================================================

    @staticmethod
    def _get_timestamp() -> str:
        """タイムスタンプを取得"""
        from core.utilities import now_jst
        return now_jst().isoformat()

    def clear_all(self):
        """すべてのパターンをクリア"""
        self.patterns.clear()

    def get_total_patterns(self) -> int:
        """総パターン数を取得"""
        return len(self.patterns)
