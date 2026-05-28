import json
import hashlib
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from dashboard.execution_gap_monitor import render_execution_gap_dashboard
from learning.performance_analyzer import PerformanceAnalyzer


STATUS_PATH = Path("logs/scheduler_status.json")
EQUITY_PATH = Path("logs/equity_curve.csv")
BETS_PATH = Path("logs/bets.csv")
CALIBRATION_PATH = Path("models/calibration_model.pkl")


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"error": str(exc)}


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception as exc:
        return pd.DataFrame({"error": [str(exc)]})


def _calibration_status(path: Path) -> dict:
    if not path.exists():
        return {"status": "missing", "hash": "unfitted", "bytes": 0}
    size = path.stat().st_size
    if size == 0:
        return {"status": "empty", "hash": "unfitted", "bytes": 0}
    return {
        "status": "available",
        "hash": hashlib.sha256(path.read_bytes()).hexdigest()[:16],
        "bytes": size,
    }


st.set_page_config(page_title="Survival OS", layout="wide")
st.title("Adaptive Survival OS")
st.caption("monitoring dashboard")

status = _read_json(STATUS_PATH)
scheduler = status.get("scheduler", {}) if isinstance(status, dict) else {}
orchestrator = status.get("orchestrator", {}) if isinstance(status, dict) else {}

col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("Cycles", orchestrator.get("cycle_count", 0))
with col2:
    st.metric("Regime", orchestrator.get("regime", "UNKNOWN"))
with col3:
    st.metric("Scheduler", bool(scheduler.get("running", False)))
with col4:
    st.metric("Shutdown", bool(orchestrator.get("shutdown", False)))

cal_status = _calibration_status(CALIBRATION_PATH)
st.subheader("Phase 1 Readiness")
if BETS_PATH.exists():
    readiness = PerformanceAnalyzer().analyze(str(BETS_PATH)).get("phase1_readiness", {})
    r1, r2, r3, r4 = st.columns(4)
    with r1:
        st.metric("Shadow Bets", readiness.get("shadow_bets", 0))
    with r2:
        st.metric("Mean EV", readiness.get("mean_ev"))
    with r3:
        st.metric("Brier", readiness.get("brier"))
    with r4:
        st.metric("ECE", readiness.get("ece"))
    if readiness.get("ready"):
        st.success("Phase 1 complete")
    else:
        st.warning("Phase 1 incomplete")
        st.json(readiness.get("checks", {}))
else:
    st.info("bets log unavailable")

st.subheader("Calibration Artifact")
st.json(cal_status)

st.subheader("Runtime Status")
if status:
    st.json(status)
else:
    st.info("scheduler status snapshot unavailable")

st.subheader("Equity Curve")
equity = _read_csv(EQUITY_PATH)
if not equity.empty and "bankroll" in equity.columns:
    st.line_chart(equity["bankroll"])
elif not equity.empty:
    st.dataframe(equity, use_container_width=True)
else:
    st.info("equity curve unavailable")

render_execution_gap_dashboard(
    str(BETS_PATH),
    slippage_threshold=0.10,
    recent_window=20,
)

st.subheader("Recent Bets")
bets = _read_csv(BETS_PATH)
if bets.empty:
    st.info("bets log unavailable")
else:
    st.dataframe(bets.tail(50), use_container_width=True)

st.markdown("---")
st.caption(f"last refresh: {datetime.utcnow().isoformat()}")
