# infrastructure/database.py

import os
import sqlite3
import threading

from datetime import datetime


class SurvivalDatabase:
    """
    Persistent Survival Infrastructure

    目的:
    - durable memory
    - crash recovery
    - concurrent persistence
    - historical intelligence storage

    最重要:
    「死んでも記憶を失わない」
    """

    def __init__(

        self,

        db_path=(
            "infrastructure/survival_os.db"
        ),
    ):

        self.db_path = db_path

        os.makedirs(
            "infrastructure",
            exist_ok=True,
        )

        # =================================================
        # thread safety
        # =================================================

        self.lock = (
            threading.Lock()
        )

        # =================================================
        # initialize
        # =================================================

        self.initialize()

    # =================================================
    # Connection
    # =================================================

    def connect(
        self,
    ):

        conn = sqlite3.connect(

            self.db_path,

            check_same_thread=False,
        )

        conn.row_factory = (
            sqlite3.Row
        )

        return conn

    # =================================================
    # Initialize Tables
    # =================================================

    def initialize(
        self,
    ):

        conn = self.connect()

        cursor = conn.cursor()

        # =================================================
        # executive decisions
        # =================================================

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS executive_decisions (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            timestamp TEXT,

            regime TEXT,

            action TEXT,

            reason TEXT,

            risk REAL,

            payload TEXT
        )
        """)

        # =================================================
        # outcomes
        # =================================================

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS outcomes (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            timestamp TEXT,

            result TEXT,

            fitness REAL,

            survival REAL,

            accuracy REAL,

            payload TEXT
        )
        """)

        # =================================================
        # knowledge graph nodes
        # =================================================

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS knowledge_nodes (

            id TEXT PRIMARY KEY,

            type TEXT,

            value TEXT,

            mentions INTEGER,

            metadata TEXT,

            created_at TEXT,

            updated_at TEXT
        )
        """)

        # =================================================
        # knowledge graph edges
        # =================================================

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS knowledge_edges (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            source TEXT,

            target TEXT,

            relation TEXT,

            weight REAL,

            metadata TEXT,

            timestamp TEXT
        )
        """)

        # =================================================
        # meta learning
        # =================================================

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS meta_learning (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            timestamp TEXT,

            regime TEXT,

            model_type TEXT,

            mutation_type TEXT,

            fitness REAL,

            survival REAL,

            accuracy REAL,

            metadata TEXT
        )
        """)

        # =================================================
        # alerts
        # =================================================

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS alerts (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            timestamp TEXT,

            level TEXT,

            title TEXT,

            message TEXT
        )
        """)

        # =================================================
        # audit logs
        # =================================================

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            timestamp TEXT,

            category TEXT,

            action TEXT,

            severity TEXT,

            metadata TEXT
        )
        """)

        # =================================================
        # state snapshots
        # =================================================

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS state_snapshots (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            timestamp TEXT,

            state_type TEXT,

            payload TEXT
        )
        """)

        # =================================================
        # evolution history
        # =================================================

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS evolution_history (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            timestamp TEXT,

            generation INTEGER,

            candidate TEXT,

            fitness REAL,

            payload TEXT
        )
        """)

        conn.commit()

        conn.close()

        print(
            "[DATABASE INITIALIZED]"
        )

    # =================================================
    # Insert
    # =================================================

    def insert(

        self,

        table,
        data,
    ):

        with self.lock:

            conn = self.connect()

            cursor = conn.cursor()

            columns = ", ".join(
                data.keys()
            )

            placeholders = ", ".join(
                ["?"] * len(data)
            )

            query = f"""
            INSERT INTO {table}
            ({columns})
            VALUES ({placeholders})
            """

            cursor.execute(

                query,

                list(data.values())
            )

            conn.commit()

            row_id = cursor.lastrowid

            conn.close()

            return row_id

    # =================================================
    # Fetch All
    # =================================================

    def fetch_all(

        self,

        table,
        limit=100,
    ):

        conn = self.connect()

        cursor = conn.cursor()

        query = f"""
        SELECT *
        FROM {table}
        ORDER BY id DESC
        LIMIT ?
        """

        cursor.execute(
            query,
            (limit,)
        )

        rows = cursor.fetchall()

        conn.close()

        return [

            dict(row)
            for row in rows
        ]

    # =================================================
    # Fetch Recent
    # =================================================

    def fetch_recent(

        self,

        table,
        timestamp_field="timestamp",
        limit=10,
    ):

        conn = self.connect()

        cursor = conn.cursor()

        query = f"""
        SELECT *
        FROM {table}
        ORDER BY {timestamp_field} DESC
        LIMIT ?
        """

        cursor.execute(
            query,
            (limit,)
        )

        rows = cursor.fetchall()

        conn.close()

        return [

            dict(row)
            for row in rows
        ]

    # =================================================
    # Delete Old Records
    # =================================================

    def cleanup(

        self,

        table,
        keep_latest=10000,
    ):

        with self.lock:

            conn = self.connect()

            cursor = conn.cursor()

            cursor.execute(f"""
            DELETE FROM {table}
            WHERE id NOT IN (
                SELECT id
                FROM {table}
                ORDER BY id DESC
                LIMIT ?
            )
            """, (keep_latest,))

            deleted = (
                cursor.rowcount
            )

            conn.commit()

            conn.close()

            return deleted

    # =================================================
    # System Statistics
    # =================================================

    def statistics(
        self,
    ):

        conn = self.connect()

        cursor = conn.cursor()

        tables = [

            "executive_decisions",

            "outcomes",

            "knowledge_nodes",

            "knowledge_edges",

            "meta_learning",

            "alerts",

            "audit_logs",

            "state_snapshots",

            "evolution_history",
        ]

        stats = {}

        for table in tables:

            cursor.execute(f"""
            SELECT COUNT(*)
            as count
            FROM {table}
            """)

            count = cursor.fetchone()[
                "count"
            ]

            stats[table] = count

        conn.close()

        return stats

    # =================================================
    # Save Executive Decision
    # =================================================

    def save_decision(

        self,

        decision,
    ):

        return self.insert(

            "executive_decisions",

            {

                "timestamp":
                    decision.get(
                        "timestamp"
                    ),

                "regime":
                    decision.get(
                        "regime"
                    ),

                "action":
                    decision.get(
                        "action"
                    ),

                "reason":
                    decision.get(
                        "reason"
                    ),

                "risk":
                    decision.get(
                        "risk"
                    ),

                "payload":
                    str(decision),
            }
        )

    # =================================================
    # Save Outcome
    # =================================================

    def save_outcome(

        self,

        outcome,
    ):

        return self.insert(

            "outcomes",

            {

                "timestamp":
                    datetime.utcnow()
                    .isoformat(),

                "result":
                    outcome.get(
                        "result"
                    ),

                "fitness":
                    outcome.get(
                        "fitness"
                    ),

                "survival":
                    outcome.get(
                        "survival"
                    ),

                "accuracy":
                    outcome.get(
                        "accuracy"
                    ),

                "payload":
                    str(outcome),
            }
        )

    # =================================================
    # Save Alert
    # =================================================

    def save_alert(

        self,

        level,
        title,
        message,
    ):

        return self.insert(

            "alerts",

            {

                "timestamp":
                    datetime.utcnow()
                    .isoformat(),

                "level":
                    level,

                "title":
                    title,

                "message":
                    message,
            }
        )

    # =================================================
    # Save Audit
    # =================================================

    def save_audit(

        self,

        category,
        action,
        severity,
        metadata=None,
    ):

        return self.insert(

            "audit_logs",

            {

                "timestamp":
                    datetime.utcnow()
                    .isoformat(),

                "category":
                    category,

                "action":
                    action,

                "severity":
                    severity,

                "metadata":
                    str(
                        metadata or {}
                    ),
            }
        )

    # =================================================
    # Save State Snapshot
    # =================================================

    def save_snapshot(

        self,

        state_type,
        payload,
    ):

        return self.insert(

            "state_snapshots",

            {

                "timestamp":
                    datetime.utcnow()
                    .isoformat(),

                "state_type":
                    state_type,

                "payload":
                    str(payload),
            }
        )

    # =================================================
    # Recent Failures
    # =================================================

    def recent_failures(
        self,
        limit=20,
    ):

        conn = self.connect()

        cursor = conn.cursor()

        cursor.execute("""
        SELECT *
        FROM outcomes
        WHERE result IN (
            'FAILURE',
            'COLLAPSE',
            'DRIFT'
        )
        ORDER BY id DESC
        LIMIT ?
        """, (limit,))

        rows = cursor.fetchall()

        conn.close()

        return [

            dict(row)
            for row in rows
        ]

    # =================================================
    # Diagnostics
    # =================================================

    def diagnostics(
        self,
    ):

        return {

            "db_path":
                self.db_path,

            "statistics":
                self.statistics(),
        }


# =====================================================
# Example
# =====================================================

if __name__ == "__main__":

    db = SurvivalDatabase()

    decision_id = db.save_decision({

        "timestamp":
            datetime.utcnow()
            .isoformat(),

        "regime":
            "DRIFT",

        "action":
            "RETRAIN",

        "reason":
            "survival degraded",

        "risk":
            0.71,
    })

    print(
        "[DECISION ID]",
        decision_id,
    )

    db.save_outcome({

        "result":
            "RECOVERY",

        "fitness":
            0.82,

        "survival":
            0.77,

        "accuracy":
            0.63,
    })

    db.save_alert(

        level="WARNING",

        title="High Risk",

        message="volatility spike",
    )

    print(
        db.statistics()
    )

    print(
        db.recent_failures()
    )

    print(
        db.diagnostics()
    )