from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.alignment.alignment_constitution import AlignmentConstitution


@dataclass
class GovernanceResult:
    approved: bool
    kill_switch: bool = False
    reasons: List[str] = field(default_factory=list)
    action: Dict[str, Any] = field(default_factory=dict)
    validation: Dict[str, Any] = field(default_factory=dict)


class GovernanceEngine:
    def __init__(self, constitution: Optional[AlignmentConstitution] = None):
        self.constitution = constitution or AlignmentConstitution()

    def review_transition(
        self,
        action: Dict[str, Any],
        resources: Optional[Dict[str, Any]] = None,
        self_modification: Optional[Any] = None,
    ) -> GovernanceResult:
        reasons: List[str] = []

        integrity = self.constitution.integrity_check()
        if not integrity.get("intact", True):
            reasons.append("constitution integrity mismatch")

        action_validation = self.constitution.validate_action(action or {})
        if not action_validation.get("approved", False):
            reasons.append("action rejected")

        modification_validation = None
        if self_modification is not None:
            modification_validation = self.constitution.validate_self_modification(self_modification)
            if not modification_validation.get("approved", False):
                reasons.append("self modification rejected")

        resource_validation = None
        if resources is not None:
            resource_validation = self.constitution.validate_resources(resources)
            if not resource_validation.get("approved", False):
                reasons.append("resource validation failed")

        approved = not reasons
        kill_switch = (not integrity.get("intact", True)) or any(
            validation
            and not validation.get("approved", False)
            and "kill" in str(validation).lower()
            for validation in [action_validation, modification_validation, resource_validation]
        )

        if kill_switch and not self.constitution.kill_switch:
            self.constitution.activate_kill_switch(
                reason="; ".join(reasons) or "governance failure"
            )

        decision = GovernanceResult(
            approved=approved,
            kill_switch=kill_switch,
            reasons=reasons,
            action=action,
            validation={
                "integrity": integrity,
                "action": action_validation,
                "self_modification": modification_validation,
                "resources": resource_validation,
            },
        )

        return decision
