from core.monitoring.audit_logger import AuditLogger
# core/audit_logger.py

import os
import json
import hashlib

from datetime import datetime


class AuditLogger:
    """
    Audit Logging System

    目的:
    - operation traceability
    - forensic analysis
    - incident investigation
    - survival accountability

    最重要:
    「何が起きたかを失わない」
    """

    def __init__(

        self,

        log_dir="logs/audit",
    ):

        self.log_dir = (
            log_dir
        )

        os.makedirs(

            self.log_dir,

            exist_ok=True,
        )

        self.current_log = (
            self._daily_log_path()
        )

    # =================================================
    # Daily Log Path
    # =================================================

    def _daily_log_path(
        self,
    ):

        day = datetime.utcnow().strftime(
            "%Y%m%d"
        )

        return os.path.join(

            self.log_dir,

            f"audit_{day}.jsonl"
        )

    # =================================================
    # Event Hash
    # =================================================

    def build_hash(
        self,
        payload,
    ):

        encoded = json.dumps(

            payload,

            sort_keys=True,

            ensure_ascii=False,
        ).encode("utf-8")

        return hashlib.sha256(
            encoded
        ).hexdigest()

    # =================================================
    # Base Event
    # =================================================

    def base_event(

        self,

        category,
        action,
        severity="INFO",
        metadata=None,
    ):

        event = {

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
                metadata or {},
        }

        event["event_hash"] = (
            self.build_hash(
                event
            )
        )

        return event

    # =================================================
    # Write Event
    # =================================================

    def write(
        self,
        event,
    ):

        self.current_log = (
            self._daily_log_path()
        )

        with open(

            self.current_log,

            "a",

            encoding="utf-8",
        ) as f:

            f.write(

                json.dumps(

                    event,

                    ensure_ascii=False,
                )

                + "\n"
            )

        print(
            f"[AUDIT] "
            f"{event['category']} "
            f"/ "
            f"{event['action']}"
        )

        return event

    # =================================================
    # Generic Event
    # =================================================

    def log(

        self,

        category,
        action,
        severity="INFO",
        metadata=None,
    ):

        event = self.base_event(

            category=category,

            action=action,

            severity=severity,

            metadata=metadata,
        )

        return self.write(
            event
        )

    # =================================================
    # Retraining
    # =================================================

    def retrain(

        self,

        result,
    ):

        status = result.get(
            "status",
            "UNKNOWN",
        )

        severity = "INFO"

        if status == "REJECTED":

            severity = "WARNING"

        elif status == "ERROR":

            severity = "ERROR"

        return self.log(

            category="MODEL",

            action=f"RETRAIN_{status}",

            severity=severity,

            metadata=result,
        )

    # =================================================
    # Shutdown
    # =================================================

    def shutdown(
        self,
        reason,
    ):

        return self.log(

            category="SYSTEM",

            action="SHUTDOWN",

            severity="CRITICAL",

            metadata={
                "reason":
                    reason
            },
        )

    # =================================================
    # Rollback
    # =================================================

    def rollback(

        self,

        backup,
    ):

        return self.log(

            category="MODEL",

            action="ROLLBACK",

            severity="WARNING",

            metadata={
                "backup":
                    backup
            },
        )

    # =================================================
    # Regime Change
    # =================================================

    def regime_transition(

        self,

        old,
        new,
        manual=False,
    ):

        severity = "INFO"

        dangerous = {

            "DRIFT",

            "COLLAPSE",
        }

        if new in dangerous:

            severity = "WARNING"

        return self.log(

            category="REGIME",

            action=f"{old}_TO_{new}",

            severity=severity,

            metadata={

                "old":
                    old,

                "new":
                    new,

                "manual":
                    manual,
            },
        )

    # =================================================
    # Alert Event
    # =================================================

    def alert(
        self,
        alert,
    ):

        return self.log(

            category="ALERT",

            action=alert.get(
                "title",
                "UNKNOWN",
            ),

            severity=alert.get(
                "level",
                "INFO",
            ),

            metadata=alert,
        )

    # =================================================
    # Simulation Event
    # =================================================

    def simulation(
        self,
        result,
    ):

        survival = result.get(
            "survival_score",
            1,
        )

        severity = "INFO"

        if survival < 0.40:

            severity = "WARNING"

        if survival < 0.25:

            severity = "CRITICAL"

        return self.log(

            category="SIMULATION",

            action="SURVIVAL_EVAL",

            severity=severity,

            metadata=result,
        )

    # =================================================
    # Exception
    # =================================================

    def exception(

        self,

        error,
        context=None,
    ):

        return self.log(

            category="EXCEPTION",

            action="SYSTEM_ERROR",

            severity="ERROR",

            metadata={

                "error":
                    str(error),

                "context":
                    context or {},
            },
        )

    # =================================================
    # Manual Override
    # =================================================

    def override(

        self,

        operator,
        action,
        metadata=None,
    ):

        return self.log(

            category="OVERRIDE",

            action=action,

            severity="WARNING",

            metadata={

                "operator":
                    operator,

                "details":
                    metadata or {},
            },
        )

    # =================================================
    # Load Recent Events
    # =================================================

    def recent_events(
        self,
        limit=100,
    ):

        if not os.path.exists(
            self.current_log
        ):

            return []

        events = []

        with open(

            self.current_log,

            "r",

            encoding="utf-8",
        ) as f:

            for line in f:

                try:

                    events.append(
                        json.loads(
                            line
                        )
                    )

                except:
                    pass

        return events[-limit:]

    # =================================================
    # Event Search
    # =================================================

    def search(

        self,

        category=None,
        severity=None,
        keyword=None,
    ):

        events = self.recent_events(
            limit=10000
        )

        results = []

        for event in events:

            if category:

                if (
                    event.get(
                        "category"
                    )
                    != category
                ):

                    continue

            if severity:

                if (
                    event.get(
                        "severity"
                    )
                    != severity
                ):

                    continue

            if keyword:

                raw = json.dumps(
                    event,
                    ensure_ascii=False,
                )

                if keyword not in raw:

                    continue

            results.append(
                event
            )

        return results

    # =================================================
    # Integrity Check
    # =================================================

    def verify_integrity(
        self,
    ):

        events = self.recent_events(
            limit=100000
        )

        broken = []

        for idx, event in enumerate(
            events
        ):

            original_hash = event.get(
                "event_hash"
            )

            temp = dict(event)

            temp.pop(
                "event_hash",
                None,
            )

            rebuilt = self.build_hash(
                temp
            )

            if rebuilt != original_hash:

                broken.append({

                    "index":
                        idx,

                    "event":
                        event,
                })

        return {

            "valid":
                len(broken) == 0,

            "broken":
                broken,
        }

    # =================================================
    # Diagnostics
    # =================================================

    def diagnostics(
        self,
    ):

        recent = self.recent_events(
            limit=20
        )

        severity_count = {}

        for event in recent:

            sev = event.get(
                "severity",
                "UNKNOWN",
            )

            severity_count[sev] = (

                severity_count.get(
                    sev,
                    0,
                )
                + 1
            )

        return {

            "log_dir":
                self.log_dir,

            "current_log":
                self.current_log,

            "recent_events":
                len(recent),

            "severity_distribution":
                severity_count,
        }


# =====================================================
# Example
# =====================================================

if __name__ == "__main__":

    audit = AuditLogger()

    audit.log(

        category="SYSTEM",

        action="BOOT",

        metadata={
            "version":
                "1.0"
        },
    )

    audit.regime_transition(

        old="NORMAL",

        new="DRIFT",
    )

    audit.shutdown(
        "max drawdown"
    )

    print(
        audit.diagnostics()
    )

    print(
        audit.verify_integrity()
    )