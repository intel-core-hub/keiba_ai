from __future__ import annotations

import asyncio
import ast
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.circuit_breaker import SharedCircuitBreaker
from core.key_manager import KeyManager
from core.low_latency_execution import LowLatencyExecutionEngine
from core.replay.replay_engine import ReplayEngine
from schemas.decision_event import DecisionEvent, canonical_hash
from scripts.critical_path_linter import scan_file as lint_critical_path
from scripts.derive_bets_csv_from_decisions import derive as derive_bets_csv
from scripts.parse_load_artifacts import analyze_file, safe_percentiles
from scripts.runtime_import_scanner import runtime_files, scan_file as scan_runtime_imports


def test_core_init_is_side_effect_free_package_marker():
    source = (ROOT / "core" / "__init__.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden = {
        "RegimeDetector",
        "BetSizer",
        "BankrollManager",
        "DecisionEngine",
        "BetExecutor",
        "SelfDestructSystem",
        "MetaController",
        "import_module",
        "KEIBA_ENABLE_RESEARCH",
    }

    assert not any(isinstance(node, (ast.Import, ast.ImportFrom)) for node in ast.walk(tree))
    assert "__getattr__" not in source
    for token in forbidden:
        assert token not in source
    assert "__all__: list[str] = []" in source


def test_research_governance_layers_are_quarantined_out_of_core():
    assert not (ROOT / "core" / "strategy" / "executive_controller.py").exists()
    assert (ROOT / "research" / "quarantine" / "core" / "strategy" / "executive_controller.py").exists()
    assert not (ROOT / "infrastructure" / "orchestrator.py").exists()
    assert (ROOT / "research" / "quarantine" / "infrastructure" / "orchestrator.py").exists()


def test_auto_operator_has_no_evolution_hook():
    source = (ROOT / "core" / "auto_operator.py").read_text(encoding="utf-8")

    assert "evolution_engine" not in source
    assert ".evolve(" not in source
    assert "core.evolution" not in source


def test_core_runtime_does_not_import_survival_database():
    core_sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "core").rglob("*.py")
        if "__pycache__" not in path.parts
    )

    assert "from infrastructure.database" not in core_sources
    assert "SurvivalDatabase" not in core_sources


def test_import_core_does_not_load_runtime_heavy_modules():
    forbidden_modules = {
        "core.low_latency_execution",
        "core.betting.decision_engine",
        "core.execution.bet_executor",
        "core.cognition.meta_controller",
    }
    saved = {
        name: module
        for name, module in list(sys.modules.items())
        if name == "core" or name.startswith("core.")
    }
    for name in list(saved):
        del sys.modules[name]
    try:
        __import__("core")
        loaded = set(sys.modules)
        assert forbidden_modules.isdisjoint(loaded)
    finally:
        for name in list(sys.modules):
            if name == "core" or name.startswith("core."):
                del sys.modules[name]
        sys.modules.update(saved)


def test_execution_runtime_has_no_manual_input_or_buy_prints():
    execution_sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "execution").glob("*.py")
    )

    assert "input(" not in execution_sources
    assert "BUY " not in execution_sources
    assert "result_input" not in execution_sources


def _valid_event(**overrides):
    data = {
        "decision_id": "D1",
        "race_id": "R1",
        "selection_id": "H1",
        "decision_time_utc": "2026-05-30T00:00:00+00:00",
        "monotonic_ns": 123,
        "odds_snapshot_hash": "odds-hash",
        "feature_snapshot_hash": "feature-hash",
        "model_hash": "model-hash",
        "calibration_hash": "calibration-hash",
        "bankroll_hash": "bankroll-hash",
        "policy_hash": "policy-hash",
        "risk_limits_hash": "risk-hash",
        "decision": "BET",
        "reason": "edge",
        "stake": 100.0,
        "execution_status": "SHADOW",
    }
    data.update(overrides)
    return DecisionEvent(**data)


def test_runtime_import_scanner_fails_for_learning_import(tmp_path):
    target = tmp_path / "runtime_module.py"
    target.write_text("from learning.uncertainty import estimate_uncertainty\n", encoding="utf-8")

    violations = scan_runtime_imports(target)

    assert violations
    assert "learning.uncertainty" in violations[0][1]


def test_runtime_import_scanner_tracks_system_orchestrator():
    tracked = {path.relative_to(ROOT).as_posix() for path in runtime_files(ROOT)}

    assert "core/system_orchestrator.py" in tracked


def test_system_orchestrator_defers_offline_imports():
    source = (ROOT / "core" / "system_orchestrator.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    top_level_imports = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            top_level_imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            top_level_imports.append(node.module)

    assert "pandas" not in top_level_imports
    assert "data.historical_dataset" not in top_level_imports
    assert "simulation.live_simulation" not in top_level_imports


def test_key_manager_blocks_filesystem_backend_in_production(tmp_path, monkeypatch):
    monkeypatch.setenv("KEY_MANAGER_BACKEND", "file")
    monkeypatch.setenv("KEIBA_ENV", "production")
    monkeypatch.delenv("KEY_MANAGER_ALLOW_INSECURE_FILE_STORAGE", raising=False)

    with pytest.raises(RuntimeError, match="Filesystem key storage is blocked in production"):
        KeyManager(base_dir=str(tmp_path))


def test_key_manager_env_backend_reads_secret_paths(tmp_path, monkeypatch):
    private_path = tmp_path / "priv.pem"
    public_path = tmp_path / "pub.pem"
    private_path.write_text("PRIVATE", encoding="utf-8")
    public_path.write_text("PUBLIC", encoding="utf-8")
    monkeypatch.setenv("KEY_MANAGER_BACKEND", "env")
    monkeypatch.setenv("AUDIT_PRIVATE_KEY_PATH", str(private_path))
    monkeypatch.setenv("AUDIT_PUBLIC_KEY_PATH", str(public_path))

    manager = KeyManager(base_dir=str(tmp_path))

    assert manager.latest_version() == "env"
    assert manager.load_private_pem() == b"PRIVATE"
    assert manager.get_public_pem() == b"PUBLIC"


def test_critical_path_linter_ignores_offline_pandas_and_flags_runtime(tmp_path):
    offline = tmp_path / "research" / "research_script.py"
    offline.parent.mkdir()
    offline.write_text("import pandas as pd\npd.DataFrame([])\n", encoding="utf-8")
    runtime = tmp_path / "runtime.py"
    runtime.write_text(
        "async def execute_critical_path():\n"
        "    import pandas as pd\n"
        "    pd.DataFrame([])\n",
        encoding="utf-8",
    )

    assert lint_critical_path(offline) == []
    violations = lint_critical_path(runtime)
    assert any("pandas import" in item[1] for item in violations)
    assert any("DataFrame usage" in item[1] for item in violations)


def test_critical_path_linter_flags_hidden_async_task_and_sleep(tmp_path):
    runtime = tmp_path / "runtime.py"
    runtime.write_text(
        "import asyncio\n"
        "import time\n"
        "async def execute_critical_path():\n"
        "    asyncio.create_task(other())\n"
        "    time.sleep(1)\n",
        encoding="utf-8",
    )

    violations = lint_critical_path(runtime)

    assert any("hidden async task creation" in item[1] for item in violations)
    assert any("sleep usage" in item[1] for item in violations)


def test_critical_path_linter_flags_riskclamp_bypass_patterns(tmp_path):
    runtime = tmp_path / "runtime.py"
    runtime.write_text(
        "def evaluate_candidate(self):\n"
        "    if not self.risk_manager.can_bet():\n"
        "        return None\n"
        "    if self.risk_manager.risk_multiplier() <= 0:\n"
        "        return None\n"
        "    decision = {'should_bet': True}\n"
        "    if decision.get('should_bet'):\n"
        "        return 'BET'\n",
        encoding="utf-8",
    )

    violations = lint_critical_path(runtime)

    assert any("RiskClamp bypass" in item[1] for item in violations)


def test_critical_path_linter_flags_submit_without_riskclamp_guard(tmp_path):
    runtime = tmp_path / "runtime.py"
    runtime.write_text(
        "def execute_bet(self):\n"
        "    return self._execute_real_vote({})\n",
        encoding="utf-8",
    )

    violations = lint_critical_path(runtime)

    assert any("submit without RiskClamp guard" in item[1] for item in violations)


def test_critical_path_linter_flags_place_bet_without_allowed_guard(tmp_path):
    runtime = tmp_path / "runtime.py"
    runtime.write_text(
        "async def execute_critical_path(self):\n"
        "    bet_decision = {'allowed': True}\n"
        "    await self.ipat_client.place_bet_async('R1', [])\n",
        encoding="utf-8",
    )

    violations = lint_critical_path(runtime)

    assert any("submit without RiskClamp guard" in item[1] for item in violations)


def test_critical_path_linter_flags_submit_alias_without_guard(tmp_path):
    runtime = tmp_path / "runtime.py"
    runtime.write_text(
        "def execute_bet(self):\n"
        "    submit = self._execute_real_vote\n"
        "    return submit({})\n",
        encoding="utf-8",
    )

    violations = lint_critical_path(runtime)

    assert any("submit without RiskClamp guard" in item[1] for item in violations)


def test_critical_path_linter_flags_approved_branch_without_riskclamp_guard(tmp_path):
    runtime = tmp_path / "runtime.py"
    runtime.write_text(
        "def execute_bet(self, decision):\n"
        "    if decision.approved:\n"
        "        return self._execute_real_vote({})\n",
        encoding="utf-8",
    )

    violations = lint_critical_path(runtime)

    assert any("submit without RiskClamp guard" in item[1] for item in violations)


def test_critical_path_linter_flags_submit_before_late_guard(tmp_path):
    runtime = tmp_path / "runtime.py"
    runtime.write_text(
        "def execute_bet(self):\n"
        "    result = self._execute_real_vote({})\n"
        "    risk_result = self.risk_clamp.evaluate(risk_input)\n"
        "    if not risk_result.allowed:\n"
        "        return {'blocked': True}\n"
        "    return result\n",
        encoding="utf-8",
    )

    violations = lint_critical_path(runtime)

    assert any("submit without RiskClamp guard" in item[1] for item in violations)


def test_critical_path_linter_allows_explicit_riskclamp_guard(tmp_path):
    runtime = tmp_path / "runtime.py"
    runtime.write_text(
        "def execute_bet(self):\n"
        "    risk_result = self.risk_clamp.evaluate(risk_input)\n"
        "    if not risk_result.allowed:\n"
        "        return {'blocked': True}\n"
        "    return self._execute_real_vote({})\n",
        encoding="utf-8",
    )

    assert lint_critical_path(runtime) == []


def test_critical_path_linter_allows_current_critical_submit_paths():
    low_latency = ROOT / "core" / "low_latency_execution.py"
    bet_executor = ROOT / "core" / "execution" / "bet_executor.py"

    low_latency_violations = [
        item for item in lint_critical_path(low_latency)
        if "submit without RiskClamp guard" in item[1]
    ]
    executor_violations = [
        item for item in lint_critical_path(bet_executor)
        if "submit without RiskClamp guard" in item[1]
    ]

    assert low_latency_violations == []
    assert executor_violations == []


def test_parse_load_artifacts_reports_p999_from_latency_list(tmp_path):
    path = tmp_path / "load_test_sample.json"
    path.write_text(json.dumps({"latencies_ms": [1, 2, 3, 4, 1000]}), encoding="utf-8")

    _, status, data = analyze_file(path)

    assert status == "ok"
    assert data["p999"] == 1000.0


def test_safe_percentiles_uses_deterministic_nearest_rank_for_small_samples():
    values = safe_percentiles([10, 20])

    assert values[50] == 10
    assert values[95] == 20
    assert values[99] == 20
    assert values[99.9] == 20


def _python_env():
    env = os.environ.copy()
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(ROOT) if not existing else str(ROOT) + os.pathsep + existing
    return env


def test_load_test_cli_writes_strict_ci_latency_artifact(tmp_path):
    output = tmp_path / ".ci_latency.json"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.load_test",
            "1",
            "2",
            "--mock-only",
            "--ci-output",
            str(output),
        ],
        cwd=tmp_path,
        env=_python_env(),
        text=True,
        capture_output=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert set(payload) == {"p50", "p95", "p99", "p999", "timeout_rate"}
    assert payload["timeout_rate"] == 0.0


def test_load_test_ci_output_fails_closed_without_samples(tmp_path):
    output = tmp_path / ".ci_latency.json"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.load_test",
            "0",
            "0",
            "--mock-only",
            "--ci-output",
            str(output),
        ],
        cwd=tmp_path,
        env=_python_env(),
        text=True,
        capture_output=True,
        timeout=30,
    )

    assert result.returncode != 0
    assert not output.exists()


def test_load_test_ci_payload_records_timeout_rate(tmp_path):
    output = tmp_path / ".ci_latency.json"
    code = (
        "from scripts.load_test import write_ci_latency_payload; "
        f"write_ci_latency_payload({str(output)!r}, [10.0, 20.0], 1)"
    )

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=_python_env(),
        text=True,
        capture_output=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["p999"] == 20.0
    assert payload["timeout_rate"] == 0.5


def test_governance_workflow_generates_latency_artifact_before_pytest():
    workflow = (ROOT / ".github" / "workflows" / "governance.yml").read_text(encoding="utf-8")

    latency_cmd = "python -m scripts.load_test 2 10 --mock-only --ci-output .ci_latency.json"
    pytest_cmd = "pytest -q"
    assert latency_cmd in workflow
    assert workflow.index(latency_cmd) < workflow.index(pytest_cmd)


def test_governance_workflow_runs_stage4_gate_only_when_evidence_exists():
    workflow = (ROOT / ".github" / "workflows" / "governance.yml").read_text(encoding="utf-8")

    assert "results/market_dependency/odds_perturbation_summary.csv" in workflow
    assert "python -m scripts.stage4_readiness_gate --replay-report reports/stage4/replay_report.json --require-replay-report" in workflow
    assert "Skipping Stage 4 readiness gate; evidence artifacts not present." in workflow
    assert workflow.index("pytest -q") < workflow.index("python -m scripts.stage4_readiness_gate")


def test_stage4_release_workflow_uses_mandatory_evidence_bundle_and_gate():
    workflow = (ROOT / ".github" / "workflows" / "stage4_release_gate.yml").read_text(encoding="utf-8")

    assert "workflow_dispatch" in workflow
    assert "python -m scripts.derive_bets_csv_from_decisions" in workflow
    assert "python -m scripts.market_dependency_report" in workflow
    assert "python -m scripts.bet_type_metrics_report" in workflow
    assert "python -m scripts.stage4_evidence_bundle" in workflow
    assert "python -m scripts.stage4_readiness_gate" in workflow
    assert "python -m scripts.stage4_rubric_v2_3_report" in workflow
    assert "--bet-type-metrics reports/stage4/bet_type_metrics.json" in workflow
    assert "--output-json reports/stage4/rubric_v2_3_compliance.json" in workflow
    assert "--require-replay-report" in workflow
    assert workflow.index("python -m scripts.derive_bets_csv_from_decisions") < workflow.index("python -m scripts.market_dependency_report")
    assert workflow.index("python -m scripts.market_dependency_report") < workflow.index("python -m scripts.stage4_readiness_gate")
    assert workflow.index("python -m scripts.stage4_readiness_gate") < workflow.index("python -m scripts.bet_type_metrics_report")
    assert workflow.index("python -m scripts.bet_type_metrics_report") < workflow.index("python -m scripts.stage4_rubric_v2_3_report")
    assert workflow.index("python -m scripts.stage4_readiness_gate") < workflow.index("python -m scripts.stage4_rubric_v2_3_report")
    assert workflow.index("python -m scripts.stage4_rubric_v2_3_report") < workflow.index("python -m scripts.stage4_evidence_bundle")


def test_stage4_release_workflow_uploads_evidence_artifacts_after_gate():
    workflow = (ROOT / ".github" / "workflows" / "stage4_release_gate.yml").read_text(encoding="utf-8")

    assert "actions/upload-artifact@v4" in workflow
    assert "stage4-release-evidence" in workflow
    assert "reports/stage4/*" in workflow
    assert "results/market_dependency/*" in workflow
    assert "derived/bets.csv" in workflow
    assert workflow.index("python -m scripts.stage4_evidence_bundle") < workflow.index("actions/upload-artifact@v4")


def test_stage4_runbook_documents_release_rehearsal_contract():
    runbook = (ROOT / "docs" / "STAGE4_RELEASE_REHEARSAL_RUNBOOK.md").read_text(encoding="utf-8")

    required_text = [
        "logs/decisions.jsonl",
        "derived/bets.csv",
        "reports/stage4/readiness_gate.json",
        "not Production Safe",
        "python -m scripts.derive_bets_csv_from_decisions",
        "python -m scripts.market_dependency_report",
        "python -m scripts.stage4_evidence_bundle",
        "python -m scripts.stage4_readiness_gate",
        "closing_odds is a contamination check",
    ]
    for text in required_text:
        assert text in runbook


def test_stage4_preflight_template_has_all_required_checks():
    from scripts.stage4_rehearsal_evidence import PREFLIGHT_CHECKS

    template = json.loads((ROOT / "reports" / "stage4" / "preflight_status.example.json").read_text(encoding="utf-8"))

    expected = set(PREFLIGHT_CHECKS) - {"stage4_release_gate_passed"}
    assert set(template) == expected | {"evidence_paths"}
    assert all(template[key] is False for key in expected)
    assert set(template["evidence_paths"]) == {
        "kill_switch",
        "manual_override",
        "max_exposure_cap",
        "bankroll_reconciliation",
        "tax_audit_export",
    }


def test_derive_bets_csv_from_canonical_decisions_jsonl(tmp_path):
    decisions = tmp_path / "decisions.jsonl"
    derived = tmp_path / "derived" / "bets.csv"
    decisions.write_text(
        json.dumps({
            "event_id": "evt-1",
            "event_type": "BetSubmitted",
            "occurred_at_utc": "2026-05-30T00:00:00Z",
            "race_id": "R1",
            "previous_hash": "previous-hash",
            "payload": {
                "decision_id": "decision-1",
                "decision_time_utc": "2026-05-30T00:00:00Z",
                "race_id": "R1",
                "selection": "H1",
                "probability": 0.2,
                "stake": 100,
                "bankroll_hash": "bankroll-hash",
                "feature_snapshot_hash": "feature-hash",
                "odds_snapshot_hash": "odds-hash",
                "policy_hash": "policy-hash",
                "risk_limits_hash": "risk-hash",
                "execution_status": "SHADOW",
                "safe_mode": True,
                "shadow_mode": True,
            },
            "entry_hash": "entry-hash",
        }) + "\n",
        encoding="utf-8",
    )

    count = derive_bets_csv(decisions, derived)

    assert count == 1
    rows = derived.read_text(encoding="utf-8").splitlines()
    assert "race_id" in rows[0]
    assert "risk_limits_hash" in rows[0]
    for field in [
        "decision_id",
        "decision_time_utc",
        "event_id",
        "event_type",
        "occurred_at_utc",
        "entry_hash",
        "previous_hash",
        "bankroll_hash",
        "feature_snapshot_hash",
        "odds_snapshot_hash",
        "policy_hash",
        "execution_status",
        "safe_mode",
        "shadow_mode",
    ]:
        assert field in rows[0]
    assert "R1" in rows[1]
    assert "entry-hash" in rows[1]


def test_dashboard_defaults_do_not_read_legacy_bets_csv():
    dashboard_files = [
        ROOT / "dashboard" / "app.py",
        ROOT / "dashboard" / "control_panel.py",
        ROOT / "dashboard" / "execution_gap_monitor.py",
        ROOT / "dashboard" / "streamlit_app.py",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in dashboard_files)

    assert "logs/bets.csv" not in combined
    assert "derived/bets.csv" in combined


def test_reporting_defaults_do_not_use_legacy_bets_csv_as_source():
    files = [
        ROOT / "scripts" / "policy_comparator.py",
        ROOT / "scripts" / "alternative_policy_runner.py",
        ROOT / "scripts" / "bankroll_path_simulator.py",
        ROOT / "scripts" / "counterfactual_replay.py",
        ROOT / "scripts" / "admin_portfolio_summary.py",
        ROOT / "tools" / "survival_analysis.py",
        ROOT / "execution" / "phase2_loop.py",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in files)

    assert "logs/bets.csv" not in combined
    assert "logs/decisions.jsonl" in combined
    assert "derived/bets.csv" in combined


def test_decision_event_validates_and_hashes_deterministically():
    event = _valid_event().validate()
    clone = DecisionEvent(**dict(reversed(list(event.to_dict().items())))).validate()

    assert event.canonical_hash() == clone.canonical_hash()
    assert canonical_hash({"b": 2, "a": 1}) == canonical_hash({"a": 1, "b": 2})


@pytest.mark.parametrize(
    "overrides",
    [
        {"odds_snapshot_hash": ""},
        {"decision": "MAYBE"},
        {"stake": -1},
        {"decision_time_utc": "2026-05-30T00:00:00"},
    ],
)
def test_decision_event_rejects_invalid_events(overrides):
    with pytest.raises(ValueError):
        _valid_event(**overrides).validate()


class _Column:
    def __init__(self, value):
        self.value = value

    def max(self):
        return self.value


class _Snapshot:
    empty = False

    def __init__(self, timestamp):
        self.timestamp = timestamp

    def __getitem__(self, key):
        assert key == "timestamp"
        return _Column(self.timestamp)


class _ReplayLoader:
    timestamp_col = "timestamp"

    def __init__(self, *, missing_features=False, missing_odds=False):
        self.missing_features = missing_features
        self.missing_odds = missing_odds

    def get_latest_odds(self, as_of, race_id=None):
        return None if self.missing_odds else _Snapshot(as_of)

    def get_latest_features(self, as_of, entity_id=None):
        return None if self.missing_features else _Snapshot(as_of)

    def get_calibration_state(self, as_of):
        return _Snapshot(as_of)


def test_replay_gate_passes_clean_jsonl(tmp_path):
    path = tmp_path / "decisions.jsonl"
    payload = _valid_event().to_dict()
    path.write_text(json.dumps({"event": "bet_executed", "payload": payload}) + "\n", encoding="utf-8")
    replay = ReplayEngine(loader=_ReplayLoader())

    report = replay.replay(path)
    replay.raise_on_failures(report)

    assert report["summary"]["anomaly_count"] == 0


@pytest.mark.parametrize(
    "payload_update,loader,summary_key",
    [
        ({"feature_snapshot_hash": ""}, _ReplayLoader(), "missing_hash"),
        ({"model_hash": "old", "active_model_hash": "new"}, _ReplayLoader(), "replay_mismatch_count"),
        ({"calibration_hash": "old", "active_calibration_hash": "new"}, _ReplayLoader(), "replay_mismatch_count"),
        ({"bankroll_hash": "old", "active_bankroll_hash": "new"}, _ReplayLoader(), "replay_mismatch_count"),
        ({}, _ReplayLoader(missing_odds=True), "missing_hash"),
    ],
)
def test_replay_gate_fails_on_anomalies(tmp_path, payload_update, loader, summary_key):
    path = tmp_path / "decisions.jsonl"
    payload = _valid_event().to_dict()
    payload.update(payload_update)
    path.write_text(json.dumps({"event": "bet_executed", "payload": payload}) + "\n", encoding="utf-8")
    replay = ReplayEngine(loader=loader)

    report = replay.replay(path)

    assert report["summary"][summary_key] > 0
    with pytest.raises(RuntimeError):
        replay.raise_on_failures(report)


def test_replay_engine_rejects_csv(tmp_path):
    replay = ReplayEngine(loader=_ReplayLoader())
    with pytest.raises(ValueError, match="JSONL"):
        replay.replay(tmp_path / "decisions.csv")


class _Predictor:
    def predict(self, *args, **kwargs):
        return 0.2


class _Risk:
    def calculate_sizing(self, *args, **kwargs):
        return {"should_bet": True, "allocations": [{"horse": "H1", "amount": 100}]}


class _IPAT:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.placed = False

    async def fetch_live_odds_async(self, race_id):
        return self.snapshot

    async def place_bet_async(self, race_id, allocations):
        self.placed = True
        return {"status": "submitted"}


async def _run_engine(snapshot, risk=None):
    breaker = SharedCircuitBreaker(failure_threshold=99, recovery_timeout=60)
    ipat = _IPAT(snapshot)
    engine = LowLatencyExecutionEngine(
        predictor=_Predictor(),
        risk_manager=risk or _Risk(),
        ipat_client=ipat,
        circuit_breaker=breaker,
        staleness_threshold=1.0,
        max_clock_skew_ms=500,
    )
    result = await engine.execute_critical_path("R1", timeout_sec=0.2)
    return result, breaker, ipat


def _fresh_snapshot(**overrides):
    snapshot = {
        "timestamp": time.time(),
        "odds": [5.0],
        "precomputed_feature_vector": [{"rank_score": 0.8}],
        "calibration_state": {"expired": False},
        "bankroll_state": {"uncertain": False},
    }
    snapshot.update(overrides)
    return snapshot


@pytest.mark.parametrize(
    "snapshot_factory,reason,breaker_reason",
    [
        (lambda: _fresh_snapshot(timestamp=time.time() - 10), "stale_odds", "STALE_ODDS"),
        (lambda: _fresh_snapshot(precomputed_feature_vector=None), "stale_features", "STALE_FEATURES"),
        (lambda: _fresh_snapshot(calibration_state={"expired": True}), "calibration_expired", "CALIBRATION_EXPIRED"),
        (lambda: _fresh_snapshot(bankroll_state={"uncertain": True}), "bankroll_uncertain", "BANKROLL_STATE_UNCERTAIN"),
        (lambda: _fresh_snapshot(clock_skew_ms=2_000), "clock_skew", "CLOCK_SKEW"),
        (lambda: _fresh_snapshot(race_cancelled=True), "race_cancelled", "RACE_CANCELLED"),
    ],
)
def test_stale_state_forces_no_bet(snapshot_factory, reason, breaker_reason):
    result, breaker, ipat = asyncio.run(_run_engine(snapshot_factory()))

    assert result["decision"] == "NO_BET"
    assert result["reason"] == reason
    assert result["breaker_reason"] == breaker_reason
    assert breaker.reason == breaker_reason
    assert not ipat.placed
