# core/civilization_memory.py

import json
import os
import hashlib

from datetime import datetime
from collections import defaultdict

from infrastructure.database import (
    SurvivalDatabase
)

from core.audit_logger import (
    AuditLogger
)

from core.alert_manager import (
    AlertManager
)


class CivilizationMemory:
    """
    Persistent Civilization Memory

    目的:
    - long-term knowledge retention
    - historical survival preservation
    - civilization doctrine storage
    - strategic inheritance

    最重要:
    「生存知識を文明として継承する」
    """

    def __init__(
        self,
    ):

        # =================================================
        # infrastructure
        # =================================================

        self.db = (
            SurvivalDatabase()
        )

        self.audit = (
            AuditLogger()
        )

        self.alerts = (
            AlertManager()
        )

        # =================================================
        # memory stores
        # =================================================

        self.events = []

        self.lessons = []

        self.doctrines = []

        self.failures = []

        self.success_patterns = []

        self.collapse_archives = []

        self.adaptation_history = []

        # =================================================
        # semantic indexes
        # =================================================

        self.tags = defaultdict(
            list
        )

        self.hash_index = {}

        # =================================================
        # storage
        # =================================================

        self.memory_path = (
            "memory/"
            "civilization_memory.json"
        )

        os.makedirs(
            "memory",
            exist_ok=True,
        )

        # =================================================
        # metadata
        # =================================================

        self.created_at = (
            datetime.utcnow()
            .isoformat()
        )

        self.last_update = None

        # =================================================
        # load previous civilization
        # =================================================

        self.load()

    # =================================================
    # Record Event
    # =================================================

    def record_event(

        self,

        category,
        title,
        content,
        severity=0.5,
        tags=None,
    ):

        tags = tags or []

        entry = {

            "id":
                self.generate_id(
                    title + content
                ),

            "timestamp":
                datetime.utcnow()
                .isoformat(),

            "category":
                category,

            "title":
                title,

            "content":
                content,

            "severity":
                severity,

            "tags":
                tags,
        }

        self.events.append(
            entry
        )

        self.index_entry(
            entry
        )

        self.last_update = (
            entry["timestamp"]
        )

        self.persist()

        return entry

    # =================================================
    # Record Lesson
    # =================================================

    def record_lesson(

        self,

        lesson,
        outcome,
        importance=0.5,
        tags=None,
    ):

        tags = tags or []

        entry = {

            "id":
                self.generate_id(
                    lesson + outcome
                ),

            "timestamp":
                datetime.utcnow()
                .isoformat(),

            "lesson":
                lesson,

            "outcome":
                outcome,

            "importance":
                importance,

            "tags":
                tags,
        }

        self.lessons.append(
            entry
        )

        self.index_entry(
            entry
        )

        self.persist()

        return entry

    # =================================================
    # Record Doctrine
    # =================================================

    def record_doctrine(

        self,

        doctrine,
        rationale,
        priority=1,
        tags=None,
    ):

        tags = tags or []

        entry = {

            "id":
                self.generate_id(
                    doctrine
                ),

            "timestamp":
                datetime.utcnow()
                .isoformat(),

            "doctrine":
                doctrine,

            "rationale":
                rationale,

            "priority":
                priority,

            "tags":
                tags,
        }

        self.doctrines.append(
            entry
        )

        self.index_entry(
            entry
        )

        self.persist()

        return entry

    # =================================================
    # Record Collapse
    # =================================================

    def record_collapse(

        self,

        cause,
        impact,
        recovery,
        tags=None,
    ):

        tags = tags or []

        entry = {

            "id":
                self.generate_id(
                    cause + recovery
                ),

            "timestamp":
                datetime.utcnow()
                .isoformat(),

            "cause":
                cause,

            "impact":
                impact,

            "recovery":
                recovery,

            "tags":
                tags,
        }

        self.collapse_archives.append(
            entry
        )

        self.index_entry(
            entry
        )

        self.alerts.emit(

            level="CRITICAL",

            title=(
                "COLLAPSE ARCHIVED"
            ),

            message=cause,
        )

        self.persist()

        return entry

    # =================================================
    # Record Success Pattern
    # =================================================

    def record_success_pattern(

        self,

        strategy,
        result,
        confidence=0.5,
        tags=None,
    ):

        tags = tags or []

        entry = {

            "id":
                self.generate_id(
                    strategy + result
                ),

            "timestamp":
                datetime.utcnow()
                .isoformat(),

            "strategy":
                strategy,

            "result":
                result,

            "confidence":
                confidence,

            "tags":
                tags,
        }

        self.success_patterns.append(
            entry
        )

        self.index_entry(
            entry
        )

        self.persist()

        return entry

    # =================================================
    # Record Adaptation
    # =================================================

    def record_adaptation(

        self,

        trigger,
        mutation,
        outcome,
        tags=None,
    ):

        tags = tags or []

        entry = {

            "id":
                self.generate_id(
                    trigger + mutation
                ),

            "timestamp":
                datetime.utcnow()
                .isoformat(),

            "trigger":
                trigger,

            "mutation":
                mutation,

            "outcome":
                outcome,

            "tags":
                tags,
        }

        self.adaptation_history.append(
            entry
        )

        self.index_entry(
            entry
        )

        self.persist()

        return entry

    # =================================================
    # Semantic Indexing
    # =================================================

    def index_entry(

        self,

        entry,
    ):

        entry_id = entry["id"]

        self.hash_index[
            entry_id
        ] = entry

        tags = entry.get(
            "tags",
            []
        )

        for tag in tags:

            self.tags[tag].append(
                entry_id
            )

    # =================================================
    # Search by Tag
    # =================================================

    def search_by_tag(

        self,

        tag,
    ):

        ids = self.tags.get(
            tag,
            []
        )

        results = []

        for entry_id in ids:

            if entry_id in (
                self.hash_index
            ):

                results.append(

                    self.hash_index[
                        entry_id
                    ]
                )

        return results

    # =================================================
    # Search Text
    # =================================================

    def search_text(

        self,

        query,
    ):

        query = query.lower()

        results = []

        for entry in (
            self.all_entries()
        ):

            serialized = json.dumps(
                entry
            ).lower()

            if query in serialized:

                results.append(
                    entry
                )

        return results

    # =================================================
    # Civilization Summary
    # =================================================

    def civilization_summary(
        self,
    ):

        return {

            "events":
                len(
                    self.events
                ),

            "lessons":
                len(
                    self.lessons
                ),

            "doctrines":
                len(
                    self.doctrines
                ),

            "collapses":
                len(
                    self.collapse_archives
                ),

            "success_patterns":
                len(
                    self.success_patterns
                ),

            "adaptations":
                len(
                    self.adaptation_history
                ),

            "created_at":
                self.created_at,

            "last_update":
                self.last_update,
        }

    # =================================================
    # All Entries
    # =================================================

    def all_entries(
        self,
    ):

        return (

            self.events +

            self.lessons +

            self.doctrines +

            self.failures +

            self.success_patterns +

            self.collapse_archives +

            self.adaptation_history
        )

    # =================================================
    # Persistence
    # =================================================

    def persist(
        self,
    ):

        payload = {

            "created_at":
                self.created_at,

            "last_update":
                self.last_update,

            "events":
                self.events,

            "lessons":
                self.lessons,

            "doctrines":
                self.doctrines,

            "failures":
                self.failures,

            "success_patterns":
                self.success_patterns,

            "collapse_archives":
                self.collapse_archives,

            "adaptation_history":
                self.adaptation_history,
        }

        with open(

            self.memory_path,

            "w",

            encoding="utf-8",
        ) as f:

            json.dump(

                payload,

                f,

                indent=2,

                ensure_ascii=False,
            )

        self.db.save_snapshot(

            state_type=
                "CIVILIZATION_MEMORY",

            payload=self.civilization_summary(),
        )

        self.audit.log(

            category=
                "CIVILIZATION_MEMORY",

            action=
                "PERSIST",

            severity="INFO",

            metadata={
                "entries":
                    len(
                        self.all_entries()
                    )
            },
        )

    # =================================================
    # Load Memory
    # =================================================

    def load(
        self,
    ):

        if not os.path.exists(
            self.memory_path
        ):

            return

        with open(

            self.memory_path,

            "r",

            encoding="utf-8",
        ) as f:

            payload = json.load(
                f
            )

        self.events = payload.get(
            "events",
            []
        )

        self.lessons = payload.get(
            "lessons",
            []
        )

        self.doctrines = payload.get(
            "doctrines",
            []
        )

        self.failures = payload.get(
            "failures",
            []
        )

        self.success_patterns = (
            payload.get(
                "success_patterns",
                []
            )
        )

        self.collapse_archives = (
            payload.get(
                "collapse_archives",
                []
            )
        )

        self.adaptation_history = (
            payload.get(
                "adaptation_history",
                []
            )
        )

        self.created_at = payload.get(
            "created_at",
            self.created_at,
        )

        self.last_update = payload.get(
            "last_update"
        )

        # =================================================
        # rebuild indexes
        # =================================================

        for entry in (
            self.all_entries()
        ):

            self.index_entry(
                entry
            )

    # =================================================
    # Generate ID
    # =================================================

    def generate_id(

        self,

        text,
    ):

        return hashlib.sha256(

            text.encode(
                "utf-8"
            )

        ).hexdigest()[:16]

    # =================================================
    # Diagnostics
    # =================================================

    def diagnostics(
        self,
    ):

        return {

            "summary":
                self.civilization_summary(),

            "indexed_tags":
                len(
                    self.tags
                ),

            "indexed_entries":
                len(
                    self.hash_index
                ),
        }


# =====================================================
# Example
# =====================================================

if __name__ == "__main__":

    memory = (
        CivilizationMemory()
    )

    memory.record_event(

        category=
            "MARKET",

        title=
            "Volatility Spike",

        content=
            "Detected abnormal volatility regime",

        severity=0.82,

        tags=[
            "volatility",
            "risk",
        ],
    )

    memory.record_lesson(

        lesson=
            "High leverage increases collapse probability",

        outcome=
            "Reduced leverage improved survival",

        importance=0.93,

        tags=[
            "survival",
            "risk_management",
        ],
    )

    memory.record_doctrine(

        doctrine=
            "Survival before expansion",

        rationale=
            "Long-term persistence dominates short-term gains",

        priority=1,

        tags=[
            "civilization",
            "strategy",
        ],
    )

    memory.record_collapse(

        cause=
            "Liquidity collapse",

        impact=
            "Massive drawdown",

        recovery=
            "Emergency deleveraging",

        tags=[
            "collapse",
            "liquidity",
        ],
    )

    memory.record_success_pattern(

        strategy=
            "Adaptive scaling",

        result=
            "Reduced infrastructure stress",

        confidence=0.87,

        tags=[
            "adaptation",
            "resilience",
        ],
    )

    memory.record_adaptation(

        trigger=
            "High stress regime",

        mutation=
            "Lowered risk tolerance",

        outcome=
            "Improved stability",

        tags=[
            "evolution",
            "adaptation",
        ],
    )

    print(
        memory.civilization_summary()
    )

    print(
        memory.search_by_tag(
            "survival"
        )
    )

    print(
        memory.search_text(
            "collapse"
        )
    )

    print(
        memory.diagnostics()
    )