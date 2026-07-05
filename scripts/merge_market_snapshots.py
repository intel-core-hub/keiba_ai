from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

EARLY_COLUMNS = (
    "odds",
    "odds_t60",
    "odds_60m",
    "odds_60min",
    "odds_t30",
    "odds_30m",
    "odds_30min",
    "opening_odds",
    "early_odds",
)

CLOSING_COLUMNS = (
    "odds",
    "closing_odds",
    "final_odds",
    "closing_price",
    "market_odds",
)


def _read(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    return pd.read_csv(path, low_memory=False)


def _normalize_key(frame: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    if "horse_id" in keys and "horse_id" not in frame.columns and "selection_id" in frame.columns:
        frame = frame.rename(columns={"selection_id": "horse_id"})
    missing = [key for key in keys if key not in frame.columns]
    if missing:
        raise ValueError(f"missing join keys: {missing}")
    out = frame.copy()
    for key in keys:
        out[key] = out[key].astype(str)
    return out


def _pick_column(frame: pd.DataFrame, explicit: str | None, candidates: tuple[str, ...], label: str) -> str:
    if explicit:
        if explicit not in frame.columns:
            raise ValueError(f"{label} column not found: {explicit}")
        return explicit
    found = [column for column in candidates if column in frame.columns]
    if not found:
        raise ValueError(f"no supported {label} odds column found")
    return found[0]


def _validate_real_snapshot(
    base: pd.DataFrame,
    snapshot: pd.DataFrame,
    *,
    join_keys: list[str],
    base_odds: str,
    snapshot_odds: str,
    label: str,
) -> None:
    if "snapshot_time" not in snapshot.columns:
        raise ValueError(f"{label} snapshot must include snapshot_time")
    if snapshot_odds == base_odds:
        # A market snapshot can use the generic column name "odds", but only if
        # it is kept in a separate timestamped snapshot file and differs from
        # the base race-close odds after join.
        pass
    if snapshot[snapshot_odds].notna().sum() == 0:
        raise ValueError(f"snapshot odds column has no values: {snapshot_odds}")
    compare_columns = [column for column in (base_odds, "odds_value") if column in base.columns]
    if not compare_columns:
        return
    merged = base[join_keys + compare_columns].merge(
        snapshot[join_keys + [snapshot_odds]].rename(columns={snapshot_odds: "__snapshot_odds"}),
        on=join_keys,
        how="inner",
        validate="many_to_one",
    )
    if merged.empty:
        return
    snapshot_values = pd.to_numeric(merged["__snapshot_odds"], errors="coerce")
    for column in compare_columns:
        base_values = pd.to_numeric(merged[column], errors="coerce")
        comparable = base_values.notna() & snapshot_values.notna()
        if comparable.any() and (base_values[comparable] == snapshot_values[comparable]).all():
            raise ValueError(f"{label} snapshot odds appear copied from base {column}")


def merge_market_snapshots(
    *,
    base_path: Path,
    output_path: Path,
    join_keys: list[str],
    early_snapshot: Path | None = None,
    closing_snapshot: Path | None = None,
    early_column: str | None = None,
    closing_column: str | None = None,
    base_odds_column: str = "odds",
) -> dict[str, Any]:
    base = _normalize_key(_read(base_path), join_keys)
    result = base.copy()
    report: dict[str, Any] = {
        "base": str(base_path),
        "output": str(output_path),
        "join_keys": join_keys,
        "rows": int(len(base)),
        "early": {"merged": False},
        "closing": {"merged": False},
    }

    if early_snapshot is not None:
        early = _normalize_key(_read(early_snapshot), join_keys)
        source_column = _pick_column(early, early_column, EARLY_COLUMNS, "early")
        target_column = "early_odds" if source_column != "early_odds" else source_column
        _validate_real_snapshot(
            base,
            early,
            join_keys=join_keys,
            base_odds=base_odds_column,
            snapshot_odds=source_column,
            label="early",
        )
        merge_cols = join_keys + [source_column]
        result = result.merge(
            early[merge_cols].rename(columns={source_column: target_column}),
            on=join_keys,
            how="left",
            validate="many_to_one",
        )
        report["early"] = {
            "merged": True,
            "snapshot": str(early_snapshot),
            "source_column": source_column,
            "target_column": target_column,
            "matched_rows": int(result[target_column].notna().sum()),
        }

    if closing_snapshot is not None:
        closing = _normalize_key(_read(closing_snapshot), join_keys)
        source_column = _pick_column(closing, closing_column, CLOSING_COLUMNS, "closing")
        target_column = "closing_odds" if source_column != "closing_odds" else source_column
        _validate_real_snapshot(
            base,
            closing,
            join_keys=join_keys,
            base_odds=base_odds_column,
            snapshot_odds=source_column,
            label="closing",
        )
        merge_cols = join_keys + [source_column]
        result = result.merge(
            closing[merge_cols].rename(columns={source_column: target_column}),
            on=join_keys,
            how="left",
            validate="many_to_one",
        )
        report["closing"] = {
            "merged": True,
            "snapshot": str(closing_snapshot),
            "source_column": source_column,
            "target_column": target_column,
            "matched_rows": int(result[target_column].notna().sum()),
        }

    if not report["early"]["merged"] and not report["closing"]["merged"]:
        raise ValueError("at least one snapshot file is required")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output_path, index=False)
    report_path = output_path.with_suffix(output_path.suffix + ".market_snapshot_report.json")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report["report"] = str(report_path)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Merge real early/closing market snapshots into a historical dataset")
    parser.add_argument("--base", default="data/processed/historical_dataset.csv")
    parser.add_argument("--output", default="data/processed/historical_dataset_with_market_snapshots.csv")
    parser.add_argument("--join-keys", default="race_id,horse_id")
    parser.add_argument("--early-snapshot", default=None)
    parser.add_argument("--closing-snapshot", default=None)
    parser.add_argument("--early-column", default=None)
    parser.add_argument("--closing-column", default=None)
    parser.add_argument("--base-odds-column", default="odds")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = merge_market_snapshots(
        base_path=Path(args.base),
        output_path=Path(args.output),
        join_keys=[key.strip() for key in args.join_keys.split(",") if key.strip()],
        early_snapshot=Path(args.early_snapshot) if args.early_snapshot else None,
        closing_snapshot=Path(args.closing_snapshot) if args.closing_snapshot else None,
        early_column=args.early_column,
        closing_column=args.closing_column,
        base_odds_column=args.base_odds_column,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
