# core/resource_economy.py

import math
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


class ResourceEconomy:
    """
    Civilization Resource Economy

    目的:
    - sustainable resource allocation
    - reserve management
    - scarcity handling
    - long-term civilization endurance

    最重要:
    「文明の持久力を維持する」
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
        # core resources
        # =================================================

        self.compute_capacity = 1.0

        self.energy_capacity = 1.0

        self.storage_capacity = 1.0

        self.bandwidth_capacity = 1.0

        self.capital_reserve = 1.0

        self.risk_reserve = 1.0

        # =================================================
        # current usage
        # =================================================

        self.compute_usage = 0.0

        self.energy_usage = 0.0

        self.storage_usage = 0.0

        self.bandwidth_usage = 0.0

        self.capital_usage = 0.0

        self.risk_usage = 0.0

        # =================================================
        # reserve policies
        # =================================================

        self.minimum_reserve_ratio = (
            0.20
        )

        self.emergency_reserve_ratio = (
            0.35
        )

        self.expansion_ratio = (
            0.25
        )

        # =================================================
        # sustainability
        # =================================================

        self.sustainability_score = (
            1.0
        )

        self.collapse_risk = 0.0

        self.scarcity_mode = False

        self.lockdown_mode = False

        # =================================================
        # historical tracking
        # =================================================

        self.history = []

        self.forecasts = []

        self.last_update = None

    # =================================================
    # Allocate Resources
    # =================================================

    def allocate(

        self,

        compute=0.0,
        energy=0.0,
        storage=0.0,
        bandwidth=0.0,
        capital=0.0,
        risk=0.0,
    ):

        projected = {

            "compute":
                self.compute_usage
                + compute,

            "energy":
                self.energy_usage
                + energy,

            "storage":
                self.storage_usage
                + storage,

            "bandwidth":
                self.bandwidth_usage
                + bandwidth,

            "capital":
                self.capital_usage
                + capital,

            "risk":
                self.risk_usage
                + risk,
        }

        if not self.validate_capacity(
            projected
        ):

            self.alerts.emit(

                level="WARNING",

                title=
                    "RESOURCE_ALLOCATION_DENIED",

                message=(
                    "resource limits exceeded"
                ),
            )

            return {

                "success":
                    False,

                "reason":
                    "INSUFFICIENT_RESOURCES",
            }

        self.compute_usage += compute

        self.energy_usage += energy

        self.storage_usage += storage

        self.bandwidth_usage += bandwidth

        self.capital_usage += capital

        self.risk_usage += risk

        self.update_metrics()

        return {

            "success":
                True,

            "state":
                self.snapshot(),
        }

    # =================================================
    # Release Resources
    # =================================================

    def release(

        self,

        compute=0.0,
        energy=0.0,
        storage=0.0,
        bandwidth=0.0,
        capital=0.0,
        risk=0.0,
    ):

        self.compute_usage = max(
            0.0,
            self.compute_usage
            - compute
        )

        self.energy_usage = max(
            0.0,
            self.energy_usage
            - energy
        )

        self.storage_usage = max(
            0.0,
            self.storage_usage
            - storage
        )

        self.bandwidth_usage = max(
            0.0,
            self.bandwidth_usage
            - bandwidth
        )

        self.capital_usage = max(
            0.0,
            self.capital_usage
            - capital
        )

        self.risk_usage = max(
            0.0,
            self.risk_usage
            - risk
        )

        self.update_metrics()

        return self.snapshot()

    # =================================================
    # Validate Capacity
    # =================================================

    def validate_capacity(

        self,

        projected,
    ):

        reserve_limit = (
            1.0
            -
            self.minimum_reserve_ratio
        )

        checks = [

            projected["compute"]
            <= self.compute_capacity
            * reserve_limit,

            projected["energy"]
            <= self.energy_capacity
            * reserve_limit,

            projected["storage"]
            <= self.storage_capacity
            * reserve_limit,

            projected["bandwidth"]
            <= self.bandwidth_capacity
            * reserve_limit,

            projected["capital"]
            <= self.capital_reserve
            * reserve_limit,

            projected["risk"]
            <= self.risk_reserve
            * reserve_limit,
        ]

        return all(checks)

    # =================================================
    # Sustainability Score
    # =================================================

    def calculate_sustainability(
        self,
    ):

        usages = [

            self.compute_usage,

            self.energy_usage,

            self.storage_usage,

            self.bandwidth_usage,

            self.capital_usage,

            self.risk_usage,
        ]

        pressure = (
            statistics.mean(usages)
        )

        sustainability = max(

            0.0,

            1.0 - pressure
        )

        return round(
            sustainability,
            4
        )

    # =================================================
    # Collapse Risk
    # =================================================

    def calculate_collapse_risk(
        self,
    ):

        usages = [

            self.compute_usage,

            self.energy_usage,

            self.storage_usage,

            self.bandwidth_usage,

            self.capital_usage,

            self.risk_usage,
        ]

        peak = max(usages)

        reserve_penalty = (
            self.minimum_reserve_ratio
        )

        risk = min(

            1.0,

            peak
            +
            reserve_penalty
        )

        return round(
            risk,
            4
        )

    # =================================================
    # Forecast Exhaustion
    # =================================================

    def forecast_exhaustion(

        self,

        growth_rate=0.05,
        steps=12,
    ):

        forecasts = []

        compute = self.compute_usage

        capital = self.capital_usage

        for i in range(steps):

            compute *= (
                1.0 + growth_rate
            )

            capital *= (
                1.0 + growth_rate
            )

            exhaustion = max(
                compute,
                capital
            )

            forecasts.append({

                "step":
                    i + 1,

                "compute":
                    round(
                        compute,
                        4
                    ),

                "capital":
                    round(
                        capital,
                        4
                    ),

                "exhaustion":
                    round(
                        exhaustion,
                        4
                    ),
            })

        self.forecasts = forecasts

        return forecasts

    # =================================================
    # Scarcity Protocol
    # =================================================

    def activate_scarcity_protocol(
        self,
    ):

        self.scarcity_mode = True

        self.expansion_ratio = 0.0

        self.minimum_reserve_ratio = (
            0.35
        )

        self.alerts.emit(

            level="WARNING",

            title=
                "SCARCITY_PROTOCOL",

            message=(
                "resource scarcity mode activated"
            ),
        )

        self.audit.log(

            category=
                "RESOURCE_ECONOMY",

            action=
                "SCARCITY_MODE",

            severity="WARNING",

            metadata=self.snapshot(),
        )

        return self.snapshot()

    # =================================================
    # Emergency Lockdown
    # =================================================

    def activate_lockdown(
        self,
    ):

        self.lockdown_mode = True

        self.scarcity_mode = True

        self.expansion_ratio = 0.0

        self.minimum_reserve_ratio = (
            self.emergency_reserve_ratio
        )

        self.alerts.emit(

            level="CRITICAL",

            title=
                "RESOURCE_LOCKDOWN",

            message=(
                "civilization lockdown enabled"
            ),
        )

        self.audit.log(

            category=
                "RESOURCE_ECONOMY",

            action=
                "LOCKDOWN",

            severity="CRITICAL",

            metadata=self.snapshot(),
        )

        return self.snapshot()

    # =================================================
    # Optimize Economy
    # =================================================

    def optimize(
        self,
    ):

        sustainability = (
            self.calculate_sustainability()
        )

        if sustainability < 0.4:

            self.activate_scarcity_protocol()

        elif sustainability > 0.8:

            self.minimum_reserve_ratio = (
                max(
                    0.15,
                    self.minimum_reserve_ratio
                    - 0.02
                )
            )

        self.update_metrics()

        return {

            "sustainability":
                self.sustainability_score,

            "collapse_risk":
                self.collapse_risk,

            "reserve_ratio":
                self.minimum_reserve_ratio,
        }

    # =================================================
    # Update Metrics
    # =================================================

    def update_metrics(
        self,
    ):

        self.sustainability_score = (
            self.calculate_sustainability()
        )

        self.collapse_risk = (
            self.calculate_collapse_risk()
        )

        self.last_update = (
            datetime.utcnow()
            .isoformat()
        )

        snapshot = self.snapshot()

        self.history.append(
            snapshot
        )

        self.history = (
            self.history[-1000:]
        )

        # =================================================
        # alerts
        # =================================================

        if self.collapse_risk > 0.85:

            self.alerts.emit(

                level="CRITICAL",

                title=
                    "RESOURCE_COLLAPSE_RISK",

                message=(
                    "resource exhaustion danger"
                ),
            )

        # =================================================
        # persistence
        # =================================================

        self.db.save_snapshot(

            state_type=
                "RESOURCE_ECONOMY",

            payload=snapshot,
        )

    # =================================================
    # Snapshot
    # =================================================

    def snapshot(
        self,
    ):

        return {

            "timestamp":
                self.last_update,

            "compute_usage":
                round(
                    self.compute_usage,
                    4
                ),

            "energy_usage":
                round(
                    self.energy_usage,
                    4
                ),

            "storage_usage":
                round(
                    self.storage_usage,
                    4
                ),

            "bandwidth_usage":
                round(
                    self.bandwidth_usage,
                    4
                ),

            "capital_usage":
                round(
                    self.capital_usage,
                    4
                ),

            "risk_usage":
                round(
                    self.risk_usage,
                    4
                ),

            "sustainability_score":
                self.sustainability_score,

            "collapse_risk":
                self.collapse_risk,

            "scarcity_mode":
                self.scarcity_mode,

            "lockdown_mode":
                self.lockdown_mode,

            "reserve_ratio":
                self.minimum_reserve_ratio,
        }

    # =================================================
    # Diagnostics
    # =================================================

    def diagnostics(
        self,
    ):

        return {

            "snapshot":
                self.snapshot(),

            "history_size":
                len(
                    self.history
                ),

            "forecast_count":
                len(
                    self.forecasts
                ),
        }


# =====================================================
# Example
# =====================================================

if __name__ == "__main__":

    economy = (
        ResourceEconomy()
    )

    print(

        economy.allocate(

            compute=0.25,
            energy=0.20,
            storage=0.15,
            capital=0.30,
            risk=0.22,
        )
    )

    print(
        economy.snapshot()
    )

    print(

        economy.forecast_exhaustion(

            growth_rate=0.08,
            steps=10,
        )
    )

    print(
        economy.optimize()
    )

    print(
        economy.diagnostics()
    )