# dashboard/control_panel.py

import os
import shutil
import streamlit as st

from datetime import datetime

from core.system_orchestrator import (
    SystemOrchestrator
)

# =====================================================
# Page
# =====================================================

st.set_page_config(

    page_title="Survival Control Panel",

    layout="wide",
)

st.title(
    "Survival OS Control Panel"
)

st.caption(
    "human intervention layer"
)

# =====================================================
# Session
# =====================================================

if "orchestrator" not in st.session_state:

    st.session_state.orchestrator = (
        SystemOrchestrator()
    )

orchestrator = (
    st.session_state.orchestrator
)

# =====================================================
# Emergency Controls
# =====================================================

st.header(
    "Emergency Controls"
)

col1, col2, col3 = st.columns(3)

# =====================================================
# Shutdown
# =====================================================

with col1:

    if st.button(
        "EMERGENCY SHUTDOWN"
    ):

        orchestrator.shutdown = True

        orchestrator.stop()

        st.error(
            "SYSTEM SHUTDOWN"
        )

# =====================================================
# Resume
# =====================================================

with col2:

    if st.button(
        "RESUME SYSTEM"
    ):

        orchestrator.shutdown = False

        orchestrator.running = True

        st.success(
            "SYSTEM RESUMED"
        )

# =====================================================
# Safe Mode
# =====================================================

with col3:

    if st.button(
        "SAFE MODE"
    ):

        orchestrator.regime_detector.current_regime = (
            "WEAK_EDGE"
        )

        st.warning(
            "SAFE MODE ENABLED"
        )

# =====================================================
# Regime Override
# =====================================================

st.header(
    "Regime Override"
)

override = st.selectbox(

    "Force Regime",

    [

        "NORMAL",

        "FAVORABLE",

        "VOLATILE",

        "WEAK_EDGE",

        "DRIFT",

        "COLLAPSE",
    ]
)

if st.button(
    "APPLY REGIME"
):

    old = (
        orchestrator
        .regime_detector
        .current_regime
    )

    orchestrator.regime_detector.current_regime = (
        override
    )

    orchestrator.regime_detector.regime_history.append({

        "timestamp":
            datetime.utcnow()
            .isoformat(),

        "old":
            old,

        "new":
            override,

        "manual":
            True,
    })

    st.success(
        f"{old} -> {override}"
    )

# =====================================================
# Retraining Controls
# =====================================================

st.header(
    "Retraining"
)

if st.button(
    "FORCE RETRAIN"
):

    with st.spinner(
        "retraining..."
    ):

        result = (

            orchestrator
            .retrainer
            .retrain()
        )

    st.json(result)

# =====================================================
# Rollback
# =====================================================

st.header(
    "Rollback"
)

backup_dir = (
    "models/backups"
)

backups = []

if os.path.exists(
    backup_dir
):

    backups = sorted(

        os.listdir(
            backup_dir
        ),

        reverse=True,
    )

selected_backup = st.selectbox(

    "Backup Model",

    backups
)

if st.button(
    "ROLLBACK MODEL"
):

    if selected_backup:

        src = os.path.join(

            backup_dir,

            selected_backup,
        )

        dst = (
            "models/"
            "predictor.pkl"
        )

        shutil.copy2(
            src,
            dst,
        )

        st.success(
            f"rollback -> "
            f"{selected_backup}"
        )

# =====================================================
# Run Single Cycle
# =====================================================

st.header(
    "Manual Cycle"
)

if st.button(
    "RUN SINGLE CYCLE"
):

    with st.spinner(
        "running..."
    ):

        result = (
            orchestrator.run_cycle()
        )

    st.json(result)

# =====================================================
# Current Status
# =====================================================

st.header(
    "Current Status"
)

diag = (
    orchestrator.diagnostics()
)

st.json(diag)

# =====================================================
# Regime Diagnostics
# =====================================================

st.header(
    "Regime Diagnostics"
)

regime_diag = (

    orchestrator
    .regime_detector
    .diagnostics()
)

st.json(
    regime_diag
)

# =====================================================
# Recovery Diagnostics
# =====================================================

st.header(
    "Recovery Diagnostics"
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
# Recent Health
# =====================================================

st.header(
    "Recent Health"
)

health = (
    orchestrator
    .health_history[-20:]
)

if len(health) > 0:

    st.dataframe(
        health
    )

else:

    st.info(
        "no health history"
    )

# =====================================================
# Dangerous Actions
# =====================================================

st.header(
    "Danger Zone"
)

danger = st.checkbox(
    "I understand the risk"
)

if danger:

    # =================================================
    # wipe logs
    # =================================================

    if st.button(
        "WIPE LOGS"
    ):

        log_dir = "logs"

        if os.path.exists(
            log_dir
        ):

            for f in os.listdir(
                log_dir
            ):

                path = os.path.join(
                    log_dir,
                    f,
                )

                try:

                    os.remove(path)

                except:
                    pass

        st.warning(
            "logs wiped"
        )

    # =================================================
    # wipe backups
    # =================================================

    if st.button(
        "DELETE BACKUPS"
    ):

        if os.path.exists(
            backup_dir
        ):

            shutil.rmtree(
                backup_dir
            )

        os.makedirs(
            backup_dir,
            exist_ok=True,
        )

        st.warning(
            "backups deleted"
        )

# =====================================================
# Footer
# =====================================================

st.markdown("---")

st.caption(
    "survival intervention layer"
)