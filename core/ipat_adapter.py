"""Adapter that provides an IPAT-like client using environment-configured HTTP API.

This adapter attempts to use environment variables:
 - IPAT_API_URL
 - IPAT_API_KEY

If not present, it falls back to an in-memory mock implementing
`fetch_live_odds_async` and `place_bet_async` used by LowLatencyExecutionEngine.
"""
import os
import asyncio
import json
from typing import Any

try:
    import aiohttp
except Exception:
    aiohttp = None


class RealIPATClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 1.0):
        if aiohttp is None:
            raise RuntimeError("aiohttp package required for RealIPATClient")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = aiohttp.ClientTimeout(total=timeout)

    async def fetch_live_odds_async(self, race_id: str) -> Any:
        url = f"{self.base_url}/odds/{race_id}"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            async with session.get(url, headers=headers) as response:
                response.raise_for_status()
                return await response.json(content_type=None)

    async def place_bet_async(self, race_id: str, allocations: Any) -> Any:
        url = f"{self.base_url}/place_bet"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {"race_id": race_id, "allocations": allocations}
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            async with session.post(url, headers=headers, json=payload) as response:
                response.raise_for_status()
                return await response.json(content_type=None)


class MockIPATClient:
    async def fetch_live_odds_async(self, race_id: str):
        await asyncio.sleep(0)
        return {"precomputed_feature_vector": [1, 2, 3], "odds": [5.0]}

    async def place_bet_async(self, race_id: str, allocations: Any):
        await asyncio.sleep(0)
        return {"status": "ok", "race_id": race_id, "allocations": allocations}


def build_from_env() -> Any:
    # 1) Check environment variables
    url = os.environ.get("IPAT_API_URL")
    key = os.environ.get("IPAT_API_KEY")
    if url and key:
        return RealIPATClient(url, key)

    # 2) Check secrets file path (JSON with {"url":..., "key":...})
    secret_path = os.environ.get("IPAT_SECRETS_FILE")
    if secret_path and os.path.exists(secret_path):
        try:
            with open(secret_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            url = data.get("url")
            key = data.get("key")
            if url and key:
                return RealIPATClient(url, key)
        except Exception:
            pass

    # fallback to mock
    return MockIPATClient()
