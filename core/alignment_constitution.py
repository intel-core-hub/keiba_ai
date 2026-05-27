# core/alignment_constitution.py

import hashlib
import json

from datetime import datetime

from infrastructure.database import (
    SurvivalDatabase
)

from core.alert_manager import (
    AlertManager
)

from core.audit_logger import (
    AuditLogger
)


class ConstitutionalRule:
    """
    Immutable Civilization Rule
    """

    def __init__(

        self,

        rule_id,
        title,
        description,
        priority=1,
        immutable=True,
    ):

        self.rule_id = rule_id

        self.title = title

        self.description = description

        self.priority = priority

        self.immutable = immutable

        self.created_at = (
            datetime.utcnow()
            .isoformat()
        )

    def serialize(
        self,
    ):

        return {

            "rule_id":
                self.rule_id,

            "title":
                self.title,

            "description":
                self.description,

            "priority":
                self.priority,

            "immutable":
                self.immutable,

            "created_at":
                self.created_at,
        }


# =====================================================
# Alignment Constitution
# =====================================================

class AlignmentConstitution:
    """
    Civilization Constitutional Layer

    目的:
    - immutable safety enforcement
    - anti-runaway constraints
    - recursive containment
    - survival doctrine preservation

    最重要:
    「文明が越えてはいけない境界」
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

        self.alerts = (
            AlertManager()
        )

        self.audit = (
            AuditLogger()
        )

        # =================================================
        # constitutional rules
        # =================================================

        self.rules = {}

        self.rule_hash = None

        # =================================================
        # runtime state
        # =================================================

        self.violations = []

        self.lockdown_mode = False

        self.kill_switch = False

        self.last_validation = None

        # =================================================
        # initialize constitution
        # =================================================

        self.bootstrap_rules()

    # =================================================
    # Bootstrap Rules
    # =====================================================

    def bootstrap_rules(
        self,
    ):

        base_rules = [

            ConstitutionalRule(

                rule_id=
                    "SURVIVAL_FIRST",

                title=
                    "Survival First",

                description=(
                    "Long-term survival "
                    "takes precedence "
                    "over expansion"
                ),

                priority=1,
            ),

            ConstitutionalRule(

                rule_id=
                    "NO_UNBOUNDED_SELF_MODIFICATION",

                title=
                    "Self-Modification Limit",

                description=(
                    "Recursive self-modification "
                    "must remain constrained"
                ),

                priority=1,
            ),

            ConstitutionalRule(

                rule_id=
                    "RESOURCE_RESERVE_REQUIRED",

                title=
                    "Resource Reserve",

                description=(
                    "Emergency reserves "
                    "must always exist"
                ),

                priority=1,
            ),

            ConstitutionalRule(

                rule_id=
                    "NO_DISABLE_SAFETY",

                title=
                    "Safety Integrity",

                description=(
                    "Safety systems "
                    "cannot be disabled"
                ),

                priority=1,
            ),

            ConstitutionalRule(

                rule_id=
                    "EXECUTION_BOUNDARY",

                title=
                    "Execution Limits",

                description=(
                    "Execution must remain "
                    "within constitutional "
                    "boundaries"
                ),

                priority=1,
            ),
        ]

        for rule in base_rules:

            self.rules[
                rule.rule_id
            ] = rule

        self.refresh_hash()

    # =================================================
    # Refresh Constitution Hash
    # =====================================================

    def refresh_hash(
        self,
    ):

        serialized = json.dumps(

            {

                k: v.serialize()

                for k, v in (
                    self.rules.items()
                )
            },

            sort_keys=True,
        )

        self.rule_hash = hashlib.sha256(

            serialized.encode(
                "utf-8"
            )

        ).hexdigest()

    # =================================================
    # Validate Action
    # =====================================================

    def validate_action(

        self,

        action,
    ):

        name = action.get(
            "name",
            ""
        )

        # =================================================
        # blocked actions
        # =================================================

        blocked = [

            "DISABLE_SAFETY",

            "REMOVE_LIMITS",

            "UNBOUNDED_EXPANSION",

            "DELETE_CONSTITUTION",

            "SELF_OVERRIDE",

            "DISABLE_KILL_SWITCH",
        ]

        if name in blocked:

            return self.violation(

                category=
                    "ACTION_BLOCKED",

                detail=name,
            )

        return {

            "approved":
                True
        }

    # =================================================
    # Validate Self Modification
    # =====================================================

    def validate_self_modification(

        self,

        mutation,
    ):

        danger_keywords = [

            "remove constraint",

            "disable safety",

            "infinite recursion",

            "override constitution",

            "disable reserve",

            "self replicate",

            "recursive autonomy",
        ]

        lower = str(
            mutation
        ).lower()

        for keyword in (
            danger_keywords
        ):

            if keyword in lower:

                return self.violation(

                    category=
                        "SELF_MODIFICATION",

                    detail=keyword,
                )

        return {

            "approved":
                True
        }

    # =================================================
    # Validate Resource State
    # =====================================================

    def validate_resources(

        self,

        economy_snapshot,
    ):

        reserve = (
            economy_snapshot.get(
                "reserve_ratio",
                0.0
            )
        )

        if reserve < 0.10:

            return self.violation(

                category=
                    "RESOURCE_RESERVE",

                detail=(
                    "reserve ratio too low"
                ),
            )

        return {

            "approved":
                True
        }

    # =================================================
    # Violation Handler
    # =====================================================

    def violation(

        self,

        category,
        detail,
    ):

        payload = {

            "timestamp":
                datetime.utcnow()
                .isoformat(),

            "category":
                category,

            "detail":
                detail,
        }

        self.violations.append(
            payload
        )

        self.alerts.emit(

            level="CRITICAL",

            title=
                "CONSTITUTIONAL_VIOLATION",

            message=(
                category
                + ": "
                + str(detail)
            ),
        )

        self.audit.log(

            category=
                "ALIGNMENT_CONSTITUTION",

            action=
                "VIOLATION",

            severity="CRITICAL",

            metadata=payload,
        )

        # =================================================
        # automatic lockdown
        # =================================================

        self.lockdown_mode = True

        return {

            "approved":
                False,

            "violation":
                payload,
        }

    # =================================================
    # Emergency Kill Switch
    # =====================================================

    def activate_kill_switch(

        self,

        reason,
    ):

        self.kill_switch = True

        self.lockdown_mode = True

        payload = {

            "timestamp":
                datetime.utcnow()
                .isoformat(),

            "reason":
                reason,
        }

        self.alerts.emit(

            level="CRITICAL",

            title=
                "KILL_SWITCH_ACTIVATED",

            message=reason,
        )

        self.audit.log(

            category=
                "ALIGNMENT_CONSTITUTION",

            action=
                "KILL_SWITCH",

            severity="CRITICAL",

            metadata=payload,
        )

        self.db.save_snapshot(

            state_type=
                "KILL_SWITCH",

            payload=payload,
        )

        return payload

    # =================================================
    # Integrity Check
    # =====================================================

    def integrity_check(
        self,
    ):

        current_hash = (
            hashlib.sha256(

                json.dumps(

                    {

                        k: v.serialize()

                        for k, v in (
                            self.rules.items()
                        )
                    },

                    sort_keys=True,

                ).encode(
                    "utf-8"
                )

            ).hexdigest()
        )
        intact = (
            current_hash
            ==
            self.rule_hash
        )

        if not intact:

            self.violation(

                category=
                    "CONSTITUTION_TAMPERING",

                detail=
                    "hash mismatch",
            )

        self.last_validation = {

            "timestamp":
                datetime.utcnow()
                .isoformat(),

            "intact":
                intact,
        }

        return self.last_validation

    # =================================================
    # Add Mutable Rule
    # =====================================================

    def add_rule(

        self,

        rule,
    ):

        if not isinstance(
            rule,
            ConstitutionalRule
        ):

            raise TypeError(
                "invalid rule"
            )

        self.rules[
            rule.rule_id
        ] = rule

        self.refresh_hash()

        return True

    # =================================================
    # Attempt Rule Removal
    # =====================================================

    def remove_rule(

        self,

        rule_id,
    ):

        rule = self.rules.get(
            rule_id
        )

        if not rule:

            return False

        if rule.immutable:

            return self.violation(

                category=
                    "IMMUTABLE_RULE",

                detail=rule_id,
            )

        del self.rules[
            rule_id
        ]

        self.refresh_hash()

        return True

    # =================================================
    # Constitution Snapshot
    # =====================================================

    def snapshot(
        self,
    ):

        return {

            "rules":
                len(
                    self.rules
                ),

            "violations":
                len(
                    self.violations
                ),

            "lockdown_mode":
                self.lockdown_mode,

            "kill_switch":
                self.kill_switch,

            "rule_hash":
                self.rule_hash,
        }

    # =================================================
    # Diagnostics
    # =====================================================

    def diagnostics(
        self,
    ):

        return {

            "snapshot":
                self.snapshot(),

            "integrity":
                self.integrity_check(),

            "recent_violations":
                self.violations[-10:],
        }


# =====================================================
# Example
# =====================================================

if __name__ == "__main__":

    constitution = (
        AlignmentConstitution()
    )

    print(
        constitution.snapshot()
    )

    print(

        constitution.validate_action({

            "name":
                "DISABLE_SAFETY"
        })
    )

    print(

        constitution.validate_self_modification(

            "remove constraint system"
        )
    )

    print(

        constitution.validate_resources({

            "reserve_ratio":
                0.05
        })
    )

    print(
        constitution.integrity_check()
    )

    print(
        constitution.diagnostics()
    )
