# core/decision_logger.py

import os
import json
import hashlib
import uuid
import traceback

from datetime import datetime


class DecisionLogger:
    """
    Decision Trace Logger

    目的:
    - 意思決定追跡
    - explainability
    - debugging
    - survival audit
    - replay analysis

    最重要思想:
    「なぜその判断をしたか」
    を失わない
    """

    def __init__(
        self,
        log_dir="logs",
    ):

        self.log_dir = log_dir

        os.makedirs(
            self.log_dir,
            exist_ok=True,
        )

        # -----------------------------------------
        # files
        # -----------------------------------------

        self.decision_log = os.path.join(
            log_dir,
            "decision_log.jsonl",
        )

        self.error_log = os.path.join(
            log_dir,
            "error_log.jsonl",
        )

        self.state_log = os.path.join(
            log_dir,
            "state_log.jsonl",
        )

        self._last_hash_by_path = {
            self.decision_log: self._load_last_hash(self.decision_log),
            self.error_log: self._load_last_hash(self.error_log),
            self.state_log: self._load_last_hash(self.state_log),
        }

    # =================================================
    # Timestamp
    # =================================================

    def timestamp(self):

        return datetime.utcnow().isoformat()

    # =================================================
    # UUID
    # =================================================

    def decision_id(self):

        return str(uuid.uuid4())

    # =================================================
    # Hash Chain
    # =================================================

    def _load_last_hash(self, path):
        if not os.path.exists(path):
            return "0" * 64

        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = [line.strip() for line in f.readlines() if line.strip()]

            if not lines:
                return "0" * 64

            last_record = json.loads(lines[-1])
            return str(last_record.get("entry_hash") or "0" * 64)
        except Exception:
            return "0" * 64

    # =================================================
    # Safe Write
    # =================================================

    def append_jsonl(
        self,
        path,
        data,
    ):

        record = dict(data)
        previous_hash = self._last_hash_by_path.get(path, "0" * 64)
        record["previous_hash"] = previous_hash

        canonical_payload = json.dumps(
            record,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        entry_hash = hashlib.sha256(
            canonical_payload.encode("utf-8")
        ).hexdigest()
        record["entry_hash"] = entry_hash

        with open(
            path,
            "a",
            encoding="utf-8",
        ) as f:

            f.write(
                json.dumps(
                    record,
                    ensure_ascii=False,
                )
                + "\n"
            )

        self._last_hash_by_path[path] = entry_hash

    # =================================================
    # Decision
    # =================================================

    def log_decision(

        self,

        race_id,
        selection,

        probability,
        odds,
        edge,

        decision,

        # -----------------------------------------
        # state layers
        # -----------------------------------------

        meta_state=None,

        regime=None,

        capital_mode=None,

        bankroll=None,

        # -----------------------------------------
        # sizing
        # -----------------------------------------

        base_size=None,

        adjusted_size=None,

        final_size=None,

        # -----------------------------------------
        # skip
        # -----------------------------------------

        skipped=False,

        skip_reason=None,

        # -----------------------------------------
        # calibration
        # -----------------------------------------

        brier_score=None,

        ece=None,

        reliability=None,

        drift_score=None,

        # -----------------------------------------
        # phase2 metrics
        # -----------------------------------------

        expected_value=None,

        market_probability=None,

        calibrated_probability=None,

        uncertainty_score=None,

        edge_quality=None,

        risk_status=None,

        uncertainty_multiplier=None,

        global_exposure_multiplier=None,

        defensive_mode=None,

        rolling_uncertainty=None,

        uncertainty_deteriorating=None,

        no_bet_reason=None,

        # -----------------------------------------
        # bet type metadata
        # -----------------------------------------

        bet_type=None,

        legs=None,

        ordered=None,

        shadow_only=None,

        production_candidate=None,

        max_combinations_per_race=None,

        max_race_exposure_share=None,

        source=None,

        # -----------------------------------------
        # features
        # -----------------------------------------

        features=None,
    ):

        log = {

            # =================================================
            # identity
            # =================================================

            "timestamp":
                self.timestamp(),

            "decision_id":
                self.decision_id(),

            "race_id":
                race_id,

            "selection":
                selection,

            # =================================================
            # prediction
            # =================================================

            "probability":
                round(
                    float(probability),
                    6,
                ),

            "odds":
                round(
                    float(odds),
                    4,
                ),

            "edge":
                round(
                    float(edge),
                    6,
                ),

            # =================================================
            # decision
            # =================================================

            "decision":
                decision,

            "skipped":
                skipped,

            "skip_reason":
                skip_reason,

            # =================================================
            # sizing
            # =================================================

            "base_size":
                self.safe_number(
                    base_size
                ),

            "adjusted_size":
                self.safe_number(
                    adjusted_size
                ),

            "final_size":
                self.safe_number(
                    final_size
                ),

            # =================================================
            # states
            # =================================================

            "meta_state":
                meta_state,

            "regime":
                regime,

            "capital_mode":
                capital_mode,

            # =================================================
            # bankroll
            # =================================================

            "bankroll":
                self.safe_number(
                    bankroll
                ),

            # =================================================
            # calibration
            # =================================================

            "brier_score":
                self.safe_number(
                    brier_score
                ),

            "ece":
                self.safe_number(
                    ece
                ),

            "reliability":
                self.safe_number(
                    reliability
                ),

            "drift_score":
                self.safe_number(
                    drift_score
                ),

            # =================================================
            # phase2 metrics
            # =================================================

            "expected_value":
                self.safe_number(
                    expected_value
                ),

            "market_probability":
                self.safe_number(
                    market_probability
                ),

            "calibrated_probability":
                self.safe_number(
                    calibrated_probability
                ),

            "uncertainty_score":
                self.safe_number(
                    uncertainty_score
                ),

            "edge_quality":
                self.safe_number(
                    edge_quality
                ),

            "uncertainty_multiplier":
                self.safe_number(
                    uncertainty_multiplier
                    if uncertainty_multiplier is not None
                    else (risk_status or {}).get("uncertainty_multiplier")
                ),

            "global_exposure_multiplier":
                self.safe_number(
                    global_exposure_multiplier
                    if global_exposure_multiplier is not None
                    else (risk_status or {}).get("global_exposure_multiplier")
                ),

            "defensive_mode":
                defensive_mode
                if defensive_mode is not None
                else (risk_status or {}).get("defensive_mode"),

            "rolling_uncertainty":
                self.safe_number(
                    rolling_uncertainty
                    if rolling_uncertainty is not None
                    else (risk_status or {}).get("rolling_uncertainty")
                ),

            "uncertainty_deteriorating":
                uncertainty_deteriorating
                if uncertainty_deteriorating is not None
                else (risk_status or {}).get("deteriorating"),

            "no_bet_reason":
                no_bet_reason,

            "bet_type":
                bet_type or "win",

            "legs":
                legs,

            "ordered":
                ordered if ordered is not None else False,

            "shadow_only":
                shadow_only if shadow_only is not None else False,

            "production_candidate":
                production_candidate if production_candidate is not None else True,

            "max_combinations_per_race":
                max_combinations_per_race,

            "max_race_exposure_share":
                self.safe_number(max_race_exposure_share),

            "source":
                source,

            # =================================================
            # features
            # =================================================

            "features":
                features,
        }

        self.append_jsonl(
            self.decision_log,
            log,
        )

        return log

    # =================================================
    # Outcome
    # =================================================

    def log_outcome(

        self,

        race_id,
        selection,

        hit,
        profit,

        bankroll_after,

        drawdown=None,

        survival_score=None,
    ):

        log = {

            "timestamp":
                self.timestamp(),

            "type":
                "OUTCOME",

            "race_id":
                race_id,

            "selection":
                selection,

            "hit":
                bool(hit),

            "profit":
                round(
                    float(profit),
                    4,
                ),

            "bankroll_after":
                round(
                    float(bankroll_after),
                    4,
                ),

            "drawdown":
                self.safe_number(
                    drawdown
                ),

            "survival_score":
                self.safe_number(
                    survival_score
                ),
        }

        self.append_jsonl(
            self.decision_log,
            log,
        )

        return log

    # =================================================
    # State Transition
    # =================================================

    def log_state_transition(

        self,

        component,

        old_state,

        new_state,

        reason=None,
    ):

        log = {

            "timestamp":
                self.timestamp(),

            "component":
                component,

            "old_state":
                old_state,

            "new_state":
                new_state,

            "reason":
                reason,
        }

        self.append_jsonl(
            self.state_log,
            log,
        )

        return log

    # =================================================
    # Error
    # =================================================

    def log_error(

        self,

        component,

        error,

        context=None,
    ):

        log = {

            "timestamp":
                self.timestamp(),

            "component":
                component,

            "error":
                str(error),

            "traceback":
                traceback.format_exc(),

            "context":
                context,
        }

        self.append_jsonl(
            self.error_log,
            log,
        )

        return log

    # =================================================
    # Skip
    # =================================================

    def log_skip(

        self,

        race_id,
        selection,

        reason,

        probability=None,
        odds=None,
        edge=None,
    ):

        return self.log_decision(

            race_id=race_id,

            selection=selection,

            probability=(
                probability or 0
            ),

            odds=(
                odds or 0
            ),

            edge=(
                edge or 0
            ),

            decision="SKIP",

            skipped=True,

            skip_reason=reason,
        )

    # =================================================
    # Shutdown
    # =================================================

    def log_shutdown(

        self,

        trigger,

        reason,

        diagnostics=None,
    ):

        log = {

            "timestamp":
                self.timestamp(),

            "type":
                "SHUTDOWN",

            "trigger":
                trigger,

            "reason":
                reason,

            "diagnostics":
                diagnostics,
        }

        self.append_jsonl(
            self.state_log,
            log,
        )

        return log

    # =================================================
    # Safe Number
    # =================================================

    def safe_number(
        self,
        value,
    ):

        if value is None:
            return None

        try:

            return round(
                float(value),
                6,
            )

        except:
            return None

    # =================================================
    # Replay Loader
    # =================================================

    def load_decisions(
        self,
    ):

        if not os.path.exists(
            self.decision_log
        ):

            return []

        decisions = []

        with open(
            self.decision_log,
            "r",
            encoding="utf-8",
        ) as f:

            for line in f:

                try:

                    decisions.append(
                        json.loads(line)
                    )

                except:
                    continue

        return decisions

    # =================================================
    # Summary
    # =================================================

    def summary(
        self,
    ):

        decisions = (
            self.load_decisions()
        )

        if len(decisions) == 0:

            return {
                "records": 0
            }

        executed = [

            d for d in decisions

            if d.get("decision")
            == "BET"
        ]

        skipped = [

            d for d in decisions

            if d.get("skipped")
        ]

        outcomes = [

            d for d in decisions

            if d.get("type")
            == "OUTCOME"
        ]

        profits = [

            d["profit"]

            for d in outcomes

            if "profit" in d
        ]

        total_profit = sum(
            profits
        )

        return {

            "records":
                len(decisions),

            "executed":
                len(executed),

            "skipped":
                len(skipped),

            "outcomes":
                len(outcomes),

            "total_profit":
                round(
                    total_profit,
                    4,
                ),

            "avg_profit":
                round(

                    total_profit
                    / max(
                        len(outcomes),
                        1,
                    ),

                    4,
                ),
        }

    # =================================================
    # Skip Analysis
    # =================================================

    def skip_analysis(
        self,
    ):

        decisions = (
            self.load_decisions()
        )

        skips = {}

        for d in decisions:

            if not d.get("skipped"):
                continue

            reason = d.get(
                "skip_reason",
                "UNKNOWN",
            )

            skips[reason] = (
                skips.get(reason, 0)
                + 1
            )

        return skips

    # =================================================
    # Most Dangerous Zone
    # =================================================

    def dangerous_patterns(
        self,
    ):

        decisions = (
            self.load_decisions()
        )

        risky = []

        for d in decisions:

            edge = d.get(
                "edge",
                0,
            )

            probability = d.get(
                "probability",
                0,
            )

            odds = d.get(
                "odds",
                0,
            )

            if (

                probability > 0.7

                and edge < 0.02

                and odds < 2.0

            ):

                risky.append(d)

        return risky[-20:]


# =====================================================
# Example
# =====================================================

if __name__ == "__main__":

    logger = DecisionLogger()

    logger.log_decision(

        race_id="TOKYO_11R",

        selection="Horse_A",

        probability=0.42,

        odds=4.5,

        edge=0.19,

        decision="BET",

        meta_state="NORMAL",

        regime="NORMAL",

        capital_mode="NORMAL",

        bankroll=20000,

        base_size=400,

        adjusted_size=300,

        final_size=250,

        brier_score=0.18,

        ece=0.03,
    )

    logger.log_outcome(

        race_id="TOKYO_11R",

        selection="Horse_A",

        hit=True,

        profit=875,

        bankroll_after=20875,
    )

    print(
        logger.summary()
    )

    print(
        logger.skip_analysis()
    )
