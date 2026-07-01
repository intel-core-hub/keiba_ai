from __future__ import annotations

import argparse
import json
import subprocess

from scripts.daily_real_data_update import run_daily_update
from scripts import daily_real_data_update


def test_daily_real_data_update_records_steps_and_calls_stage4_without_fabricating(monkeypatch, tmp_path):
    calls: list[list[str]] = []

    def fake_run(args: list[str], *, timeout_seconds: float):
        calls.append(args)
        name = args[args.index("-m") + 1]
        return {
            "args": args,
            "returncode": 1 if name == "scripts.collect_market_snapshots" else 0,
            "passed": name != "scripts.collect_market_snapshots",
            "stdout": "",
            "stderr": "provider_error" if name == "scripts.collect_market_snapshots" else "",
        }

    monkeypatch.setattr("scripts.daily_real_data_update._run", fake_run)
    args = argparse.Namespace(
        provider="local_file",
        schedule=str(tmp_path / "today_races.json"),
        odds_dir=str(tmp_path / "odds"),
        results_dir=str(tmp_path / "results"),
        baseline=str(tmp_path / "historical.csv"),
        decision_log=str(tmp_path / "decisions.jsonl"),
        derived_bets=str(tmp_path / "bets.csv"),
        feature_snapshots=str(tmp_path / "feature_snapshots"),
        early_output=str(tmp_path / "early_odds.csv"),
        closing_output=str(tmp_path / "closing_odds.csv"),
        results_output=str(tmp_path / "race_results.csv"),
        collection_status=str(tmp_path / "collection_status.json"),
        collection_errors=str(tmp_path / "collection_errors.jsonl"),
        result_status=str(tmp_path / "result_status.json"),
        result_errors=str(tmp_path / "result_errors.jsonl"),
        drift_outdir=str(tmp_path / "drift"),
        top_features="early_odds",
        status=str(tmp_path / "daily_update_status.json"),
        now=None,
        step_timeout_seconds=300.0,
    )

    report = run_daily_update(args)

    stage4_call = next(call for call in calls if "scripts.stage4_current_update" in call)
    assert report["passed"] is False
    assert "--early-snapshot" in stage4_call
    assert "--closing-snapshot" in stage4_call
    assert str(tmp_path / "early_odds.csv") in stage4_call
    assert str(tmp_path / "closing_odds.csv") in stage4_call
    saved = json.loads((tmp_path / "daily_update_status.json").read_text(encoding="utf-8"))
    assert saved["steps"][0]["passed"] is False


def test_run_marks_timed_out_step_failed(monkeypatch):
    def fake_subprocess_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=kwargs.get("args", ["python"]), timeout=1)

    monkeypatch.setattr(daily_real_data_update.subprocess, "run", fake_subprocess_run)

    result = daily_real_data_update._run(["python", "-m", "slow"], timeout_seconds=1)

    assert result["passed"] is False
    assert result["returncode"] is None
    assert result["timeout_seconds"] == 1
    assert "timed out" in result["stderr"]


def test_run_respects_child_json_passed_false(monkeypatch):
    completed = subprocess.CompletedProcess(
        args=["python", "-m", "child"],
        returncode=0,
        stdout='{"passed": false, "status": "insufficient_data"}\n',
        stderr="",
    )

    monkeypatch.setattr(daily_real_data_update.subprocess, "run", lambda *args, **kwargs: completed)

    result = daily_real_data_update._run(["python", "-m", "child"], timeout_seconds=1)

    assert result["passed"] is False
    assert result["reported_passed"] is False
    assert result["reported_status"] == "insufficient_data"
