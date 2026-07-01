"""Offline evidence data-source interfaces for real-data collection."""

from __future__ import annotations

from core.data_sources.base import DataProvider, OddsRow, RaceSchedule, ResultRow
from core.data_sources.http_provider import HTTPProvider, HTTPProviderConfig

__all__ = [
    "DataProvider",
    "HTTPProvider",
    "HTTPProviderConfig",
    "OddsRow",
    "RaceSchedule",
    "ResultRow",
]
