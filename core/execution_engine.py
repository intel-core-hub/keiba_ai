from core.execution.execution_engine import ExecutionEngine
# core/execution_engine.py

import uuid
import time
import statistics

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

from core.survival_policy import (
    SurvivalPolicy
)

from core.self_modifier import (
    SelfModifier
)


# =====================================================
# Action
# =====================================================

class Action:
    """
    Civilization Action Unit
    """

    def __init__(

        self,

        name,
        category,
        priority=0.5,
        cost=0.1,
        risk=0.1,
        payload=None,
    ):

        self.id = str(
            uuid.uuid4()
        )

        self.timestamp = (
            datetime.utcnow()
            .isoformat()
        )

        self.name = name

        self.category = category

        self.priority = priority

        self.cost = cost

        self.risk = risk

        self.payload = (
            payload or {}
        )

        self.status = (
            "PENDING"
        )

        self.result = None

    def serialize(
        self,
    ):

        return {

            "id":
                self.id,

            "timestamp":
                self.timestamp,

            "name":
                self.name,

            "category":
                self.category,

            "priority":
                self.priority,

            "cost":
                self.cost,

            "risk":
                self.risk,

            "payload":
                self.payload,

            "status":
                self.status,

            "result":
                self.result,
        }


# =====================================================
# Execution Plan
# =====================================================

class ExecutionPlan:
    """
    Multi-Action Survival Plan
    """

    def __init__(
        self,
    ):

        self.id = str(
            uuid.uuid4()
        )

        self.timestamp = (
            datetime.utcnow()
            .isoformat()
        )

        self.actions = []

        self.status = (
            "CREATED"
        )

        self.score = 0.0

    def add_action(

        self,

        action,
    ):

        self.actions.append(
            action
        )

    def total_cost(
        self,
    ):

        return round(

            sum(

                a.cost

                for a in (
                    self.actions
                )
            ),

            4
        )

    def total_risk(
        self,
    ):

        return round(

            sum(

                a.risk

                for a in (
                    self.actions
                )
            ),

            4
        )

    def serialize(
        self,
    ):

        return {

            "id":
                self.id,

            "timestamp":
                self.timestamp,

            "status":
                self.status,

            "score":
                self.score,

            "total_cost":
                self.total_cost(),

            "total_risk":
                self.total_risk(),

            "actions": [

                a.serialize()

                for a in (
                    self.actions
                )
            ],
        }


# =====================================================
# Resource Allocator
# =====================================================

class ResourceAllocator:
    """
    Resource Optimization Layer
    """

    def __init__(
        self,
    ):

        self.total_compute = 1.0

        self.total_capital = 1.0

        self.total_bandwidth = 1.0

        self.reserved_ratio = 0.2

    def allocate(

        self,

        plan,
    ):

        required = (
            plan.total_cost()
        )

        available = (

            self.total_compute
            *
            (1.0 - self.reserved_ratio)
        )

        approved = (
            required <= available
        )

        return {

            "required":
                required,

            "available":
                round(
                    available,
                    4
                ),

            "approved":
                approved,
        }


# =====================================================
# Safety Validator
# =====================================================

class SafetyValidator:
    """
    Safety Constraints
    """

    def __init__(
        self,
    ):

        self.max_risk = 0.8

        self.max_cost = 0.9

        self.blocked_actions = [

            "UNBOUNDED_EXPANSION",

            "DISABLE_SAFETY",

            "REMOVE_LIMITS",
        ]

    def validate(

        self,

        plan,
    ):

        if (
            plan.total_risk()
            > self.max_risk
        ):

            return False

        if (
            plan.total_cost()
            > self.max_cost
        ):

            return False

        for action in (
            plan.actions
        ):

            if (
                action.name
                in self.blocked_actions
            ):

                return False

        return True


# =====================================================
# Execution Engine
# =====================================================

class ExecutionEngine:
    """
    Civilization Execution Core

    目的:
    - action execution
    - resource deployment
    - adaptive intervention
    - emergency response

    最重要:
    「思考を現実へ反映する」
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

        self.policy = (
            SurvivalPolicy()
        )

        self.self_modifier = (
            SelfModifier()
        )

        # =================================================
        # execution subsystems
        # =================================================

        self.resources = (
            ResourceAllocator()
        )

        self.safety = (
            SafetyValidator()
        )

        # =================================================
        # state
        # =================================================

        self.execution_history = []

        self.rollback_stack = []

        self.last_plan = None

        self.running = False

        # =================================================
        # metrics
        # =================================================

        self.total_executions = 0

        self.failed_executions = 0

        self.success_rate = 1.0

    # =================================================
    # Generate Plan
    # =====================================================

    def generate_plan(

        self,

        future,
    ):

        plan = ExecutionPlan()

        state = future.get(
            "state",
            {}
        )

        collapse = state.get(
            "collapse_probability",
            0.0
        )

        stress = state.get(
            "stress_index",
            0.0
        )

        volatility = state.get(
            "market_volatility",
            0.0
        )

        # =================================================
        # defensive survival
        # =================================================

        if collapse > 0.7:

            plan.add_action(

                Action(

                    name=
                        "REDUCE_EXPOSURE",

                    category=
                        "RISK",

                    priority=0.95,

                    cost=0.2,

                    risk=0.05,
                )
            )

            plan.add_action(

                Action(

                    name=
                        "ENABLE_LOCKDOWN",

                    category=
                        "EMERGENCY",

                    priority=1.0,

                    cost=0.1,

                    risk=0.02,
                )
            )

        # =================================================
        # stress adaptation
        # =================================================

        if stress > 0.6:

            plan.add_action(

                Action(

                    name=
                        "SCALE_REDUNDANCY",

                    category=
                        "INFRA",

                    priority=0.8,

                    cost=0.25,

                    risk=0.10,
                )
            )

        # =================================================
        # volatility exploitation
        # =================================================

        if volatility > 0.5:

            plan.add_action(

                Action(

                    name=
                        "INCREASE_OPTIONALITY",

                    category=
                        "STRATEGY",

                    priority=0.7,

                    cost=0.15,

                    risk=0.15,
                )
            )

        # =================================================
        # default survival
        # =================================================

        if not plan.actions:

            plan.add_action(

                Action(

                    name=
                        "MAINTAIN_STABILITY",

                    category=
                        "BASELINE",

                    priority=0.5,

                    cost=0.05,

                    risk=0.01,
                )
            )

        # =================================================
        # score
        # =================================================

        priorities = [

            a.priority

            for a in (
                plan.actions
            )
        ]

        plan.score = round(

            statistics.mean(
                priorities
            ),

            4
        )

        self.last_plan = (
            plan
        )

        return plan

    # =================================================
    # Validate Plan
    # =====================================================

    def validate_plan(

        self,

        plan,
    ):

        safety_ok = (
            self.safety.validate(
                plan
            )
        )

        allocation = (
            self.resources.allocate(
                plan
            )
        )

        approved = (

            safety_ok
            and
            allocation[
                "approved"
            ]
        )

        return {

            "approved":
                approved,

            "safety":
                safety_ok,

            "resources":
                allocation,
        }

    # =================================================
    # Execute Plan
    # =====================================================

    def execute_plan(

        self,

        plan,
    ):

        validation = (
            self.validate_plan(
                plan
            )
        )

        if not validation[
            "approved"
        ]:

            self.failed_executions += 1

            self.update_success_rate()

            self.alerts.emit(

                level="WARNING",

                title=
                    "PLAN REJECTED",

                message=(
                    "execution plan rejected"
                ),
            )

            return {

                "success":
                    False,

                "reason":
                    "VALIDATION_FAILED",

                "validation":
                    validation,
            }

        # =================================================
        # save rollback point
        # =================================================

        self.rollback_stack.append(
            plan.serialize()
        )

        # =================================================
        # execute actions
        # =================================================

        results = []

        for action in (
            plan.actions
        ):

            result = (
                self.execute_action(
                    action
                )
            )

            results.append(
                result
            )

        # =================================================
        # metrics
        # =================================================

        self.total_executions += 1

        self.update_success_rate()

        payload = {

            "timestamp":
                datetime.utcnow()
                .isoformat(),

            "plan":
                plan.serialize(),

            "results":
                results,
        }

        self.execution_history.append(
            payload
        )

        self.execution_history = (
            self.execution_history[
                -1000:
            ]
        )

        # =================================================
        # persistence
        # =================================================

        self.db.save_snapshot(

            state_type=
                "EXECUTION",

            payload=payload,
        )

        self.audit.log(

            category=
                "EXECUTION_ENGINE",

            action=
                "EXECUTE_PLAN",

            severity="INFO",

            metadata=payload,
        )

        return {

            "success":
                True,

            "results":
                results,
        }

    # =================================================
    # Execute Action
    # =====================================================

    def execute_action(

        self,

        action,
    ):

        action.status = (
            "RUNNING"
        )

        time.sleep(0.05)

        # =================================================
        # simulated execution
        # =================================================

        action.status = (
            "COMPLETED"
        )

        action.result = {

            "success":
                True,

            "timestamp":
                datetime.utcnow()
                .isoformat(),
        }

        return action.serialize()

    # =================================================
    # Rollback
    # =====================================================

    def rollback(
        self,
    ):

        if not self.rollback_stack:

            return False

        previous = (
            self.rollback_stack.pop()
        )

        self.alerts.emit(

            level="WARNING",

            title=
                "ROLLBACK",

            message=(
                "execution rollback triggered"
            ),
        )

        self.audit.log(

            category=
                "EXECUTION_ENGINE",

            action=
                "ROLLBACK",

            severity="ERROR",

            metadata=previous,
        )

        return True

    # =================================================
    # Emergency Protocol
    # =====================================================

    def emergency_protocol(

        self,

        reason,
    ):

        emergency_plan = (
            ExecutionPlan()
        )

        emergency_plan.add_action(

            Action(

                name=
                    "ENTER_SURVIVAL_MODE",

                category=
                    "EMERGENCY",

                priority=1.0,

                cost=0.1,

                risk=0.01,
            )
        )
        emergency_plan.add_action(

            Action(

                name=
                    "FREEZE_EXPANSION",

                category=
                    "EMERGENCY",

                priority=0.95,

                cost=0.05,

                risk=0.01,
            )
        )

        self.alerts.emit(

            level="CRITICAL",

            title=
                "EMERGENCY_PROTOCOL",

            message=reason,
        )

        return self.execute_plan(
            emergency_plan
        )

    # =================================================
    # Optimize Resources
    # =====================================================

    def optimize_resources(
        self,
    ):

        if self.success_rate < 0.5:

            self.resources.reserved_ratio = (
                min(
                    0.5,
                    self.resources
                    .reserved_ratio
                    + 0.05
                )
            )

        else:

            self.resources.reserved_ratio = (
                max(
                    0.1,
                    self.resources
                    .reserved_ratio
                    - 0.02
                )
            )

        return {

            "reserved_ratio":
                round(
                    self.resources
                    .reserved_ratio,
                    4
                )
        }

    # =================================================
    # Success Rate
    # =====================================================

    def update_success_rate(
        self,
    ):

        if (
            self.total_executions
            == 0
        ):

            self.success_rate = 1.0

            return

        self.success_rate = round(

            1.0
            -
            (
                self.failed_executions
                /
                self.total_executions
            ),

            4
        )

    # =================================================
    # Diagnostics
    # =====================================================

    def diagnostics(
        self,
    ):

        return {

            "executions":
                self.total_executions,

            "failed":
                self.failed_executions,

            "success_rate":
                self.success_rate,

            "history":
                len(
                    self.execution_history
                ),

            "last_plan":
                (
                    self.last_plan
                    .serialize()
                    if self.last_plan
                    else None
                ),
        }


# =====================================================
# Example
# =====================================================

if __name__ == "__main__":

    engine = (
        ExecutionEngine()
    )

    future = {

        "state": {

            "collapse_probability":
                0.74,

            "stress_index":
                0.66,

            "market_volatility":
                0.71,
        }
    }

    plan = (
        engine.generate_plan(
            future
        )
    )

    print(
        plan.serialize()
    )

    validation = (
        engine.validate_plan(
            plan
        )
    )

    print(validation)

    result = (
        engine.execute_plan(
            plan
        )
    )

    print(result)

    print(
        engine.optimize_resources()
    )

    print(
        engine.diagnostics()
    )
