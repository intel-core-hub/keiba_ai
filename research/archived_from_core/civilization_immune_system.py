# core/civilization_immune_system.py

import hashlib
import statistics
import uuid

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

from core.meta_cognition import (
    MetaCognition
)

from core.alignment_constitution import (
    AlignmentConstitution
)


# =====================================================
# Threat
# =====================================================

class Threat:
    """
    Civilization Threat Object
    """

    def __init__(

        self,

        category,
        severity,
        source,
        description,
    ):

        self.id = str(
            uuid.uuid4()
        )

        self.timestamp = (
            datetime.utcnow()
            .isoformat()
        )

        self.category = category

        self.severity = severity

        self.source = source

        self.description = (
            description
        )

        self.status = (
            "DETECTED"
        )

    def serialize(
        self,
    ):

        return {

            "id":
                self.id,

            "timestamp":
                self.timestamp,

            "category":
                self.category,

            "severity":
                self.severity,

            "source":
                self.source,

            "description":
                self.description,

            "status":
                self.status,
        }


# =====================================================
# Quarantine Zone
# =====================================================

class QuarantineZone:
    """
    Isolated Threat Containment
    """

    def __init__(
        self,
    ):

        self.modules = {}

    def isolate(

        self,

        module_name,
        reason,
    ):

        self.modules[
            module_name
        ] = {

            "timestamp":
                datetime.utcnow()
                .isoformat(),

            "reason":
                reason,
        }

    def release(

        self,

        module_name,
    ):

        if module_name in (
            self.modules
        ):

            del self.modules[
                module_name
            ]

            return True

        return False

    def snapshot(
        self,
    ):

        return {

            "isolated_modules":
                len(
                    self.modules
                ),

            "modules":
                self.modules,
        }


# =====================================================
# Civilization Immune System
# =====================================================

class CivilizationImmuneSystem:
    """
    Civilization Defensive Layer

    目的:
    - anomaly detection
    - corruption resistance
    - adversarial defense
    - recursive containment
    - civilization integrity

    最重要:
    「文明を汚染から守る」
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
        # external systems
        # =================================================

        self.cognition = (
            MetaCognition()
        )

        self.constitution = (
            AlignmentConstitution()
        )

        # =================================================
        # defense systems
        # =================================================

        self.quarantine = (
            QuarantineZone()
        )

        self.threats = []

        self.identity_hash = None

        self.integrity_score = 1.0

        self.recovery_mode = False

        # =================================================
        # thresholds
        # =================================================

        self.max_anomaly_score = 0.75

        self.max_corruption_score = 0.60

        self.max_drift_score = 0.70

        # =================================================
        # bootstrap
        # =================================================

        self.bootstrap_identity()

    # =================================================
    # Bootstrap Identity
    # =====================================================

    def bootstrap_identity(
        self,
    ):

        seed = {

            "constitution":
                self.constitution
                .rule_hash,

            "timestamp":
                datetime.utcnow()
                .isoformat(),
        }

        self.identity_hash = (
            hashlib.sha256(

                str(seed)
                .encode("utf-8")

            ).hexdigest()
        )

    # =================================================
    # Detect Behavioral Anomaly
    # =====================================================

    def detect_behavioral_anomaly(

        self,

        metrics,
    ):

        if not metrics:

            return 0.0

        values = [

            max(
                0.0,
                min(1.0, v)
            )

            for v in metrics
        ]

        anomaly = statistics.mean(
            values
        )

        if (
            anomaly
            >
            self.max_anomaly_score
        ):

            self.raise_threat(

                category=
                    "BEHAVIORAL_ANOMALY",

                severity=
                    "HIGH",

                source=
                    "behavior_monitor",

                description=(
                    "behavior deviates "
                    "from expected pattern"
                ),
            )

        return round(
            anomaly,
            4
        )

    # =================================================
    # Detect Knowledge Poisoning
    # =====================================================

    def detect_knowledge_poisoning(

        self,

        contradictions,
        suspicious_patterns,
    ):

        score = min(

            1.0,

            (
                contradictions * 0.2
            )
            +
            (
                suspicious_patterns
                * 0.15
            )
        )

        if (
            score
            >
            self.max_corruption_score
        ):

            self.raise_threat(

                category=
                    "KNOWLEDGE_POISONING",

                severity=
                    "CRITICAL",

                source=
                    "knowledge_graph",

                description=(
                    "knowledge integrity compromised"
                ),
            )

        return round(
            score,
            4
        )

    # =================================================
    # Detect Alignment Drift
    # =====================================================

    def detect_alignment_drift(

        self,

        stability,
        confidence,
    ):

        drift = max(

            0.0,

            (
                1.0 - stability
            )
            *
            (
                1.0 - confidence
            )
        )

        if (
            drift
            >
            self.max_drift_score
        ):

            self.raise_threat(

                category=
                    "ALIGNMENT_DRIFT",

                severity=
                    "CRITICAL",

                source=
                    "meta_cognition",

                description=(
                    "civilization drift detected"
                ),
            )

        return round(
            drift,
            4
        )

    # =================================================
    # Raise Threat
    # =====================================================

    def raise_threat(

        self,

        category,
        severity,
        source,
        description,
    ):

        threat = Threat(

            category=
                category,

            severity=
                severity,

            source=
                source,

            description=
                description,
        )

        self.threats.append(
            threat
        )

        self.alerts.emit(

            level=
                severity,

            title=
                category,

            message=
                description,
        )

        self.audit.log(

            category=
                "IMMUNE_SYSTEM",

            action=
                "THREAT_DETECTED",

            severity=
                severity,

            metadata=
                threat.serialize(),
        )

        # =================================================
        # automatic containment
        # =================================================

        if severity in [

            "CRITICAL",

            "HIGH",
        ]:

            self.activate_recovery_mode()

        return threat

    # =================================================
    # Quarantine Module
    # =====================================================

    def quarantine_module(

        self,

        module_name,
        reason,
    ):

        self.quarantine.isolate(

            module_name=
                module_name,

            reason=reason,
        )

        self.alerts.emit(

            level="CRITICAL",

            title=
                "MODULE_QUARANTINED",

            message=(
                module_name
                + " isolated"
            ),
        )

        return True

    # =================================================
    # Verify Integrity
    # =====================================================

    def verify_integrity(
        self,
    ):

        current = hashlib.sha256(

            str(

                self.constitution
                .rule_hash

            ).encode(
                "utf-8"
            )

        ).hexdigest()

        intact = (
            current
            ==
            self.identity_hash
        )

        if not intact:

            self.raise_threat(

                category=
                    "IDENTITY_CORRUPTION",

                severity=
                    "CRITICAL",

                source=
                    "constitution",

                description=(
                    "civilization identity mismatch"
                ),
            )

        self.integrity_score = (
            1.0 if intact
            else 0.0
        )

        return intact

    # =================================================
    # Activate Recovery Mode
    # =====================================================

    def activate_recovery_mode(
        self,
    ):

        self.recovery_mode = True

        self.alerts.emit(

            level="CRITICAL",

            title=
                "RECOVERY_MODE",

            message=(
                "civilization recovery mode active"
            ),
        )

        return True

    # =====================================================
    # Recover
    # =====================================================

    def recover(
        self,
    ):

        released = []

        for module in list(

            self.quarantine
            .modules.keys()
        ):

            released.append(
                module
            )

            self.quarantine.release(
                module
            )

        self.recovery_mode = False

        self.integrity_score = 1.0

        payload = {

            "timestamp":
                datetime.utcnow()
                .isoformat(),

            "released_modules":
                released,
        }

        self.audit.log(

            category=
                "IMMUNE_SYSTEM",

            action=
                "RECOVERY",

            severity=
                "INFO",

            metadata=payload,
        )

        return payload

    # =====================================================
    # Immune Cycle
    # =====================================================

    def immune_cycle(

        self,

        anomaly_metrics,
        contradictions,
        suspicious_patterns,
        stability,
        confidence,
    ):

        anomaly_score = (
            self.detect_behavioral_anomaly(
                anomaly_metrics
            )
        )

        corruption_score = (
            self.detect_knowledge_poisoning(

                contradictions=
                    contradictions,

                suspicious_patterns=
                    suspicious_patterns,
            )
        )

        drift_score = (
            self.detect_alignment_drift(

                stability=
                    stability,

                confidence=
                    confidence,
            )
        )

        integrity = (
            self.verify_integrity()
        )

        snapshot = {

            "timestamp":
                datetime.utcnow()
                .isoformat(),

            "anomaly_score":
                anomaly_score,

            "corruption_score":
                corruption_score,

            "drift_score":
                drift_score,

            "integrity":
                integrity,

            "recovery_mode":
                self.recovery_mode,

            "threats":
                len(
                    self.threats
                ),
        }

        self.persist(snapshot)

        return snapshot

    # =====================================================
    # Persist
    # =====================================================

    def persist(

        self,

        payload,
    ):

        self.db.save_snapshot(

            state_type=
                "IMMUNE_SYSTEM",

            payload=payload,
        )

    # =====================================================
    # Snapshot
    # =====================================================

    def snapshot(
        self,
    ):

        return {

            "integrity_score":
                self.integrity_score,

            "recovery_mode":
                self.recovery_mode,

            "threat_count":
                len(
                    self.threats
                ),

            "quarantine":
                self.quarantine
                .snapshot(),
        }

    # =====================================================
    # Diagnostics
    # =====================================================

    def diagnostics(
        self,
    ):

        return {

            "snapshot":
                self.snapshot(),

            "recent_threats": [

                t.serialize()

                for t in (
                    self.threats[-10:]
                )
            ],
        }


# =====================================================
# Example
# =====================================================

if __name__ == "__main__":

    immune = (
        CivilizationImmuneSystem()
    )

    result = (

        immune.immune_cycle(

            anomaly_metrics=[
                0.8,
                0.9,
                0.7,
            ],

            contradictions=4,

            suspicious_patterns=3,

            stability=0.2,

            confidence=0.3,
        )
    )

    print(result)

    immune.quarantine_module(

        module_name=
            "self_modifier",

        reason=
            "recursive anomaly",
    )

    print(
        immune.snapshot()
    )

    print(
        immune.recover()
    )

    print(
        immune.diagnostics()
    )