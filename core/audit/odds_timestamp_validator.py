"""Leakage checks for odds timestamp governance."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import pandas as pd

from .odds_availability_checker import OddsAvailabilityChecker
from .odds_history_manager import OddsHistoryManager, SnapshotConfig
from .odds_snapshot import normalize_snapshot_label


@dataclass
class ValidationIssue:
    issue_type: str
    severity: str
    message: str
    rows: int = 0


class OddsTimestampValidator:
    """Validate that odds features are only used from their valid time window."""

    def __init__(self, strict: bool = True):
        self.strict = strict
        self.availability_checker = OddsAvailabilityChecker()

    def validate(
        self,
        df: pd.DataFrame,
        *,
        race_start_col: str | None = None,
        bet_time_col: str | None = None,
        snapshot_label_col: str = "snapshot_label",
        available_at_col: str = "available_at",
        odds_col: str = "odds",
        favorite_rank_col: str = "favorite_rank",
        plain_odds_snapshot_label: str | None = None,
    ) -> dict[str, Any]:
        config = SnapshotConfig(
            race_start_col=race_start_col,
            bet_time_col=bet_time_col,
            odds_col=odds_col,
            favorite_rank_col=favorite_rank_col,
            plain_odds_snapshot_label=plain_odds_snapshot_label,
            strict=self.strict,
        )
        manager = OddsHistoryManager(config=config)
        long_frame = manager.load(df)
        annotated = self.availability_checker.annotate(
            long_frame,
            snapshot_label_col="snapshot_label",
            available_at_col="available_at",
            bet_time_col="bet_time",
            race_start_col="race_start_at",
        )

        issues: list[ValidationIssue] = []
        issues.extend(self._check_ambiguous_plain_odds(annotated, odds_col))
        issues.extend(self._check_missing_timestamp_fields(annotated))
        issues.extend(self._check_future_usage(annotated))
        issues.extend(self._check_closing_contamination(annotated))
        issues.extend(self._check_same_day_contamination(annotated))
        issues.extend(self._check_snapshot_order(annotated))

        if self._has_hard_failure(issues):
            status = "fail"
        elif issues:
            status = "warn"
        else:
            status = "pass"

        return {
            "status": status,
            "issues": [issue.__dict__ for issue in issues],
            "summary": self._build_summary(annotated),
            "available_at_bet_time": int(annotated["available_at_bet_time"].sum()) if "available_at_bet_time" in annotated.columns else 0,
            "final_market_rows": int(annotated["final_market_odds"].sum()) if "final_market_odds" in annotated.columns else 0,
            "post_market_rows": int(annotated["post_market_info"].sum()) if "post_market_info" in annotated.columns else 0,
            "annotated_frame": annotated,
        }

    def _check_ambiguous_plain_odds(self, frame: pd.DataFrame, odds_col: str) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        if odds_col in frame.columns and "plain_odds_ambiguous" in frame.columns and frame["plain_odds_ambiguous"].any():
            issues.append(
                ValidationIssue(
                    issue_type="ambiguous_odds",
                    severity="hard" if self.strict else "warn",
                    message=f"{odds_col} exists without a timestamp role; it is ambiguous and cannot be used as a safe feature.",
                    rows=int(frame["plain_odds_ambiguous"].sum()),
                )
            )
        return issues

    def _check_missing_timestamp_fields(self, frame: pd.DataFrame) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        if "available_at" not in frame.columns or frame["available_at"].isna().all():
            issues.append(
                ValidationIssue(
                    issue_type="missing_available_at",
                    severity="hard",
                    message="No usable available_at timestamp column was provided or inferred.",
                    rows=int(frame["available_at"].isna().sum()) if "available_at" in frame.columns else len(frame),
                )
            )
        if "bet_time" not in frame.columns or frame["bet_time"].isna().all():
            issues.append(
                ValidationIssue(
                    issue_type="missing_bet_time",
                    severity="warn",
                    message="No usable bet_time column was provided; availability can only be checked against race_start_at.",
                    rows=int(frame["bet_time"].isna().sum()) if "bet_time" in frame.columns else len(frame),
                )
            )
        return issues

    def _check_future_usage(self, frame: pd.DataFrame) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        if "available_at_ts" not in frame.columns:
            return issues
        bet_time = pd.to_datetime(frame.get("bet_time"), errors="coerce")
        race_start = pd.to_datetime(frame.get("race_start_at"), errors="coerce")
        available = pd.to_datetime(frame["available_at_ts"], errors="coerce")
        future_mask = available.notna() & ((bet_time.notna() & (available > bet_time)) | (race_start.notna() & (available > race_start)))
        if future_mask.any():
            issues.append(
                ValidationIssue(
                    issue_type="future_odds_usage",
                    severity="hard",
                    message="At least one odds snapshot is timestamped after the bet time or race start.",
                    rows=int(future_mask.sum()),
                )
            )
        return issues

    def _check_closing_contamination(self, frame: pd.DataFrame) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        if "final_market_odds" in frame.columns and "available_at_bet_time" in frame.columns:
            contaminated = frame[frame["final_market_odds"] & ~frame["available_at_bet_time"]]
            if len(contaminated) > 0:
                issues.append(
                    ValidationIssue(
                        issue_type="closing_odds_contamination",
                        severity="hard",
                        message="Final closing odds appear in a context that is not available at bet time.",
                        rows=len(contaminated),
                    )
                )
        return issues

    def _check_same_day_contamination(self, frame: pd.DataFrame) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        available = pd.to_datetime(frame.get("available_at"), errors="coerce")
        bet_time = pd.to_datetime(frame.get("bet_time"), errors="coerce")
        race_start = pd.to_datetime(frame.get("race_start_at"), errors="coerce")
        if available.notna().any() and bet_time.notna().any():
            same_day = available.dt.date == bet_time.dt.date
            after_bet = available > bet_time
            if (same_day & after_bet).any():
                issues.append(
                    ValidationIssue(
                        issue_type="same_day_contamination",
                        severity="hard",
                        message="Some odds snapshots share the same calendar day as bet_time but are later than it.",
                        rows=int((same_day & after_bet).sum()),
                    )
                )
        elif available.notna().any() and race_start.notna().any():
            same_day = available.dt.date == race_start.dt.date
            after_race = available > race_start
            if (same_day & after_race).any():
                issues.append(
                    ValidationIssue(
                        issue_type="same_day_contamination",
                        severity="warn",
                        message="Odds timestamps are on the same day as race_start but some are later than the race start time.",
                        rows=int((same_day & after_race).sum()),
                    )
                )
        return issues

    def _check_snapshot_order(self, frame: pd.DataFrame) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        if "snapshot_label" not in frame.columns or "available_at" not in frame.columns:
            return issues
        available = pd.to_datetime(frame["available_at"], errors="coerce")
        groups = frame.assign(available_at_ts=available).groupby([c for c in ["race_id", "horse_name"] if c in frame.columns], dropna=False)
        order_rank = {label: idx for idx, label in enumerate(["t-60min", "t-30min", "t-10min", "final odds"])}
        for _, group in groups:
            ordered = group.dropna(subset=["available_at_ts"]).sort_values("available_at_ts")
            if len(ordered) <= 1:
                continue
            labels = [normalize_snapshot_label(label) for label in ordered["snapshot_label"].tolist()]
            ranks = [order_rank.get(label, -1) for label in labels]
            if any(right < left for left, right in zip(ranks, ranks[1:])):
                issues.append(
                    ValidationIssue(
                        issue_type="snapshot_order",
                        severity="hard",
                        message="Snapshot timestamps are not monotonic in the expected t-60 -> t-30 -> t-10 -> final order.",
                        rows=len(ordered),
                    )
                )
                break
        return issues

    @staticmethod
    def _has_hard_failure(issues: Iterable[ValidationIssue]) -> bool:
        return any(issue.severity == "hard" for issue in issues)

    @staticmethod
    def _build_summary(frame: pd.DataFrame) -> dict[str, Any]:
        return {
            "rows": len(frame),
            "labels": sorted(frame["snapshot_label"].dropna().astype(str).unique().tolist()) if "snapshot_label" in frame.columns else [],
            "missing_available_at": int(frame["available_at"].isna().sum()) if "available_at" in frame.columns else len(frame),
            "missing_bet_time": int(frame["bet_time"].isna().sum()) if "bet_time" in frame.columns else len(frame),
            "missing_race_start_at": int(frame["race_start_at"].isna().sum()) if "race_start_at" in frame.columns else len(frame),
            "available_before_race_start": int(frame["available_at_bet_time"].sum()) if "available_at_bet_time" in frame.columns else 0,
        }