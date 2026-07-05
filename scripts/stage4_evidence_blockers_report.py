from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _load_optional(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    return _load(path)


def _readiness_blockers(readiness: dict[str, Any], survivability: dict[str, Any]) -> list[str]:
    if readiness:
        blockers = list(readiness.get("blocking_reasons", []))
        if not blockers and readiness.get("failures"):
            blockers = list(readiness.get("failures", []))
    else:
        blockers = list(survivability.get("blockers", []))

    production = survivability.get("production_readiness", {})
    if production.get("limited_production_rehearsal") in {"不可", "blocked"}:
        for item in survivability.get("blockers", []):
            if item == "operator preflight not passed" and item not in blockers:
                blockers.append(item)
    return blockers


def build_blockers_report(*, survivability_json: Path, output_md: Path, readiness_json: Path | None = None) -> dict[str, Any]:
    payload = _load(survivability_json)
    readiness = _load_optional(readiness_json)
    blockers = _readiness_blockers(readiness, payload)
    non_shadow = list(readiness.get("non_shadow_blockers", [])) if readiness else [
        item for item in blockers if not str(item).startswith("shadow_coverage.")
    ]
    lines = [
        "# Stage 4 Evidence Blockers",
        "",
        f"- stage: {payload.get('stage', 'UNKNOWN')}",
        f"- limited_production_rehearsal: {payload.get('production_readiness', {}).get('limited_production_rehearsal', 'UNKNOWN')}",
        f"- collapse_probability: {payload.get('collapse_probability', {}).get('range', 'UNKNOWN')}",
        f"- shadow_days: {readiness.get('shadow_days', 'UNKNOWN') if readiness else 'UNKNOWN'}",
        f"- required_shadow_days: {readiness.get('required_shadow_days', 'UNKNOWN') if readiness else 'UNKNOWN'}",
        "",
        "## Remaining Blockers",
    ]
    if blockers:
        lines.extend(f"- {item}" for item in blockers)
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Non-Shadow Blockers",
        ]
    )
    if non_shadow:
        lines.extend(f"- {item}" for item in non_shadow)
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Current Passes",
            "- replay mismatch = 0, missing hash = 0, snapshot-after-decision = 0 when replay gate is PASS",
            "- p999 and timeout_rate pass when latency gate is PASS",
            "",
            "## Canonical Evidence Policy",
            "- logs/decisions.jsonl is canonical append-only evidence",
            "- derived/bets.csv is report-only and must not be used as the replay source",
            "- synthetic fixtures are not production evidence",
        ]
    )
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"output": str(output_md), "blockers": blockers, "non_shadow_blockers": non_shadow}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Stage 4 evidence blockers summary")
    parser.add_argument("--survivability-json", default="reports/stage4/survivability_evaluation_v2.json")
    parser.add_argument("--readiness-json", default="reports/stage4/readiness_gate.json")
    parser.add_argument("--output-md", default="reports/stage4/evidence_blockers.md")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_blockers_report(
        survivability_json=Path(args.survivability_json),
        readiness_json=Path(args.readiness_json) if args.readiness_json else None,
        output_md=Path(args.output_md),
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
