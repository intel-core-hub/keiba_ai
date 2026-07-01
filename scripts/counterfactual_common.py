from __future__ import annotations

import json
import math
import os
import warnings
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


warnings.filterwarnings("ignore", category=FutureWarning)


def _safe_numeric(series: pd.Series | None, default: float = np.nan) -> pd.Series:
    if series is None:
        return pd.Series(dtype=float)
    return pd.to_numeric(series, errors="coerce").fillna(default)


def _entropy_score(probability: float) -> float:
    p = float(np.clip(probability, 1e-6, 1.0 - 1e-6))
    entropy = -(p * math.log(p) + (1.0 - p) * math.log(1.0 - p))
    return float(entropy / math.log(2.0))


def _regime_from_odds(odds: float | int | None) -> str:
    value = pd.to_numeric(pd.Series([odds]), errors="coerce").iloc[0]
    if pd.isna(value):
        return "UNKNOWN"
    if value <= 2.0:
        return "FAVORITE_HEAVY"
    if value <= 4.0:
        return "FAVORITE_TO_BALANCED"
    if value <= 8.0:
        return "BALANCED"
    if value <= 20.0:
        return "LONGSHOT"
    return "DEEP_LONGSHOT"


def _calibration_gap(row: pd.Series) -> float:
    if pd.notna(row.get("calibration_gap", np.nan)):
        return float(row.get("calibration_gap"))
    probability = row.get("calibrated_probability", row.get("probability", row.get("pred_prob", np.nan)))
    if pd.isna(probability):
        return float("nan")
    market_probability = row.get("market_probability", np.nan)
    if pd.isna(market_probability) and pd.notna(row.get("odds", np.nan)):
        odds = float(row.get("odds"))
        market_probability = 1.0 / odds if odds > 0 else np.nan
    if pd.isna(market_probability):
        hit = row.get("hit", np.nan)
        if pd.notna(hit):
            market_probability = float(hit)
    if pd.isna(market_probability):
        return float("nan")
    return float(abs(float(probability) - float(market_probability)))


def _uncertainty_score(row: pd.Series) -> float:
    if pd.notna(row.get("uncertainty_score", np.nan)):
        return float(row.get("uncertainty_score"))
    probability = row.get("calibrated_probability", row.get("probability", row.get("pred_prob", np.nan)))
    if pd.isna(probability):
        return 0.5
    return _entropy_score(float(probability))


def _expected_value(row: pd.Series) -> float:
    if pd.notna(row.get("expected_value", np.nan)):
        return float(row.get("expected_value"))
    probability = row.get("calibrated_probability", row.get("probability", row.get("pred_prob", np.nan)))
    odds = row.get("odds", np.nan)
    if pd.isna(probability) or pd.isna(odds):
        return float("nan")
    return float(probability) * float(odds)


def _edge(row: pd.Series) -> float:
    if pd.notna(row.get("edge", np.nan)):
        return float(row.get("edge"))
    expected_value = _expected_value(row)
    if pd.isna(expected_value):
        return float("nan")
    return float(expected_value - 1.0)


def _profit_per_unit(row: pd.Series) -> float:
    profit = row.get("profit", np.nan)
    stake = row.get("stake", row.get("final_size", row.get("bet_size", np.nan)))
    if pd.notna(profit) and pd.notna(stake) and float(stake) > 0:
        return float(profit) / float(stake)
    hit = row.get("hit", np.nan)
    odds = row.get("odds", np.nan)
    if pd.notna(hit) and pd.notna(odds):
        return float(odds) - 1.0 if bool(hit) else -1.0
    return 0.0


def dataframe_to_markdown(frame: pd.DataFrame) -> str:
    if frame is None or len(frame) == 0:
        return "No data"
    rows = frame.copy().astype(object).where(pd.notna(frame), "").astype(str)
    headers = list(rows.columns)
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for _, row in rows.iterrows():
        lines.append("| " + " | ".join(row[column] for column in headers) + " |")
    return "\n".join(lines)


def load_records(path: str | Path) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"input not found: {p}")

    if p.suffix.lower() == ".jsonl":
        rows = []
        with p.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except Exception:
                    continue
                if isinstance(record, dict) and isinstance(record.get("payload"), dict):
                    row = dict(record["payload"])
                    row.setdefault("event", record.get("event"))
                    row.setdefault("timestamp", record.get("timestamp"))
                    row.setdefault("entry_hash", record.get("entry_hash"))
                    rows.append(row)
                else:
                    rows.append(record)
        df = pd.DataFrame(rows)
    else:
        df = pd.read_csv(p, low_memory=False)

    if len(df) == 0:
        return df

    if "type" in df.columns:
        decision_df = df[df["type"].ne("OUTCOME")].copy()
        outcome_df = df[df["type"].eq("OUTCOME")].copy()
        if len(decision_df) > 0:
            df = decision_df.reset_index(drop=True)
            if len(outcome_df) > 0:
                df = merge_outcomes(df, outcome_df)

    return normalize_records(df)


def merge_outcomes(decisions: pd.DataFrame, outcomes: pd.DataFrame) -> pd.DataFrame:
    base = decisions.copy()
    extra = outcomes.copy()

    merge_keys = []
    if "decision_id" in base.columns and "decision_id" in extra.columns:
        merge_keys = ["decision_id"]
    elif {"race_id", "selection"}.issubset(base.columns) and {"race_id", "selection"}.issubset(extra.columns):
        merge_keys = ["race_id", "selection"]
    elif {"race_id", "horse_name"}.issubset(base.columns) and {"race_id", "horse_name"}.issubset(extra.columns):
        merge_keys = ["race_id", "horse_name"]

    if not merge_keys:
        return base

    wanted = [column for column in ["hit", "profit", "bankroll_after", "drawdown", "survival_score"] if column in extra.columns]
    if not wanted:
        return base

    merged = base.merge(extra[merge_keys + wanted].drop_duplicates(merge_keys, keep="last"), on=merge_keys, how="left", suffixes=("", "_outcome"))
    for column in wanted:
        extra_col = f"{column}_outcome"
        if extra_col in merged.columns:
            if column in merged.columns:
                merged[column] = merged[column].combine_first(merged[extra_col])
                merged = merged.drop(columns=[extra_col])
            else:
                merged = merged.rename(columns={extra_col: column})
    return merged


def normalize_records(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()

    rename_map = {}
    for source, target in [
        ("pred_prob", "probability"),
        ("calibrated_prob", "calibrated_probability"),
        ("decision_prob", "probability"),
        ("stake_size", "stake"),
    ]:
        if source in work.columns and target not in work.columns:
            rename_map[source] = target
    if rename_map:
        work = work.rename(columns=rename_map)

    if "timestamp" in work.columns:
        work["timestamp"] = pd.to_datetime(work["timestamp"], errors="coerce")

    for column in ["probability", "calibrated_probability", "market_probability", "odds", "edge", "expected_value", "stake", "hit", "profit", "bankroll", "drawdown", "risk_multiplier", "uncertainty_score", "calibration_gap"]:
        if column in work.columns:
            work[column] = pd.to_numeric(work[column], errors="coerce")

    if "probability" not in work.columns:
        if "calibrated_probability" in work.columns:
            work["probability"] = work["calibrated_probability"]
        elif "pred_prob" in work.columns:
            work["probability"] = pd.to_numeric(work["pred_prob"], errors="coerce")

    if "calibrated_probability" not in work.columns and "probability" in work.columns:
        work["calibrated_probability"] = work["probability"]

    if "odds" in work.columns:
        work["market_probability"] = np.where(work["odds"] > 0, 1.0 / work["odds"], np.nan)
    elif "market_probability" not in work.columns:
        work["market_probability"] = np.nan

    if "edge" not in work.columns:
        work["edge"] = work.apply(_edge, axis=1)

    if "expected_value" not in work.columns:
        work["expected_value"] = work.apply(_expected_value, axis=1)

    if "stake" not in work.columns:
        for candidate in ["final_size", "bet_size", "adjusted_size", "base_size"]:
            if candidate in work.columns:
                work["stake"] = pd.to_numeric(work[candidate], errors="coerce")
                break
        if "stake" not in work.columns:
            decision_series = work["decision"] if "decision" in work.columns else pd.Series("BUY", index=work.index)
            work["stake"] = np.where(pd.Series(decision_series, index=work.index).astype(str).str.upper().isin(["BUY", "BET", "TAKE"]), 1.0, 0.0)
    work["stake"] = work["stake"].fillna(0.0)

    if "hit" not in work.columns:
        if "profit" in work.columns and "stake" in work.columns:
            work["hit"] = (work["profit"] > 0).astype(int)
        elif "actual_pos" in work.columns:
            work["hit"] = (pd.to_numeric(work["actual_pos"], errors="coerce") == 1).astype(int)
        else:
            work["hit"] = 0
    work["hit"] = pd.to_numeric(work["hit"], errors="coerce").fillna(0).astype(int)

    if "profit" not in work.columns:
        work["profit"] = np.where(work["hit"] > 0, work["stake"] * (work.get("odds", pd.Series(1.0, index=work.index)) - 1.0), -work["stake"])

    if "bankroll" not in work.columns:
        work["bankroll"] = np.nan

    if "uncertainty_score" not in work.columns:
        prob = work.get("calibrated_probability", work.get("probability", pd.Series(0.5, index=work.index)))
        work["uncertainty_score"] = prob.fillna(0.5).apply(lambda value: _entropy_score(float(value)))

    if "calibration_gap" not in work.columns:
        work["calibration_gap"] = work.apply(_calibration_gap, axis=1)

    if "regime" not in work.columns:
        work["regime"] = work.get("odds", pd.Series(np.nan, index=work.index)).apply(_regime_from_odds)

    if "defensive_mode" not in work.columns:
        work["defensive_mode"] = np.where(work["regime"].isin(["SURVIVAL", "RISK_OFF", "DEFENSIVE"]), "DEFENSIVE", "NORMAL")

    if "decision" not in work.columns:
        work["decision"] = np.where(work["stake"] > 0, "BUY", "SKIP")

    if "skipped" not in work.columns:
        work["skipped"] = work["stake"].fillna(0.0) <= 0

    if "race_id" not in work.columns:
        work["race_id"] = work.index.astype(str)

    if "selection" not in work.columns:
        if "horse_name" in work.columns:
            work["selection"] = work["horse_name"].astype(str)
        else:
            work["selection"] = work.index.astype(str)

    if "timestamp" in work.columns:
        work = work.sort_values(["timestamp", "race_id", "selection"], kind="stable").reset_index(drop=True)
    else:
        work = work.reset_index(drop=True)

    return work


def initial_bankroll(df: pd.DataFrame, default: float = 20000.0) -> float:
    for column in ["bankroll", "bankroll_after"]:
        if column in df.columns:
            series = pd.to_numeric(df[column], errors="coerce").dropna()
            if len(series) > 0:
                return float(series.iloc[0])
    return float(default)


@dataclass
class PolicyConfig:
    name: str
    kelly_scale: float = 1.0
    exposure_scale: float = 1.0
    max_uncertainty: float | None = None
    min_edge: float = 0.0
    min_expected_value: float = 1.0
    force_no_bet: bool = False
    allow_new_bets: bool = False
    use_recorded_stake: bool = True
    regime_aware: bool = False
    no_bet_regimes: tuple[str, ...] = ("SURVIVAL", "RISK_OFF", "DEFENSIVE")
    calibration_stop: bool = False
    calibration_window: int = 20
    calibration_delta: float = 0.04
    calibration_ratio: float = 1.10
    hard_drawdown_stop: float | None = None
    base_stake_fraction: float = 0.02
    max_risk_fraction: float = 0.10
    halt_after_stop: bool = True


@dataclass
class PolicyRunResult:
    policy: str
    path: pd.DataFrame
    summary: dict[str, float | int | str | bool]
    available: bool = True
    reason: str | None = None


def _race_key(series: pd.Series) -> str:
    if "race_id" in series and pd.notna(series["race_id"]):
        return str(series["race_id"])
    return str(series.name)


def should_halt_on_calibration(history: deque[float], window: int, delta: float, ratio: float) -> bool:
    if len(history) < window * 2:
        return False
    data = list(history)
    recent = data[-window:]
    previous = data[-window * 2:-window]
    recent_mean = float(np.mean(recent)) if recent else 0.0
    previous_mean = float(np.mean(previous)) if previous else 0.0
    if previous_mean <= 0:
        return recent_mean > delta
    return (recent_mean - previous_mean) >= delta and recent_mean >= previous_mean * ratio


def simulate_policy(df: pd.DataFrame, policy: PolicyConfig, initial_bankroll_value: float | None = None) -> PolicyRunResult:
    work = normalize_records(df)
    if len(work) == 0:
        return PolicyRunResult(policy=policy.name, path=pd.DataFrame(), summary={"available": 0, "reason": "empty_input"}, available=False, reason="empty_input")

    initial = initial_bankroll_value if initial_bankroll_value is not None else initial_bankroll(work)
    bankroll = float(initial)
    peak = float(initial)
    halted = False
    halt_reason: str | None = None
    current_race = None
    race_risk_used = 0.0
    uncertainty_history: deque[float] = deque(maxlen=max(2 * policy.calibration_window, 50))
    calibration_history: deque[float] = deque(maxlen=max(2 * policy.calibration_window, 50))
    rows: list[dict[str, float | int | str | bool | None]] = []

    for idx, row in work.iterrows():
        race_id = str(row.get("race_id", idx))
        if race_id != current_race:
            current_race = race_id
            race_risk_used = 0.0

        uncertainty = float(_uncertainty_score(row))
        calibration_gap = float(_calibration_gap(row)) if pd.notna(_calibration_gap(row)) else float("nan")
        edge = float(_edge(row)) if pd.notna(_edge(row)) else float("nan")
        expected_value = float(_expected_value(row)) if pd.notna(_expected_value(row)) else float("nan")
        regime = str(row.get("regime", _regime_from_odds(row.get("odds", np.nan))))

        uncertainty_history.append(uncertainty)
        if pd.notna(calibration_gap):
            calibration_history.append(calibration_gap)

        if policy.calibration_stop and should_halt_on_calibration(calibration_history, policy.calibration_window, policy.calibration_delta, policy.calibration_ratio):
            halted = True
            halt_reason = halt_reason or "CALIBRATION_DETERIORATION"

        if policy.hard_drawdown_stop is not None:
            drawdown_now = 0.0 if peak <= 0 else max(0.0, 1.0 - bankroll / peak)
            if drawdown_now >= policy.hard_drawdown_stop:
                halted = True
                halt_reason = halt_reason or "DRAWDOWN_STOP"

        recorded_taken = bool(row.get("stake", 0.0) > 0 or str(row.get("decision", "")).upper() in {"BUY", "BET", "TAKE"} or not bool(row.get("skipped", False)))
        action = "SKIP"
        skip_reason = None
        take = recorded_taken

        if not policy.allow_new_bets and not recorded_taken:
            take = False

        if policy.force_no_bet:
            take = False
            skip_reason = "NO_BET_POLICY"
        elif halted and policy.halt_after_stop:
            take = False
            skip_reason = halt_reason or "HALTED"
        elif policy.regime_aware and regime in policy.no_bet_regimes:
            take = False
            skip_reason = f"REGIME_NO_BET:{regime}"
        elif policy.max_uncertainty is not None and uncertainty > policy.max_uncertainty:
            take = False
            skip_reason = "HIGH_UNCERTAINTY"
        elif pd.notna(edge) and edge < policy.min_edge:
            take = False
            skip_reason = "INSUFFICIENT_EDGE"
        elif pd.notna(expected_value) and expected_value < policy.min_expected_value:
            take = False
            skip_reason = "LOW_EXPECTED_VALUE"

        base_stake = float(row.get("stake", row.get("final_size", row.get("bet_size", 0.0))) or 0.0)
        if base_stake <= 0 and policy.allow_new_bets:
            base_stake = max(0.0, bankroll * policy.base_stake_fraction)

        recorded_risk_multiplier = float(row.get("risk_multiplier", 1.0) or 1.0)
        stake = 0.0
        if take and base_stake > 0:
            stake = base_stake * policy.kelly_scale * policy.exposure_scale * recorded_risk_multiplier
            max_allowed = bankroll * policy.max_risk_fraction - race_risk_used
            stake = max(0.0, min(stake, max_allowed))

        unit_return = _profit_per_unit(row)
        profit = stake * unit_return if stake > 0 else 0.0

        if stake > 0:
            action = "BET"
            race_risk_used += stake

        bankroll_before = bankroll
        bankroll = bankroll + profit
        peak = max(peak, bankroll)
        drawdown = 0.0 if peak <= 0 else max(0.0, 1.0 - bankroll / peak)

        rows.append({
            "step": idx,
            "timestamp": row.get("timestamp"),
            "race_id": race_id,
            "selection": row.get("selection", row.get("horse_name", str(idx))),
            "regime": regime,
            "bankroll_before": round(float(bankroll_before), 6),
            "bankroll_after": round(float(bankroll), 6),
            "peak_bankroll": round(float(peak), 6),
            "drawdown": round(float(drawdown), 6),
            "stake": round(float(stake), 6),
            "profit": round(float(profit), 6),
            "action": action,
            "skip_reason": skip_reason,
            "recorded_taken": recorded_taken,
            "probability": round(float(row.get("probability", row.get("calibrated_probability", np.nan))), 6) if pd.notna(row.get("probability", row.get("calibrated_probability", np.nan))) else np.nan,
            "calibrated_probability": round(float(row.get("calibrated_probability", row.get("probability", np.nan))), 6) if pd.notna(row.get("calibrated_probability", row.get("probability", np.nan))) else np.nan,
            "market_probability": round(float(row.get("market_probability", np.nan)), 6) if pd.notna(row.get("market_probability", np.nan)) else np.nan,
            "odds": round(float(row.get("odds", np.nan)), 6) if pd.notna(row.get("odds", np.nan)) else np.nan,
            "edge": round(float(edge), 6) if pd.notna(edge) else np.nan,
            "expected_value": round(float(expected_value), 6) if pd.notna(expected_value) else np.nan,
            "uncertainty_score": round(float(uncertainty), 6),
            "calibration_gap": round(float(calibration_gap), 6) if pd.notna(calibration_gap) else np.nan,
            "risk_multiplier": round(float(recorded_risk_multiplier), 6),
        })

    path = pd.DataFrame(rows)
    summary = summarize_path(path, initial_bankroll=initial, policy_name=policy.name)
    summary["halt_reason"] = halt_reason or ""
    summary["policy"] = policy.name
    return PolicyRunResult(policy=policy.name, path=path, summary=summary)


def summarize_path(path: pd.DataFrame, initial_bankroll: float, policy_name: str = "policy") -> dict[str, float | int | str | bool]:
    if len(path) == 0:
        return {
            "policy": policy_name,
            "bets": 0,
            "final_bankroll": round(float(initial_bankroll), 6),
            "profit": 0.0,
            "roi": 0.0,
            "risk_adjusted_roi": 0.0,
            "max_drawdown": 0.0,
            "variance": 0.0,
            "survival_score": 0.0,
            "ruin_probability": 0.0,
            "collapse_probability": 0.0,
            "survival_improvement": 0.0,
            "variance_reduction": 0.0,
            "stress_robustness": 0.0,
        }

    profits = pd.to_numeric(path["profit"], errors="coerce").fillna(0.0)
    stakes = pd.to_numeric(path["stake"], errors="coerce").fillna(0.0)
    bet_mask = stakes > 0
    bets = int(bet_mask.sum())
    total_profit = float(profits.sum())
    final_bankroll = float(initial_bankroll + total_profit)
    roi = float(total_profit / stakes[bet_mask].sum()) if stakes[bet_mask].sum() > 0 else 0.0
    equity = profits.cumsum() + initial_bankroll
    peak = equity.cummax()
    drawdown = equity - peak
    max_drawdown = float(drawdown.min()) if len(drawdown) else 0.0
    profit_variance = float(profits[bet_mask].var(ddof=0)) if bets > 0 else 0.0
    profit_std = float(profits[bet_mask].std(ddof=0)) if bets > 1 else 0.0
    risk_adjusted_roi = float(total_profit / (profit_std + 1e-9)) if bets > 0 else 0.0

    ruin_probability = estimate_ruin_probability(path, initial_bankroll=initial_bankroll, ruin_ratio=0.0)
    collapse_probability = estimate_ruin_probability(path, initial_bankroll=initial_bankroll, ruin_ratio=0.70)
    stress_robustness = max(0.0, min(1.0, (1.0 - ruin_probability) * (1.0 - min(1.0, abs(max_drawdown) / max(1.0, initial_bankroll)))))
    survival_score = max(0.0, min(100.0, 100.0 * (
        0.35 * max(final_bankroll / max(1.0, initial_bankroll), 0.0)
        + 0.25 * max(0.0, 1.0 - abs(max_drawdown) / max(1.0, initial_bankroll))
        + 0.20 * (1.0 - ruin_probability)
        + 0.20 * (1.0 - min(1.0, profit_variance / (max(1.0, abs(total_profit)) + 1.0)))
    )))

    return {
        "policy": policy_name,
        "bets": bets,
        "bet_rows": int(len(path)),
        "final_bankroll": round(final_bankroll, 6),
        "profit": round(total_profit, 6),
        "roi": round(roi, 6),
        "risk_adjusted_roi": round(risk_adjusted_roi, 6),
        "max_drawdown": round(max_drawdown, 6),
        "variance": round(profit_variance, 6),
        "profit_std": round(profit_std, 6),
        "survival_score": round(survival_score, 6),
        "ruin_probability": round(ruin_probability, 6),
        "collapse_probability": round(collapse_probability, 6),
        "survival_improvement": round(max(0.0, 1.0 - ruin_probability), 6),
        "variance_reduction": 0.0,
        "stress_robustness": round(stress_robustness, 6),
    }


def estimate_ruin_probability(path: pd.DataFrame, initial_bankroll: float, ruin_ratio: float = 0.0, samples: int = 500, random_state: int = 42) -> float:
    if len(path) == 0:
        return 0.0

    work = path.copy()
    if "race_id" in work.columns:
        blocks = [group["profit"].to_numpy(dtype=float) for _, group in work.groupby("race_id", sort=False)]
    else:
        blocks = [np.asarray([value], dtype=float) for value in pd.to_numeric(work["profit"], errors="coerce").fillna(0.0).tolist()]

    if not blocks:
        return 0.0

    rng = np.random.default_rng(random_state)
    ruin_threshold = float(initial_bankroll * ruin_ratio)
    ruined = 0

    for _ in range(samples):
        bankroll = float(initial_bankroll)
        sample_blocks = rng.choice(len(blocks), size=len(blocks), replace=True)
        for block_index in sample_blocks:
            bankroll += float(np.sum(blocks[block_index]))
            if bankroll <= ruin_threshold:
                ruined += 1
                break

    return float(ruined / samples)


def default_policy_suite() -> list[PolicyConfig]:
    return [
        PolicyConfig(name="recorded", kelly_scale=1.0, exposure_scale=1.0, use_recorded_stake=True),
        PolicyConfig(name="no_bet", force_no_bet=True, use_recorded_stake=True),
        PolicyConfig(name="kelly_half", kelly_scale=0.5, exposure_scale=1.0, use_recorded_stake=True),
        PolicyConfig(name="aggressive", kelly_scale=1.25, exposure_scale=1.25, max_uncertainty=0.80, min_edge=-0.02, use_recorded_stake=True),
        PolicyConfig(name="defensive", kelly_scale=0.50, exposure_scale=0.60, max_uncertainty=0.45, min_edge=0.02, regime_aware=True, calibration_stop=True, calibration_window=20, calibration_delta=0.03, calibration_ratio=1.05, use_recorded_stake=True),
        PolicyConfig(name="regime_no_bet", kelly_scale=0.75, exposure_scale=0.80, regime_aware=True, calibration_stop=False, use_recorded_stake=True),
        PolicyConfig(name="calibration_stop", kelly_scale=1.0, exposure_scale=0.80, calibration_stop=True, calibration_window=20, calibration_delta=0.04, calibration_ratio=1.10, use_recorded_stake=True),
    ]


def policy_from_name(
    name: str,
    *,
    max_uncertainty: float | None = None,
    calibration_window: int = 20,
    calibration_delta: float = 0.04,
    calibration_ratio: float = 1.10,
    exposure_scale: float | None = None,
    kelly_scale: float | None = None,
    min_edge: float | None = None,
) -> PolicyConfig:
    name = str(name).strip().lower()

    if name == "recorded":
        return PolicyConfig(name="recorded", kelly_scale=1.0, exposure_scale=1.0, use_recorded_stake=True)
    if name == "no_bet":
        return PolicyConfig(name="no_bet", force_no_bet=True, use_recorded_stake=True)
    if name == "kelly_half":
        return PolicyConfig(name="kelly_half", kelly_scale=0.5, exposure_scale=1.0, use_recorded_stake=True)
    if name == "aggressive":
        return PolicyConfig(name="aggressive", kelly_scale=1.25, exposure_scale=1.25, max_uncertainty=0.80, min_edge=-0.02, use_recorded_stake=True)
    if name == "defensive":
        return PolicyConfig(name="defensive", kelly_scale=0.50, exposure_scale=0.60, max_uncertainty=0.45, min_edge=0.02, regime_aware=True, calibration_stop=True, calibration_window=calibration_window, calibration_delta=0.03, calibration_ratio=1.05, use_recorded_stake=True)
    if name == "regime_no_bet":
        return PolicyConfig(name="regime_no_bet", kelly_scale=0.75, exposure_scale=0.80, regime_aware=True, calibration_stop=False, use_recorded_stake=True)
    if name == "calibration_stop":
        return PolicyConfig(name="calibration_stop", kelly_scale=1.0, exposure_scale=0.80, calibration_stop=True, calibration_window=calibration_window, calibration_delta=calibration_delta, calibration_ratio=calibration_ratio, use_recorded_stake=True)
    if name == "uncertainty_threshold":
        threshold = 0.65 if max_uncertainty is None else float(max_uncertainty)
        return PolicyConfig(name=f"uncertainty_{threshold:g}", kelly_scale=1.0, exposure_scale=1.0, max_uncertainty=threshold, use_recorded_stake=True)

    return PolicyConfig(
        name=name,
        kelly_scale=1.0 if kelly_scale is None else float(kelly_scale),
        exposure_scale=1.0 if exposure_scale is None else float(exposure_scale),
        max_uncertainty=max_uncertainty,
        min_edge=0.0 if min_edge is None else float(min_edge),
        use_recorded_stake=True,
    )


def bankroll_curve_frame(results: Sequence[PolicyRunResult]) -> pd.DataFrame:
    rows = []
    for result in results:
        if result.path is None or len(result.path) == 0:
            continue
        for _, row in result.path.iterrows():
            rows.append({
                "policy": result.policy,
                "step": int(row.get("step", 0)),
                "timestamp": row.get("timestamp"),
                "race_id": row.get("race_id"),
                "selection": row.get("selection"),
                "bankroll": float(row.get("bankroll_after", np.nan)),
                "drawdown": float(row.get("drawdown", np.nan)),
                "stake": float(row.get("stake", 0.0)),
                "profit": float(row.get("profit", 0.0)),
                "regime": row.get("regime"),
                "uncertainty_score": float(row.get("uncertainty_score", np.nan)),
                "calibration_gap": float(row.get("calibration_gap", np.nan)),
                "action": row.get("action"),
            })
    return pd.DataFrame(rows)


def exposure_heatmap_frame(results: Sequence[PolicyRunResult]) -> pd.DataFrame:
    rows = []
    for result in results:
        if result.path is None or len(result.path) == 0:
            continue
        path = result.path.copy()
        path["stake"] = pd.to_numeric(path["stake"], errors="coerce").fillna(0.0)
        path["bankroll_before"] = pd.to_numeric(path["bankroll_before"], errors="coerce").fillna(1.0)
        path["exposure"] = path["stake"] / path["bankroll_before"].replace(0, np.nan)
        for regime, grp in path.groupby("regime"):
            rows.append({
                "policy": result.policy,
                "regime": regime,
                "avg_exposure": round(float(grp["exposure"].mean()), 6),
                "avg_stake": round(float(grp["stake"].mean()), 6),
                "roi": round(float(grp["profit"].sum() / grp["stake"].sum()) if grp["stake"].sum() > 0 else 0.0, 6),
                "bets": int((grp["stake"] > 0).sum()),
            })
    return pd.DataFrame(rows)


def compare_summaries(results: Sequence[PolicyRunResult]) -> pd.DataFrame:
    rows = [dict(result.summary) for result in results]
    frame = pd.DataFrame(rows)
    if len(frame) == 0:
        return frame
    baseline = frame.loc[frame["policy"] == "recorded"].iloc[0].to_dict() if (frame["policy"] == "recorded").any() else frame.iloc[0].to_dict()
    baseline_variance = float(baseline.get("variance", 0.0) or 0.0)
    frame["drawdown_delta_vs_baseline"] = frame["max_drawdown"] - float(baseline.get("max_drawdown", 0.0))
    frame["roi_delta_vs_baseline"] = frame["roi"] - float(baseline.get("roi", 0.0))
    frame["survival_delta_vs_baseline"] = frame["survival_score"] - float(baseline.get("survival_score", 0.0))
    frame["variance_delta_vs_baseline"] = frame["variance"] - float(baseline.get("variance", 0.0))
    frame["variance_reduction"] = baseline_variance - frame["variance"]
    frame["collapse_avoidance"] = 1.0 - frame["collapse_probability"]
    denom = abs(baseline_variance) + 1e-9
    frame["stability_improvement"] = frame["survival_delta_vs_baseline"] + (frame["variance_reduction"] / denom)
    return frame.sort_values(["survival_score", "risk_adjusted_roi"], ascending=False).reset_index(drop=True)


def plot_bankroll_curves(curves: pd.DataFrame, out_path: str | Path) -> None:
    if curves is None or len(curves) == 0:
        return
    fig, ax = plt.subplots(figsize=(12, 7))
    for policy, grp in curves.groupby("policy"):
        grp = grp.sort_values("step")
        ax.plot(grp["step"], grp["bankroll"], label=policy, linewidth=1.8)
    ax.set_title("Bankroll Curves")
    ax.set_xlabel("Step")
    ax.set_ylabel("Bankroll")
    ax.legend(loc="best")
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(out_path, dpi=160)
    plt.close(fig)


def plot_drawdown_comparison(curves: pd.DataFrame, out_path: str | Path) -> None:
    if curves is None or len(curves) == 0:
        return
    fig, ax = plt.subplots(figsize=(12, 7))
    for policy, grp in curves.groupby("policy"):
        grp = grp.sort_values("step")
        ax.plot(grp["step"], grp["drawdown"], label=policy, linewidth=1.8)
    ax.set_title("Drawdown Comparison")
    ax.set_xlabel("Step")
    ax.set_ylabel("Drawdown")
    ax.legend(loc="best")
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(out_path, dpi=160)
    plt.close(fig)


def plot_exposure_heatmap(exposure: pd.DataFrame, out_path: str | Path, value_col: str = "avg_exposure") -> None:
    if exposure is None or len(exposure) == 0:
        return
    pivot = exposure.pivot_table(index="policy", columns="regime", values=value_col, aggfunc="mean", fill_value=0.0)
    fig, ax = plt.subplots(figsize=(12, max(5, 0.4 * len(pivot.index) + 2)))
    im = ax.imshow(pivot.to_numpy(dtype=float), aspect="auto", cmap="viridis")
    ax.set_xticks(range(len(pivot.columns)))
    ax.set_xticklabels([str(c) for c in pivot.columns], rotation=20, ha="right")
    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels([str(i) for i in pivot.index])
    ax.set_title(f"Exposure Heatmap: {value_col}")
    fig.colorbar(im, ax=ax, shrink=0.8)
    fig.tight_layout()
    fig.savefig(out_path, dpi=160)
    plt.close(fig)


def save_summary_bundle(results: Sequence[PolicyRunResult], outdir: str | Path) -> dict[str, Path]:
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    summary = compare_summaries(results)
    curves = bankroll_curve_frame(results)
    exposure = exposure_heatmap_frame(results)

    summary_path = outdir / "policy_summary.csv"
    curves_path = outdir / "bankroll_curves.csv"
    exposure_path = outdir / "exposure_heatmap.csv"
    summary.to_csv(summary_path, index=False, encoding="utf-8-sig")
    curves.to_csv(curves_path, index=False, encoding="utf-8-sig")
    exposure.to_csv(exposure_path, index=False, encoding="utf-8-sig")

    plot_bankroll_curves(curves, outdir / "bankroll_curves.png")
    plot_drawdown_comparison(curves, outdir / "drawdown_comparison.png")
    plot_exposure_heatmap(exposure, outdir / "exposure_heatmap.png", value_col="avg_exposure")

    report = outdir / "counterfactual_report.md"
    report.write_text(
        "\n".join([
            "# Counterfactual Replay Report",
            "",
            dataframe_to_markdown(summary),
            "",
            "## Exposure Heatmap",
            dataframe_to_markdown(exposure),
        ]),
        encoding="utf-8",
    )

    return {
        "summary": summary_path,
        "curves": curves_path,
        "exposure": exposure_path,
        "report": report,
    }
