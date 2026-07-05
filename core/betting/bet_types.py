from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = ROOT / "config" / "bet_types.yaml"

PRODUCTION_CANDIDATE_BET_TYPES = ("win", "place", "wide")
SHADOW_ONLY_BET_TYPES = ("quinella", "trio", "wakuren")
DISABLED_BET_TYPES = ("exacta", "trifecta")
SUPPORTED_BET_TYPES = PRODUCTION_CANDIDATE_BET_TYPES + SHADOW_ONLY_BET_TYPES + DISABLED_BET_TYPES

_ALIASES = {
    "win": "win",
    "tansho": "win",
    "単勝": "win",
    "place": "place",
    "fukusho": "place",
    "複勝": "place",
    "wide": "wide",
    "ワイド": "wide",
    "quinella": "quinella",
    "umaren": "quinella",
    "馬連": "quinella",
    "trio": "trio",
    "sanrenpuku": "trio",
    "三連複": "trio",
    "wakuren": "wakuren",
    "bracket_quinella": "wakuren",
    "枠連": "wakuren",
    "exacta": "exacta",
    "umatan": "exacta",
    "馬単": "exacta",
    "trifecta": "trifecta",
    "sanrentan": "trifecta",
    "三連単": "trifecta",
}


class BetTypeMode(str, Enum):
    PRODUCTION_CANDIDATE = "production_candidate"
    SHADOW_ONLY = "shadow_only"
    DISABLED = "disabled"


@dataclass(frozen=True)
class BetTypeConfig:
    bet_type: str
    enabled: bool
    production_candidate: bool
    shadow_only: bool
    ordered: bool
    legs: int
    max_fraction_multiplier: float = 1.0
    max_race_exposure_share: float = 1.0
    max_combinations_per_race: int = 1
    disable_if_roi_below: float | None = None
    disable_if_profit_factor_below: float | None = None
    disable_if_dd_contribution_above: float | None = None
    reason: str = ""

    @property
    def mode(self) -> BetTypeMode:
        if not self.enabled:
            return BetTypeMode.DISABLED
        if self.shadow_only:
            return BetTypeMode.SHADOW_ONLY
        if self.production_candidate:
            return BetTypeMode.PRODUCTION_CANDIDATE
        return BetTypeMode.DISABLED


@dataclass(frozen=True)
class BetCandidate:
    race_id: str
    bet_type: str
    legs: tuple[str, ...]
    ordered: bool
    odds: float
    stake: float
    shadow_only: bool
    production_candidate: bool
    source: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(
        cls,
        row: Mapping[str, Any],
        *,
        registry: "BetTypeRegistry | None" = None,
        source: str | None = None,
    ) -> "BetCandidate":
        registry = registry or default_registry()
        normalized = normalize_legacy_win_record(row, registry=registry)
        bet_type = normalized["bet_type"]
        config = registry.get(bet_type)
        legs = normalize_legs(bet_type, normalized["legs"])
        candidate = cls(
            race_id=str(normalized.get("race_id") or ""),
            bet_type=bet_type,
            legs=legs,
            ordered=config.ordered,
            odds=_float(normalized.get("odds"), field="odds"),
            stake=_float(normalized.get("stake", 0.0), field="stake"),
            shadow_only=config.shadow_only,
            production_candidate=config.production_candidate,
            source=str(source or normalized.get("source") or row.get("source") or ""),
            metadata=dict(row),
        )
        validate_bet_candidate(candidate, config, field_size=int(normalized.get("field_size") or 0))
        return candidate


@dataclass(frozen=True)
class BetSettlement:
    race_id: str
    bet_type: str
    legs: tuple[str, ...]
    stake: float
    payout: float
    hit: bool
    profit: float
    payout_per_100: float | None = None
    gross_payout: float | None = None


class BetTypeRegistry:
    def __init__(self, configs: Mapping[str, BetTypeConfig]):
        self._configs = {normalize_bet_type(key): value for key, value in configs.items()}

    @classmethod
    def from_yaml(cls, path: Path) -> "BetTypeRegistry":
        return cls(load_bet_type_config(path))

    def get(self, bet_type: str) -> BetTypeConfig:
        normalized = normalize_bet_type(bet_type)
        try:
            return self._configs[normalized]
        except KeyError as exc:
            raise ValueError(f"unknown bet_type: {bet_type}") from exc

    def all(self) -> dict[str, BetTypeConfig]:
        return dict(self._configs)

    def production_candidate_bet_types(self) -> list[str]:
        return [name for name, config in self._configs.items() if config.production_candidate and config.enabled]

    def shadow_only_bet_types(self) -> list[str]:
        return [name for name, config in self._configs.items() if config.shadow_only and config.enabled]

    def disabled_bet_types(self) -> list[str]:
        return [name for name, config in self._configs.items() if not config.enabled]


_DEFAULT_REGISTRY: BetTypeRegistry | None = None


def default_registry() -> BetTypeRegistry:
    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is None:
        _DEFAULT_REGISTRY = BetTypeRegistry.from_yaml(DEFAULT_CONFIG_PATH)
    return _DEFAULT_REGISTRY


def load_bet_type_config(path: Path) -> dict[str, BetTypeConfig]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw_configs = payload.get("bet_types")
    if not isinstance(raw_configs, dict):
        raise ValueError("bet_types config must contain a bet_types mapping")

    configs: dict[str, BetTypeConfig] = {}
    for raw_name, raw_config in raw_configs.items():
        if not isinstance(raw_config, dict):
            raise ValueError(f"bet_types.{raw_name} must be a mapping")
        bet_type = normalize_bet_type(str(raw_name))
        config = BetTypeConfig(
            bet_type=bet_type,
            enabled=bool(raw_config.get("enabled", False)),
            production_candidate=bool(raw_config.get("production_candidate", False)),
            shadow_only=bool(raw_config.get("shadow_only", False)),
            ordered=bool(raw_config.get("ordered", False)),
            legs=int(raw_config.get("legs", 0) or 0),
            max_fraction_multiplier=float(raw_config.get("max_fraction_multiplier", 1.0) or 1.0),
            max_race_exposure_share=float(raw_config.get("max_race_exposure_share", 1.0) or 1.0),
            max_combinations_per_race=int(raw_config.get("max_combinations_per_race", 1) or 1),
            disable_if_roi_below=_optional_float(raw_config.get("disable_if_roi_below")),
            disable_if_profit_factor_below=_optional_float(raw_config.get("disable_if_profit_factor_below")),
            disable_if_dd_contribution_above=_optional_float(raw_config.get("disable_if_dd_contribution_above")),
            reason=str(raw_config.get("reason") or ""),
        )
        _validate_config(config)
        configs[bet_type] = config

    missing = sorted(set(SUPPORTED_BET_TYPES) - set(configs))
    if missing:
        raise ValueError(f"bet_types config missing required bet types: {missing}")
    return configs


def normalize_bet_type(value: str) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    normalized = _ALIASES.get(text)
    if normalized is None:
        raise ValueError(f"unknown bet_type: {value}")
    return normalized


def normalize_legs(bet_type: str, legs: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    normalized_type = normalize_bet_type(bet_type)
    cleaned = tuple(str(leg).strip() for leg in legs if str(leg).strip())
    if len(cleaned) != len(set(cleaned)):
        raise ValueError("duplicate legs are not allowed")
    if is_ordered_bet_type(normalized_type):
        return cleaned
    return tuple(sorted(cleaned))


def is_ordered_bet_type(bet_type: str) -> bool:
    return bool(default_registry().get(bet_type).ordered)


def validate_bet_candidate(candidate: BetCandidate, config: BetTypeConfig, field_size: int) -> None:
    bet_type = normalize_bet_type(candidate.bet_type)
    if bet_type != config.bet_type:
        raise ValueError(f"candidate bet_type {bet_type} does not match config {config.bet_type}")
    if not config.enabled:
        raise ValueError(f"disabled bet_type is not allowed as candidate: {bet_type}")
    if candidate.legs != normalize_legs(bet_type, list(candidate.legs)):
        raise ValueError("candidate legs are not normalized")
    if len(candidate.legs) != config.legs:
        raise ValueError(f"{bet_type} requires {config.legs} legs")
    if len(set(candidate.legs)) != len(candidate.legs):
        # NOTE: this also excludes same-bracket wakuren pairs (zorome);
        # supporting those requires lifting the duplicate ban for wakuren only.
        raise ValueError("duplicate legs are not allowed")
    if bet_type == "wakuren":
        for leg in candidate.legs:
            if not str(leg).isdigit() or not 1 <= int(leg) <= 8:
                raise ValueError(f"wakuren legs must be bracket numbers 1-8: {leg}")
    if field_size and len(candidate.legs) > field_size:
        raise ValueError("legs exceed field_size")
    if float(candidate.odds) <= 0:
        raise ValueError("odds must be positive")
    if float(candidate.stake) < 0:
        raise ValueError("stake must be non-negative")
    if bool(candidate.shadow_only) != bool(config.shadow_only):
        raise ValueError("candidate shadow_only does not match bet type config")
    if bool(candidate.production_candidate) != bool(config.production_candidate):
        raise ValueError("candidate production_candidate does not match bet type config")


def validate_bet_type_exposure(
    candidates: Iterable[BetCandidate],
    *,
    bankroll: float,
    registry: BetTypeRegistry | None = None,
    clamp: bool = True,
) -> tuple[list[BetCandidate], list[dict[str, Any]]]:
    registry = registry or default_registry()
    accepted: list[BetCandidate] = []
    rejected: list[dict[str, Any]] = []
    by_key: dict[tuple[str, str], list[BetCandidate]] = {}
    for candidate in candidates:
        key = (candidate.race_id, normalize_bet_type(candidate.bet_type))
        by_key.setdefault(key, []).append(candidate)

    for (race_id, bet_type), items in by_key.items():
        config = registry.get(bet_type)
        sorted_items = list(items)
        for index, candidate in enumerate(sorted_items, start=1):
            if index > config.max_combinations_per_race:
                rejected.append(
                    {
                        "race_id": race_id,
                        "bet_type": bet_type,
                        "legs": list(candidate.legs),
                        "reason": "max_combinations_per_race_exceeded",
                    }
                )
                continue
            max_stake = max(0.0, float(bankroll) * float(config.max_race_exposure_share))
            stake = min(float(candidate.stake), max_stake) if clamp else float(candidate.stake)
            if stake > max_stake:
                rejected.append(
                    {
                        "race_id": race_id,
                        "bet_type": bet_type,
                        "legs": list(candidate.legs),
                        "reason": "max_race_exposure_share_exceeded",
                    }
                )
                continue
            if stake != candidate.stake:
                candidate = BetCandidate(
                    race_id=candidate.race_id,
                    bet_type=candidate.bet_type,
                    legs=candidate.legs,
                    ordered=candidate.ordered,
                    odds=candidate.odds,
                    stake=stake,
                    shadow_only=candidate.shadow_only,
                    production_candidate=candidate.production_candidate,
                    source=candidate.source,
                    metadata={**candidate.metadata, "risk_clamped": True},
                )
            accepted.append(candidate)
    return accepted, rejected


def apply_fraction_multiplier(stake: float, bet_type: str, registry: BetTypeRegistry | None = None) -> float:
    registry = registry or default_registry()
    config = registry.get(bet_type)
    return max(0.0, float(stake) * float(config.max_fraction_multiplier))


def evaluate_hit(
    bet_type: str,
    legs: list[str],
    finish_positions: dict[str, int],
    *,
    brackets: Mapping[str, int] | None = None,
) -> bool:
    normalized = normalize_bet_type(bet_type)
    normalized_legs = normalize_legs(normalized, legs)
    positions = {str(horse_id): int(position) for horse_id, position in finish_positions.items()}
    if normalized == "wakuren":
        # legs are bracket numbers (1-8), not horse ids; settlement needs the
        # horse-to-bracket mapping and must fail closed without it.
        if brackets is None:
            raise ValueError("wakuren settlement requires a horse-to-bracket mapping")
        bracket_of = {str(horse_id): int(bracket) for horse_id, bracket in brackets.items()}
        top_two = [horse for horse, position in positions.items() if position in (1, 2)]
        if len(top_two) != 2 or any(horse not in bracket_of for horse in top_two):
            return False
        result_pair = sorted(bracket_of[horse] for horse in top_two)
        return result_pair == sorted(int(leg) for leg in normalized_legs)
    if not normalized_legs or any(leg not in positions for leg in normalized_legs):
        return False
    leg_positions = [positions[leg] for leg in normalized_legs]

    if normalized == "win":
        return leg_positions[0] == 1
    if normalized == "place":
        return 1 <= leg_positions[0] <= 3
    if normalized == "wide":
        return len(leg_positions) == 2 and all(1 <= pos <= 3 for pos in leg_positions)
    if normalized == "quinella":
        return sorted(leg_positions) == [1, 2]
    if normalized == "trio":
        return sorted(leg_positions) == [1, 2, 3]
    if normalized == "exacta":
        ordered_positions = [positions[str(leg).strip()] for leg in legs]
        return ordered_positions == [1, 2]
    if normalized == "trifecta":
        ordered_positions = [positions[str(leg).strip()] for leg in legs]
        return ordered_positions == [1, 2, 3]
    return False


def settle_bet(
    stake: float,
    payout: float | None = None,
    hit: bool = False,
    *,
    payout_per_100: float | None = None,
    gross_payout: float | None = None,
) -> float:
    stake_value = float(stake)
    if stake_value < 0:
        raise ValueError("stake must be non-negative")
    if bool(hit):
        specified = [
            value is not None
            for value in (
                payout,
                payout_per_100,
                gross_payout,
            )
        ]
        if sum(specified) != 1:
            raise ValueError("exactly one payout, payout_per_100, or gross_payout is required for a hit settlement")
        if gross_payout is not None:
            payout_value = float(gross_payout)
        elif payout_per_100 is not None:
            per_100_value = float(payout_per_100)
            if per_100_value <= 0:
                raise ValueError("payout_per_100 must be positive for a hit settlement")
            payout_value = stake_value * per_100_value / 100.0
        else:
            payout_value = float(payout)
        if payout_value <= 0:
            raise ValueError("payout must be positive for a hit settlement")
        return payout_value - stake_value
    return -stake_value


def make_settlement(
    *,
    race_id: str,
    bet_type: str,
    legs: list[str] | tuple[str, ...],
    stake: float,
    payout: float | None = None,
    hit: bool,
    payout_per_100: float | None = None,
    gross_payout: float | None = None,
) -> BetSettlement:
    stake_value = float(stake)
    resolved_gross_payout = None
    if bool(hit):
        if gross_payout is not None:
            resolved_gross_payout = float(gross_payout)
        elif payout_per_100 is not None:
            resolved_gross_payout = stake_value * float(payout_per_100) / 100.0
        elif payout is not None:
            resolved_gross_payout = float(payout)
    return BetSettlement(
        race_id=str(race_id),
        bet_type=normalize_bet_type(bet_type),
        legs=normalize_legs(bet_type, legs),
        stake=stake_value,
        payout=float(resolved_gross_payout if resolved_gross_payout is not None else (payout or 0.0)),
        hit=bool(hit),
        profit=settle_bet(
            stake_value,
            payout,
            hit,
            payout_per_100=payout_per_100,
            gross_payout=gross_payout,
        ),
        payout_per_100=float(payout_per_100) if payout_per_100 is not None else None,
        gross_payout=resolved_gross_payout,
    )


def is_production_eligible(bet_type: str) -> bool:
    config = default_registry().get(bet_type)
    return bool(config.enabled and config.production_candidate and not config.shadow_only)


def is_shadow_only(bet_type: str) -> bool:
    config = default_registry().get(bet_type)
    return bool(config.enabled and config.shadow_only)


def is_disabled_bet_type(bet_type: str) -> bool:
    config = default_registry().get(bet_type)
    return not bool(config.enabled)


def assert_execution_allowed(bet_type: str, *, execution_status: str = "LIVE") -> None:
    normalized = normalize_bet_type(bet_type)
    config = default_registry().get(normalized)
    if not config.enabled:
        raise ValueError(f"disabled bet_type cannot enter execution: {normalized}")
    if config.shadow_only:
        raise ValueError(f"shadow_only bet_type cannot enter execution: {normalized}")
    if not config.production_candidate:
        raise ValueError(f"production_candidate=false cannot enter execution: {normalized}")
    if str(execution_status or "").upper() in {"SUBMIT", "LIVE", "BET_SUBMIT"} and not config.production_candidate:
        raise ValueError(f"execution submit rejected for bet_type: {normalized}")


def filter_execution_candidates(
    candidates: Iterable[BetCandidate | Mapping[str, Any]],
    *,
    registry: BetTypeRegistry | None = None,
) -> tuple[list[BetCandidate], list[dict[str, Any]]]:
    registry = registry or default_registry()
    accepted: list[BetCandidate] = []
    rejected: list[dict[str, Any]] = []
    for item in candidates:
        try:
            candidate = item if isinstance(item, BetCandidate) else BetCandidate.from_mapping(item, registry=registry)
            assert_execution_allowed(candidate.bet_type)
            accepted.append(candidate)
        except ValueError as exc:
            rejected.append({"candidate": item, "reason": str(exc)})
    return accepted, rejected


def normalize_legacy_win_record(
    row: Mapping[str, Any],
    *,
    registry: BetTypeRegistry | None = None,
) -> dict[str, Any]:
    registry = registry or default_registry()
    data = dict(row)
    bet_type_value = data.get("bet_type")
    legs_value = data.get("legs")

    old_win_compat = False
    if not bet_type_value:
        selection = str(data.get("horse_id") or data.get("selection_id") or data.get("selection") or "").strip()
        if not selection:
            raise ValueError("bet_type missing and legacy win selection cannot be inferred")
        data["bet_type"] = "win"
        data["legs"] = [selection]
        old_win_compat = True
    else:
        data["bet_type"] = normalize_bet_type(str(bet_type_value))
        if legs_value in (None, ""):
            selection = str(data.get("horse_id") or data.get("selection_id") or data.get("selection") or "").strip()
            if not selection:
                raise ValueError("legs missing and selection cannot be inferred")
            data["legs"] = [selection]
            old_win_compat = data["bet_type"] == "win"
        else:
            data["legs"] = parse_legs(legs_value)

    config = registry.get(data["bet_type"])
    data["legs"] = list(normalize_legs(data["bet_type"], data["legs"]))
    data["ordered"] = config.ordered
    data["shadow_only"] = config.shadow_only
    data["production_candidate"] = config.production_candidate
    data["max_combinations_per_race"] = config.max_combinations_per_race
    data["max_race_exposure_share"] = config.max_race_exposure_share
    data["old_win_compat_converted"] = old_win_compat
    if "payout_per_100" not in data and "win_payout" in data:
        data["payout_per_100"] = data.get("win_payout")
    if "payout" not in data and "win_payout" in data:
        data["payout"] = data.get("win_payout")
    return data


def parse_legs(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    if not text:
        return []
    if text.startswith("["):
        parsed = json.loads(text)
        if not isinstance(parsed, list):
            raise ValueError("legs JSON must be an array")
        return [str(item).strip() for item in parsed if str(item).strip()]
    return [part.strip() for part in text.replace("|", "-").split("-") if part.strip()]


def legs_to_json(legs: Iterable[str]) -> str:
    return json.dumps([str(leg) for leg in legs], ensure_ascii=False)


def _validate_config(config: BetTypeConfig) -> None:
    if config.bet_type not in SUPPORTED_BET_TYPES:
        raise ValueError(f"unsupported bet_type in config: {config.bet_type}")
    if config.legs <= 0:
        raise ValueError(f"{config.bet_type}.legs must be positive")
    if config.enabled and config.production_candidate and config.shadow_only:
        raise ValueError(f"{config.bet_type} cannot be both production_candidate and shadow_only")
    if not config.enabled and (config.production_candidate or config.shadow_only):
        raise ValueError(f"{config.bet_type} disabled config cannot be production or shadow")
    if config.max_fraction_multiplier < 0:
        raise ValueError(f"{config.bet_type}.max_fraction_multiplier must be non-negative")
    if config.max_race_exposure_share < 0:
        raise ValueError(f"{config.bet_type}.max_race_exposure_share must be non-negative")
    if config.max_combinations_per_race < 0:
        raise ValueError(f"{config.bet_type}.max_combinations_per_race must be non-negative")


def _float(value: Any, *, field: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric: {value}") from exc


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)
