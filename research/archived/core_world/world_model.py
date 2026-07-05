# core/world_model.py

import math
import statistics

from datetime import datetime

from infrastructure.database import (
    SurvivalDatabase
)

from core.audit_logger import (
    AuditLogger
)

from core.alert_manager import (
    AlertManager
)


class WorldModel:
    """
    Environmental Survival Intelligence

    目的:
    - external world awareness
    - macro regime understanding
    - systemic risk estimation
    - environmental adaptation

    最重要:
    「世界変化を理解する」
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
        # state memory
        # =================================================

        self.current_regime = (
            "UNKNOWN"
        )

        self.last_update = None

        self.world_state = {}

        self.history = []

        # =================================================
        # environmental signals
        # =================================================

        self.market_volatility = 0.0

        self.liquidity_risk = 0.0

        self.sentiment_score = 0.0

        self.systemic_risk = 0.0

        self.collapse_probability = 0.0

        self.stress_index = 0.0

        self.adaptation_pressure = 0.0

    # =================================================
    # Update World State
    # =================================================

    def update(

        self,

        market_data=None,
        sentiment_data=None,
        system_data=None,
    ):

        market_data = (
            market_data or {}
        )

        sentiment_data = (
            sentiment_data or {}
        )

        system_data = (
            system_data or {}
        )

        # =================================================
        # compute metrics
        # =================================================

        self.market_volatility = (
            self.compute_volatility(
                market_data
            )
        )

        self.liquidity_risk = (
            self.compute_liquidity_risk(
                market_data
            )
        )

        self.sentiment_score = (
            self.compute_sentiment(
                sentiment_data
            )
        )

        self.systemic_risk = (
            self.compute_systemic_risk(
                system_data
            )
        )

        self.stress_index = (
            self.compute_stress()
        )

        self.collapse_probability = (
            self.compute_collapse_probability()
        )

        self.adaptation_pressure = (
            self.compute_adaptation_pressure()
        )

        # =================================================
        # regime classification
        # =================================================

        self.current_regime = (
            self.detect_regime()
        )

        # =================================================
        # build state
        # =================================================

        self.world_state = {

            "timestamp":
                datetime.utcnow()
                .isoformat(),

            "regime":
                self.current_regime,

            "market_volatility":
                self.market_volatility,

            "liquidity_risk":
                self.liquidity_risk,

            "sentiment_score":
                self.sentiment_score,

            "systemic_risk":
                self.systemic_risk,

            "stress_index":
                self.stress_index,

            "collapse_probability":
                self.collapse_probability,

            "adaptation_pressure":
                self.adaptation_pressure,
        }

        self.last_update = (
            self.world_state[
                "timestamp"
            ]
        )

        self.history.append(
            self.world_state
        )

        self.history = (
            self.history[-1000:]
        )

        # =================================================
        # persistence
        # =================================================

        self.db.save_snapshot(

            state_type="WORLD_MODEL",

            payload=self.world_state,
        )

        # =================================================
        # alerting
        # =================================================

        self.evaluate_alerts()

        # =================================================
        # audit
        # =================================================

        self.audit.log(

            category="WORLD_MODEL",

            action="UPDATE",

            severity="INFO",

            metadata=self.world_state,
        )

        return self.world_state

    # =================================================
    # Volatility
    # =================================================

    def compute_volatility(

        self,

        market_data,
    ):

        prices = market_data.get(
            "prices",
            []
        )

        if len(prices) < 2:
            return 0.0

        returns = []

        for i in range(
            1,
            len(prices)
        ):

            prev = prices[i - 1]

            curr = prices[i]

            if prev == 0:
                continue

            returns.append(
                (curr - prev) / prev
            )

        if len(returns) < 2:
            return 0.0

        return abs(
            statistics.stdev(
                returns
            )
        )

    # =================================================
    # Liquidity Risk
    # =================================================

    def compute_liquidity_risk(

        self,

        market_data,
    ):

        volume = market_data.get(
            "volume",
            0
        )

        spread = market_data.get(
            "spread",
            0
        )

        if volume <= 0:
            return 1.0

        risk = spread / (
            math.log(
                volume + 1
            )
        )

        return min(
            1.0,
            abs(risk)
        )

    # =================================================
    # Sentiment
    # =================================================

    def compute_sentiment(

        self,

        sentiment_data,
    ):

        positive = (
            sentiment_data.get(
                "positive",
                0
            )
        )

        negative = (
            sentiment_data.get(
                "negative",
                0
            )
        )

        neutral = (
            sentiment_data.get(
                "neutral",
                1
            )
        )

        total = (
            positive +
            negative +
            neutral
        )

        if total == 0:
            return 0.0

        score = (
            positive - negative
        ) / total

        return max(
            -1.0,
            min(1.0, score)
        )

    # =================================================
    # Systemic Risk
    # =================================================

    def compute_systemic_risk(

        self,

        system_data,
    ):

        cpu = system_data.get(
            "cpu_usage",
            0
        )

        memory = system_data.get(
            "memory_usage",
            0
        )

        failures = system_data.get(
            "failures",
            0
        )

        latency = system_data.get(
            "latency",
            0
        )

        risk = (

            cpu * 0.25 +

            memory * 0.25 +

            failures * 0.30 +

            latency * 0.20
        )

        return min(
            1.0,
            risk
        )

    # =================================================
    # Stress
    # =================================================

    def compute_stress(
        self,
    ):

        stress = (

            self.market_volatility * 0.30 +

            self.liquidity_risk * 0.20 +

            abs(
                self.sentiment_score
            ) * 0.10 +

            self.systemic_risk * 0.40
        )

        return min(
            1.0,
            stress
        )

    # =================================================
    # Collapse Probability
    # =================================================

    def compute_collapse_probability(
        self,
    ):

        collapse = (

            self.stress_index * 0.5 +

            self.systemic_risk * 0.3 +

            self.liquidity_risk * 0.2
        )

        return min(
            1.0,
            collapse
        )

    # =================================================
    # Adaptation Pressure
    # =================================================

    def compute_adaptation_pressure(
        self,
    ):

        pressure = (

            self.market_volatility * 0.4 +

            self.collapse_probability * 0.4 +

            abs(
                self.sentiment_score
            ) * 0.2
        )

        return min(
            1.0,
            pressure
        )

    # =================================================
    # Regime Detection
    # =================================================

    def detect_regime(
        self,
    ):

        if (
            self.collapse_probability
            > 0.85
        ):

            return "COLLAPSE"

        if (
            self.stress_index
            > 0.70
        ):

            return "CRISIS"

        if (
            self.market_volatility
            > 0.08
        ):

            return "VOLATILE"

        if (
            self.sentiment_score
            > 0.4
        ):

            return "OPTIMISTIC"

        if (
            self.sentiment_score
            < -0.4
        ):

            return "PANIC"

        return "STABLE"

    # =================================================
    # Alerting
    # =================================================

    def evaluate_alerts(
        self,
    ):

        if (
            self.collapse_probability
            > 0.85
        ):

            self.alerts.emit(

                level="CRITICAL",

                title=(
                    "SYSTEMIC COLLAPSE RISK"
                ),

                message=(
                    "collapse probability "
                    "exceeded threshold"
                ),
            )

        elif (
            self.stress_index
            > 0.70
        ):

            self.alerts.emit(

                level="WARNING",

                title=(
                    "HIGH STRESS"
                ),

                message=(
                    "environmental stress "
                    "elevated"
                ),
            )

    # =================================================
    # Summary
    # =================================================

    def summary(
        self,
    ):

        return {

            "regime":
                self.current_regime,

            "stress_index":
                self.stress_index,

            "collapse_probability":
                self.collapse_probability,

            "adaptation_pressure":
                self.adaptation_pressure,

            "last_update":
                self.last_update,
        }

    # =================================================
    # Diagnostics
    # =================================================

    def diagnostics(
        self,
    ):

        return {

            "summary":
                self.summary(),

            "world_state":
                self.world_state,

            "history_size":
                len(
                    self.history
                ),
        }


# =====================================================
# Example
# =====================================================

if __name__ == "__main__":

    world = WorldModel()

    market_data = {

        "prices": [

            100,
            102,
            98,
            105,
            95,
            110,
        ],

        "volume":
            2500000,

        "spread":
            0.02,
    }

    sentiment_data = {

        "positive":
            120,

        "negative":
            80,

        "neutral":
            40,
    }

    system_data = {

        "cpu_usage":
            0.65,

        "memory_usage":
            0.58,

        "failures":
            0.20,

        "latency":
            0.30,
    }

    state = world.update(

        market_data=
            market_data,

        sentiment_data=
            sentiment_data,

        system_data=
            system_data,
    )

    print(state)

    print(
        world.summary()
    )

    print(
        world.diagnostics()
    )