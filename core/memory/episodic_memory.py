# core/memory/episodic_memory.py

import sqlite3
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


@dataclass
class Bet:
    """ベット記録"""
    bet_id: str
    race_id: str
    horse_id: str
    bet_type: str  # "win", "place", "wide", "exacta"
    bet_size: float
    odds: float
    result: str  # "win", "loss", "void"
    payout: float
    timestamp: datetime


class EpisodicMemory:
    """
    エピソード記憶

    SQLite ベースのベット履歴管理

    機能:
    - ベット記録の保存
    - レースID / 日付 / 結果による検索
    - 統計分析
    """

    def __init__(self, db_path: Optional[str] = None):
        """
        初期化

        Args:
            db_path: SQLite DB のパス（Noneの場合は :memory:）
        """
        if db_path is None:
            self.db_path = ":memory:"
        else:
            self.db_path = db_path
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        self.conn: Optional[sqlite3.Connection] = None
        self._init_db()

    # =================================================
    # Database Initialization
    # =================================================

    def _init_db(self):
        """データベースを初期化"""
        self.conn = sqlite3.connect(self.db_path)
        cursor = self.conn.cursor()

        # ベット記録テーブル
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS bets (
                bet_id TEXT PRIMARY KEY,
                race_id TEXT NOT NULL,
                horse_id TEXT NOT NULL,
                bet_type TEXT NOT NULL,
                bet_size REAL NOT NULL,
                odds REAL NOT NULL,
                result TEXT NOT NULL,
                payout REAL NOT NULL,
                timestamp TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # インデックスを作成
        cursor.execute(
            'CREATE INDEX IF NOT EXISTS idx_race_id ON bets(race_id)'
        )
        cursor.execute(
            'CREATE INDEX IF NOT EXISTS idx_timestamp ON bets(timestamp)'
        )
        cursor.execute(
            'CREATE INDEX IF NOT EXISTS idx_result ON bets(result)'
        )

        self.conn.commit()

    # =================================================
    # Bet Recording
    # =================================================

    def record_bet(
        self,
        bet_id: str,
        race_id: str,
        horse_id: str,
        bet_type: str,
        bet_size: float,
        odds: float,
        result: str,
        payout: float,
        timestamp: Optional[datetime] = None,
    ):
        """
        ベットを記録

        Args:
            bet_id: ベットID
            race_id: レースID
            horse_id: 馬ID
            bet_type: ベットタイプ
            bet_size: ベットサイズ
            odds: オッズ
            result: 結果
            payout: 配当
            timestamp: タイムスタンプ
        """
        from core.utilities import now_jst

        if timestamp is None:
            timestamp = now_jst()

        cursor = self.conn.cursor()

        cursor.execute('''
            INSERT OR REPLACE INTO bets
            (bet_id, race_id, horse_id, bet_type, bet_size, odds, result, payout, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            bet_id, race_id, horse_id, bet_type,
            bet_size, odds, result, payout, timestamp.isoformat()
        ))

        self.conn.commit()

        logger.info(f"Recorded bet: {bet_id}")

    # =================================================
    # Search & Retrieval
    # =================================================

    def get_bet_by_id(self, bet_id: str) -> Optional[Bet]:
        """
        ベットID で取得

        Args:
            bet_id: ベットID

        Returns:
            Bet またはNone
        """
        cursor = self.conn.cursor()
        cursor.execute(
            'SELECT * FROM bets WHERE bet_id = ?',
            (bet_id,)
        )
        row = cursor.fetchone()

        if row:
            return self._row_to_bet(row)
        return None

    def get_bets_by_race(self, race_id: str) -> List[Bet]:
        """
        レースID で取得

        Args:
            race_id: レースID

        Returns:
            ベットリスト
        """
        cursor = self.conn.cursor()
        cursor.execute(
            'SELECT * FROM bets WHERE race_id = ? ORDER BY timestamp DESC',
            (race_id,)
        )
        rows = cursor.fetchall()

        return [self._row_to_bet(row) for row in rows]

    def get_bets_by_date_range(
        self,
        start_date: datetime,
        end_date: datetime,
    ) -> List[Bet]:
        """
        日付範囲で取得

        Args:
            start_date: 開始日
            end_date: 終了日

        Returns:
            ベットリスト
        """
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT * FROM bets
            WHERE timestamp >= ? AND timestamp <= ?
            ORDER BY timestamp DESC
        ''', (start_date.isoformat(), end_date.isoformat()))
        rows = cursor.fetchall()

        return [self._row_to_bet(row) for row in rows]

    def get_bets_by_result(self, result: str) -> List[Bet]:
        """
        結果で取得

        Args:
            result: 結果（"win", "loss", "void"）

        Returns:
            ベットリスト
        """
        cursor = self.conn.cursor()
        cursor.execute(
            'SELECT * FROM bets WHERE result = ? ORDER BY timestamp DESC',
            (result,)
        )
        rows = cursor.fetchall()

        return [self._row_to_bet(row) for row in rows]

    def get_recent_bets(self, limit: int = 100) -> List[Bet]:
        """
        最近のベットを取得

        Args:
            limit: 取得件数

        Returns:
            ベットリスト
        """
        cursor = self.conn.cursor()
        cursor.execute(
            'SELECT * FROM bets ORDER BY timestamp DESC LIMIT ?',
            (limit,)
        )
        rows = cursor.fetchall()

        return [self._row_to_bet(row) for row in rows]

    # =================================================
    # Statistics
    # =================================================

    def get_statistics(
        self,
        days: int = 30,
    ) -> Dict[str, Any]:
        """
        統計情報を取得

        Args:
            days: 過去N日間

        Returns:
            統計情報
        """
        from core.utilities import now_jst

        cutoff_date = now_jst() - timedelta(days=days)

        cursor = self.conn.cursor()

        # 総ベット数
        cursor.execute(
            'SELECT COUNT(*) FROM bets WHERE timestamp >= ?',
            (cutoff_date.isoformat(),)
        )
        total_bets = cursor.fetchone()[0]

        # 勝利数
        cursor.execute(
            'SELECT COUNT(*) FROM bets WHERE timestamp >= ? AND result = ?',
            (cutoff_date.isoformat(), "win")
        )
        wins = cursor.fetchone()[0]

        # 損失数
        cursor.execute(
            'SELECT COUNT(*) FROM bets WHERE timestamp >= ? AND result = ?',
            (cutoff_date.isoformat(), "loss")
        )
        losses = cursor.fetchone()[0]

        # 総ベット額
        cursor.execute(
            'SELECT SUM(bet_size) FROM bets WHERE timestamp >= ?',
            (cutoff_date.isoformat(),)
        )
        total_bet_amount = cursor.fetchone()[0] or 0.0

        # 総配当
        cursor.execute(
            'SELECT SUM(payout) FROM bets WHERE timestamp >= ?',
            (cutoff_date.isoformat(),)
        )
        total_payout = cursor.fetchone()[0] or 0.0

        # ROI
        roi = (
            (total_payout - total_bet_amount) / total_bet_amount * 100
            if total_bet_amount > 0
            else 0.0
        )

        # 勝率
        win_rate = (
            wins / total_bets * 100 if total_bets > 0 else 0.0
        )

        return {
            "period_days": days,
            "total_bets": total_bets,
            "wins": wins,
            "losses": losses,
            "win_rate": win_rate,
            "total_bet_amount": total_bet_amount,
            "total_payout": total_payout,
            "roi": roi,
            "profit": total_payout - total_bet_amount,
        }

    def get_horse_statistics(self, horse_id: str) -> Dict[str, Any]:
        """
        馬別統計を取得

        Args:
            horse_id: 馬ID

        Returns:
            統計情報
        """
        cursor = self.conn.cursor()

        # この馬へのベット数
        cursor.execute(
            'SELECT COUNT(*) FROM bets WHERE horse_id = ?',
            (horse_id,)
        )
        total_bets = cursor.fetchone()[0]

        # 勝利数
        cursor.execute(
            'SELECT COUNT(*) FROM bets WHERE horse_id = ? AND result = ?',
            (horse_id, "win")
        )
        wins = cursor.fetchone()[0]

        # 総ベット額
        cursor.execute(
            'SELECT SUM(bet_size) FROM bets WHERE horse_id = ?',
            (horse_id,)
        )
        total_bet_amount = cursor.fetchone()[0] or 0.0

        # 総配当
        cursor.execute(
            'SELECT SUM(payout) FROM bets WHERE horse_id = ?',
            (horse_id,)
        )
        total_payout = cursor.fetchone()[0] or 0.0

        return {
            "horse_id": horse_id,
            "total_bets": total_bets,
            "wins": wins,
            "win_rate": wins / total_bets * 100 if total_bets > 0 else 0.0,
            "total_amount": total_bet_amount,
            "total_payout": total_payout,
            "profit": total_payout - total_bet_amount,
        }

    # =================================================
    # Cleanup
    # =================================================

    def delete_old_records(self, days: int = 365):
        """
        古いレコードを削除

        Args:
            days: N日以上前のレコードを削除
        """
        from core.utilities import now_jst

        cutoff_date = now_jst() - timedelta(days=days)

        cursor = self.conn.cursor()
        cursor.execute(
            'DELETE FROM bets WHERE timestamp < ?',
            (cutoff_date.isoformat(),)
        )
        deleted = cursor.rowcount
        self.conn.commit()

        logger.info(f"Deleted {deleted} old records")

    def close(self):
        """接続を閉じる"""
        if self.conn:
            self.conn.close()

    # =================================================
    # Helper
    # =================================================

    @staticmethod
    def _row_to_bet(row: Tuple) -> Bet:
        """行をBetオブジェクトに変換"""
        return Bet(
            bet_id=row[0],
            race_id=row[1],
            horse_id=row[2],
            bet_type=row[3],
            bet_size=row[4],
            odds=row[5],
            result=row[6],
            payout=row[7],
            timestamp=datetime.fromisoformat(row[8]),
        )
