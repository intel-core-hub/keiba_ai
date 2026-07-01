import json
import hashlib
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from learning.performance_analyzer import PerformanceAnalyzer


STATUS_PATH = Path("logs/scheduler_status.json")
BETS_PATH = Path("derived/bets.csv")
CALIBRATION_PATH = Path("models/calibration_model.pkl")


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"error": str(exc)}


def _read_recent_bets(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path).tail(25)
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


st.set_page_config(page_title="Survival Control Panel", layout="wide")
st.title("Survival OS Control Panel")
st.caption("read-only operator view")

st.warning(
    "Execution controls are disabled in Streamlit. Run the scheduler process "
    "outside the dashboard for production cycles."
)

status = _read_json(STATUS_PATH)
scheduler = status.get("scheduler", {}) if isinstance(status, dict) else {}
orchestrator = status.get("orchestrator", {}) if isinstance(status, dict) else {}

col1, col2, col3 = st.columns(3)
with col1:
    st.metric("Scheduler Running", bool(scheduler.get("running", False)))
with col2:
    st.metric("Regime", orchestrator.get("regime", "UNKNOWN"))
with col3:
    st.metric("Shutdown", bool(orchestrator.get("shutdown", False)))

st.header("Readiness")
if BETS_PATH.exists():
    st.json(PerformanceAnalyzer().analyze(str(BETS_PATH)).get("phase1_readiness", {}))
else:
    st.info("bets log unavailable")

st.header("Calibration Artifact")
st.json(_calibration_status(CALIBRATION_PATH))

st.header("Runtime Status")
if status:
    st.json(status)
else:
    st.info("scheduler status snapshot unavailable")

st.header("Recent Bets")
recent = _read_recent_bets(BETS_PATH)
if recent.empty:
    st.info("bets log unavailable")
else:
    st.dataframe(recent, use_container_width=True)

st.markdown("---")
st.caption(f"last refresh: {datetime.utcnow().isoformat()}")
