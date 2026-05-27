# dashboard/app.py

import os
import time
import pandas as pd
import streamlit as st

from datetime import datetime

from core.system_orchestrator import (
    SystemOrchestrator
)

from core.regime_detector import (
    RegimeDetector
)

from learning.performance_analyzer import (
    PerformanceAnalyzer
)

from dashboard.execution_gap_monitor import (
    render_execution_gap_dashboard,
)


# =====================================================
# Page
# =====================================================

st.set_page_config(

    page_title="Survival OS",

    layout="wide",
)

st.title(
    "Adaptive Survival OS"
)

st.caption(
    "environment adaptive autonomous system"
)

# =====================================================
# Session State
# =====================================================

if "orchestrator" not in st.session_state:

    st.session_state.orchestrator = (
        SystemOrchestrator(
            loop_interval=60
        )
    )

if "started" not in st.session_state:

    st.session_state.started = False

# =====================================================
# Sidebar
# =====================================================

st.sidebar.title(
    "Control Panel"
)

start_button = (
    st.sidebar.button(
        "START SYSTEM"
    )
)

stop_button = (
    st.sidebar.button(
        "STOP SYSTEM"
    )
)

single_cycle_button = (
    st.sidebar.button(
        "RUN SINGLE CYCLE"
    )
)

refresh_button = (
    st.sidebar.button(
        "REFRESH"
    )
)

# =====================================================
# System Reference
# =====================================================

orchestrator = (
    st.session_state.orchestrator
)

# =====================================================
# Start
# =====================================================

if start_button:

    st.session_state.started = True

    st.success(
        "system started"
    )

# =====================================================
# Stop
# =====================================================

if stop_button:

    orchestrator.stop()

    st.session_state.started = False

    st.warning(
        "system stopped"
    )

# =====================================================
# Single Cycle
# =====================================================

if single_cycle_button:

    with st.spinner(
        "running cycle..."
    ):

        result = (
            orchestrator.run_cycle()
        )

    st.success(
        "cycle complete"
    )

    st.json(result)

# =====================================================
# Diagnostics
# =====================================================

diagnostics = (
    orchestrator.diagnostics()
)

# =====================================================
# Header Metrics
# =====================================================

col1, col2, col3, col4 = (
    st.columns(4)
)

with col1:

    st.metric(

        "Cycles",

        diagnostics[
            "cycle_count"
        ],
    )

with col2:

    st.metric(

        "Regime",

        diagnostics[
            "regime"
        ],
    )

with col3:

    st.metric(

        "Running",

        diagnostics[
            "running"
        ],
    )

with col4:

    st.metric(

        "Shutdown",

        diagnostics[
            "shutdown"
        ],
    )

# =====================================================
# Health Status
# =====================================================

st.subheader(
    "System Health"
)

health_color = "green"

if diagnostics["shutdown"]:

    health_color = "red"

elif diagnostics["regime"] in [

    "VOLATILE",

    "DRIFT",

    "WEAK_EDGE",
]:

    health_color = "orange"

st.markdown(

    f"""
    <div style="
        padding:20px;
        border-radius:10px;
        background-color:{health_color};
        color:white;
        font-size:24px;
        font-weight:bold;
    ">
        REGIME:
        {diagnostics["regime"]}
    </div>
    """,

    unsafe_allow_html=True,
)

# =====================================================
# Diagnostics Table
# =====================================================

st.subheader(
    "Diagnostics"
)

diag_df = pd.DataFrame([

    diagnostics
])

st.dataframe(

    diag_df,

    use_container_width=True,
)

# =====================================================
# Health History
# =====================================================

st.subheader(
    "Health History"
)

health = (
    orchestrator.health_history
)

if len(health) > 0:

    health_df = pd.DataFrame(
        health
    )

    st.dataframe(

        health_df,

        use_container_width=True,
    )

else:

    st.info(
        "no health history"
    )

# =====================================================
# Equity Curve
# =====================================================

st.subheader(
    "Equity Curve"
)

equity_path = (
    "logs/equity_curve.csv"
)

if os.path.exists(
    equity_path
):

    eq = pd.read_csv(
        equity_path
    )

    if "bankroll" in eq.columns:

        st.line_chart(

            eq["bankroll"]
        )

else:

    st.info(
        "equity curve unavailable"
    )

# =====================================================
# Execution Gap Monitor
# =====================================================

render_execution_gap_dashboard(
    "logs/bets.csv",
    slippage_threshold=0.10,
    recent_window=20,
)

# =====================================================
# Regime Transitions
# =====================================================

st.subheader(
    "Regime Transitions"
)

regime_detector = (
    orchestrator.regime_detector
)

history = (
    regime_detector
    .regime_history
)

if len(history) > 0:

    regime_df = pd.DataFrame(
        history
    )

    st.dataframe(

        regime_df,

        use_container_width=True,
    )

else:

    st.info(
        "no regime transitions"
    )

# =====================================================
# Recovery Diagnostics
# =====================================================

st.subheader(
    "Recovery System"
)

recovery_diag = (
    orchestrator
    .retrainer
    .diagnostics()
)

st.json(
    recovery_diag
)

# =====================================================
# Auto Loop
# =====================================================

if st.session_state.started:

    with st.spinner(
        "system loop active..."
    ):

        result = (
            orchestrator.run_cycle()
        )

        st.success(
            "cycle complete"
        )

        st.json(result)

        time.sleep(5)

        st.rerun()

# =====================================================
# Footer
# =====================================================

st.markdown("---")

st.caption(

    f"last refresh: "
    f"{datetime.utcnow().isoformat()}"
)