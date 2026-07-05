from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable


Candidate = dict[str, Any]


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _load_candidates(evaluation_json: Path) -> list[Candidate]:
    if not evaluation_json.exists():
        raise FileNotFoundError(evaluation_json)
    report = json.loads(evaluation_json.read_text(encoding="utf-8"))
    candidates = report.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("evaluation JSON must include a candidates list")
    return [dict(row) for row in candidates]


def _summarize(name: str, description: str, candidates: list[Candidate], baseline_profit: float) -> dict[str, Any]:
    stake = sum(_float(row.get("stake")) for row in candidates)
    profit = sum(_float(row.get("profit")) for row in candidates)
    hits = sum(_int(row.get("hit")) for row in candidates)
    return {
        "name": name,
        "description": description,
        "candidate_count": len(candidates),
        "stake_sum": stake,
        "profit_sum": profit,
        "roi": profit / stake if stake else None,
        "hit_sum": hits,
        "hit_rate": hits / len(candidates) if candidates else None,
        "loss_reduction_vs_baseline": profit - baseline_profit,
    }


def _rank(row: Candidate) -> int:
    return _int(row.get("favorite_rank"))


def _regime(row: Candidate) -> str:
    return str(row.get("odds_regime") or "").strip().upper()


def _policy_rows(candidates: list[Candidate], predicate: Callable[[Candidate], bool]) -> list[Candidate]:
    return [row for row in candidates if predicate(row)]


def analyze_pre_contract_filters(
    *,
    evaluation_json: Path,
    output_json: Path,
    output_md: Path,
) -> dict[str, Any]:
    candidates = _load_candidates(evaluation_json)
    baseline_profit = sum(_float(row.get("profit")) for row in candidates)

    policies: list[tuple[str, str, Callable[[Candidate], bool]]] = [
        ("baseline_all", "Keep all sandbox candidates.", lambda row: True),
        (
            "exclude_deep_longshot",
            "Exclude candidates in the DEEP_LONGSHOT odds regime.",
            lambda row: _regime(row) != "DEEP_LONGSHOT",
        ),
        (
            "exclude_rank_9_plus",
            "Exclude candidates whose favorite rank is 9 or worse.",
            lambda row: _rank(row) == 0 or _rank(row) <= 8,
        ),
        (
            "exclude_deep_longshot_or_rank_9_plus",
            "Exclude DEEP_LONGSHOT candidates and favorite-rank-9-plus candidates.",
            lambda row: _regime(row) != "DEEP_LONGSHOT" and (_rank(row) == 0 or _rank(row) <= 8),
        ),
        (
            "top_3_only",
            "Keep only top-three favorite-rank candidates.",
            lambda row: 1 <= _rank(row) <= 3,
        ),
    ]

    summaries = [
        _summarize(name, description, _policy_rows(candidates, predicate), baseline_profit)
        for name, description, predicate in policies
    ]

    report = {
        "passed": True,
        "evidence_eligible": False,
        "evaluation_json": str(evaluation_json),
        "baseline_candidate_count": len(candidates),
        "baseline_profit_sum": baseline_profit,
        "policies": summaries,
        "interpretation": (
            "Sandbox-only filter analysis. This helps choose conservative pre-contract experiments; "
            "it is not Stage 4 evidence and does not prove profitability."
        ),
    }

    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text(_markdown(report), encoding="utf-8")
    return report


def _fmt_pct(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{float(value) * 100:.2f}%"


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Pre-Contract Sandbox Filter Analysis",
        "",
        "Status: sandbox-only, not Stage 4 evidence.",
        "",
        "| Policy | Candidates | Stake | Profit | ROI | Hits | Loss reduction vs baseline |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in report["policies"]:
        lines.append(
            f"| {row['name']} | {row['candidate_count']} | {row['stake_sum']:.0f} | "
            f"{row['profit_sum']:.0f} | {_fmt_pct(row['roi'])} | {row['hit_sum']} | "
            f"{row['loss_reduction_vs_baseline']:.0f} |"
        )
    lines.extend(["", "## Interpretation", "", str(report["interpretation"]), ""])
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze conservative filters for pre-contract sandbox candidates")
    parser.add_argument("--evaluation-json", default="reports/data_collection/pre_contract_sandbox_eval_status.json")
    parser.add_argument("--output-json", default="reports/data_collection/pre_contract_sandbox_filter_analysis_status.json")
    parser.add_argument("--output-md", default="reports/data_collection/pre_contract_sandbox_filter_analysis.md")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = analyze_pre_contract_filters(
        evaluation_json=Path(args.evaluation_json),
        output_json=Path(args.output_json),
        output_md=Path(args.output_md),
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
