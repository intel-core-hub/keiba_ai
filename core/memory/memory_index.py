# core/memory/memory_index.py

from typing import Dict, List, Set, Optional, Tuple, Any
from dataclasses import dataclass, field
import json


@dataclass
class IndexEntry:
    """インデックスエントリ"""
    key: str
    value: Any
    metadata: Dict[str, Any] = field(default_factory=dict)
    references: Set[str] = field(default_factory=set)  # 参照するエントリのキー


class MemoryIndex:
    """
    メモリ検索インデックス

    目的:
    - 高速なメモリ検索
    - 関連パターンの抽出
    - メモリ内容の集約

    構造:
    - Full-text search: キーワード検索
    - Tag-based index: タグによる分類
    - Graph index: 関連メモリのグラフ
    """

    def __init__(self):
        """初期化"""
        # メインインデックス
        self.entries: Dict[str, IndexEntry] = {}

        # タグインデックス（タグ → キーのセット）
        self.tag_index: Dict[str, Set[str]] = {}

        # 全文検索用（キーワード → キーのセット）
        self.text_index: Dict[str, Set[str]] = {}

    # =================================================
    # Indexing
    # =================================================

    def index_entry(
        self,
        key: str,
        value: Any,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """
        エントリをインデックスに追加

        Args:
            key: エントリキー
            value: 値
            tags: タグリスト
            metadata: メタデータ
        """
        if metadata is None:
            metadata = {}

        entry = IndexEntry(
            key=key,
            value=value,
            metadata=metadata,
        )

        self.entries[key] = entry

        # タグインデックスに追加
        if tags:
            for tag in tags:
                if tag not in self.tag_index:
                    self.tag_index[tag] = set()
                self.tag_index[tag].add(key)

        # 全文検索インデックスに追加
        self._index_text(key, str(value))

    def _index_text(self, key: str, text: str):
        """全文検索インデックスに追加"""
        # 簡易的なトークン化
        words = text.lower().split()

        for word in words:
            # 短いトークンはスキップ
            if len(word) < 3:
                continue

            if word not in self.text_index:
                self.text_index[word] = set()

            self.text_index[word].add(key)

    # =================================================
    # Search
    # =================================================

    def search_by_key(self, key: str) -> Optional[IndexEntry]:
        """
        キーで検索

        Args:
            key: エントリキー

        Returns:
            IndexEntry またはNone
        """
        return self.entries.get(key)

    def search_by_tag(self, tag: str) -> List[IndexEntry]:
        """
        タグで検索

        Args:
            tag: タグ

        Returns:
            マッチしたエントリリスト
        """
        if tag not in self.tag_index:
            return []

        keys = self.tag_index[tag]
        return [self.entries[k] for k in keys if k in self.entries]

    def search_by_multiple_tags(
        self,
        tags: List[str],
        match_all: bool = True,
    ) -> List[IndexEntry]:
        """
        複数タグで検索

        Args:
            tags: タグリスト
            match_all: すべてのタグにマッチする必要があるか

        Returns:
            マッチしたエントリリスト
        """
        if not tags:
            return []

        # 各タグのキーセットを取得
        tag_sets = [
            self.tag_index.get(tag, set()) for tag in tags
        ]

        # 共通集合または和集合
        if match_all:
            common_keys = set.intersection(*tag_sets) if tag_sets else set()
        else:
            common_keys = set.union(*tag_sets) if tag_sets else set()

        return [
            self.entries[k] for k in common_keys
            if k in self.entries
        ]

    def search_text(self, query: str) -> List[IndexEntry]:
        """
        全文検索

        Args:
            query: 検索クエリ

        Returns:
            マッチしたエントリリスト
        """
        query_words = query.lower().split()

        # 最初のワードに一致するキーを取得
        if not query_words:
            return []

        first_word = query_words[0]
        matching_keys = self.text_index.get(first_word, set()).copy()

        # 他のワードでフィルタ
        for word in query_words[1:]:
            word_keys = self.text_index.get(word, set())
            matching_keys &= word_keys

        return [
            self.entries[k] for k in matching_keys
            if k in self.entries
        ]

    # =================================================
    # Graph Operations
    # =================================================

    def link_entries(
        self,
        from_key: str,
        to_key: str,
    ):
        """
        エントリ間にリンクを張る

        Args:
            from_key: ソースキー
            to_key: ターゲットキー
        """
        if from_key in self.entries:
            self.entries[from_key].references.add(to_key)

    def find_related_entries(
        self,
        key: str,
        depth: int = 1,
    ) -> Set[str]:
        """
        関連エントリを検索

        Args:
            key: 開始キー
            depth: 探索深さ

        Returns:
            関連キーのセット
        """
        if key not in self.entries:
            return set()

        visited = set()
        to_explore = [key]

        for _ in range(depth):
            new_to_explore = []

            for current_key in to_explore:
                if current_key in visited:
                    continue

                visited.add(current_key)

                # 参照を追加
                if current_key in self.entries:
                    refs = self.entries[current_key].references
                    new_to_explore.extend(refs - visited)

            to_explore = new_to_explore

        # 開始キーを除去
        visited.discard(key)
        return visited

    # =================================================
    # Statistics
    # =================================================

    def get_statistics(self) -> Dict[str, Any]:
        """
        インデックス統計を取得

        Returns:
            統計情報
        """
        return {
            "total_entries": len(self.entries),
            "total_tags": len(self.tag_index),
            "total_keywords": len(self.text_index),
            "avg_references": (
                sum(len(e.references) for e in self.entries.values()) /
                len(self.entries)
                if self.entries else 0.0
            ),
        }

    def get_tag_statistics(self) -> Dict[str, int]:
        """
        タグ別統計を取得

        Returns:
            タグ → エントリ数
        """
        return {
            tag: len(keys) for tag, keys in self.tag_index.items()
        }

    # =================================================
    # Maintenance
    # =================================================

    def remove_entry(self, key: str):
        """
        エントリを削除

        Args:
            key: エントリキー
        """
        if key not in self.entries:
            return

        # メインインデックスから削除
        del self.entries[key]

        # タグインデックスから削除
        for tag in list(self.tag_index.keys()):
            self.tag_index[tag].discard(key)
            if not self.tag_index[tag]:
                del self.tag_index[tag]

        # 全文検索インデックスから削除
        for word in list(self.text_index.keys()):
            self.text_index[word].discard(key)
            if not self.text_index[word]:
                del self.text_index[word]

    def optimize(self):
        """
        インデックスを最適化（不要なエントリを削除）
        """
        # 空のタグを削除
        empty_tags = [
            tag for tag, keys in self.tag_index.items()
            if not keys
        ]
        for tag in empty_tags:
            del self.tag_index[tag]

        # 空のキーワードを削除
        empty_words = [
            word for word, keys in self.text_index.items()
            if not keys
        ]
        for word in empty_words:
            del self.text_index[word]

    def clear(self):
        """すべてをクリア"""
        self.entries.clear()
        self.tag_index.clear()
        self.text_index.clear()

    # =================================================
    # Export / Import
    # =================================================

    def export_index(self) -> str:
        """
        インデックスをJSON形式でエクスポート

        Returns:
            JSON文字列
        """
        data = {
            "entries": [
                {
                    "key": k,
                    "value": str(v.value),
                    "metadata": v.metadata,
                    "tags": list(v.references),
                }
                for k, v in self.entries.items()
            ],
            "statistics": self.get_statistics(),
        }
        return json.dumps(data, ensure_ascii=False, indent=2)

    def import_index(self, json_str: str):
        """
        JSON からインデックスをインポート

        Args:
            json_str: JSON文字列
        """
        data = json.loads(json_str)

        for entry_data in data.get("entries", []):
            self.index_entry(
                key=entry_data["key"],
                value=entry_data["value"],
                tags=entry_data.get("tags", []),
                metadata=entry_data.get("metadata", {}),
            )
