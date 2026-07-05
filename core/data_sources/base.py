from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class RaceSchedule:
    race_id: str
    race_start_at_utc: datetime
    venue: str | None
    race_number: str | None
    source: str


@dataclass(frozen=True)
class OddsRow:
    race_id: str
    horse_id: str
    odds: float
    snapshot_at_utc: datetime | None
    source: str
    provider_latency_ms: float | None = None
    raw_payload_hash: str | None = None
    bet_type: str = "win"
    legs: tuple[str, ...] = ()
    ordered: bool = False


@dataclass(frozen=True)
class ResultRow:
    race_id: str
    horse_id: str
    finish_position: int | None
    is_win: bool
    win_payout: float
    result_time_utc: datetime | None
    source: str
    provider_latency_ms: float | None = None
    raw_payload_hash: str | None = None
    bet_type: str = "win"
    legs: tuple[str, ...] = ()
    ordered: bool = False
    payout: float = 0.0


class DataProvider(ABC):
    @abstractmethod
    def list_today_races(self, target_date: date) -> list[RaceSchedule]:
        raise NotImplementedError

    @abstractmethod
    def fetch_odds(self, race_id: str) -> list[OddsRow]:
        raise NotImplementedError

    @abstractmethod
    def fetch_race_result(self, race_id: str) -> list[ResultRow]:
        raise NotImplementedError
