from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Union

import pandas as pd

try:
    import plotly.graph_objects as go
    _PLOTLY_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    go = None
    _PLOTLY_AVAILABLE = False

try:
    import streamlit as st
except Exception:  # pragma: no cover - optional dependency
    class _MissingStreamlit:
        def __getattr__(self, name):
            def _missing(*args, **kwargs):
                raise RuntimeError(
                    "streamlit is required to render execution gap dashboards"
                )

            return _missing

    st = _MissingStreamlit()


DataSource = Union[str, Path, pd.DataFrame]


def load_execution_gap_frame(data_source: DataSource = "derived/bets.csv") -> pd.DataFrame:
    if isinstance(data_source, pd.DataFrame):
        return data_source.copy()

    path = Path(str(data_source))
    if not path.exists():
        return pd.DataFrame()

    return pd.read_csv(path)


def _coerce_numeric(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    result = frame.copy()
    for column in columns:
        if column in result.columns:
            result[column] = pd.to_numeric(result[column], errors="coerce")
    return result


def prepare_execution_gap_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()

    prepared = frame.copy()
    numeric_columns = [
        "probability",
        "hit",
        "odds",
        "predicted_odds",
        "confirmed_odds",
        "slippage_pct",
        "edge",
        "expected_value",
        "expected_value_per_unit",
        "profit",
        "stake",
    ]
    prepared = _coerce_numeric(prepared, numeric_columns)

    if "timestamp" in prepared.columns:
        prepared["timestamp"] = pd.to_datetime(prepared["timestamp"], errors="coerce")
        prepared = prepared.sort_values("timestamp")

    if "predicted_odds" not in prepared.columns and "odds" in prepared.columns:
        prepared["predicted_odds"] = prepared["odds"]

    if "confirmed_odds" not in prepared.columns:
        prepared["confirmed_odds"] = prepared.get("predicted_odds", prepared.get("odds"))

    prepared["predicted_odds"] = pd.to_numeric(prepared.get("predicted_odds"), errors="coerce")
    prepared["confirmed_odds"] = pd.to_numeric(prepared.get("confirmed_odds"), errors="coerce")

    if "slippage_pct" not in prepared.columns:
        prepared["slippage_pct"] = (prepared["confirmed_odds"] - prepared["predicted_odds"]) / prepared["predicted_odds"]

    prepared["slippage_pct"] = pd.to_numeric(prepared["slippage_pct"], errors="coerce")

    if "expected_value" not in prepared.columns and "expected_value_per_unit" in prepared.columns:
        prepared["expected_value"] = prepared["expected_value_per_unit"]

    if "expected_value_per_unit" not in prepared.columns and "expected_value" in prepared.columns:
        prepared["expected_value_per_unit"] = prepared["expected_value"]

    if "expected_value" not in prepared.columns:
        if "probability" in prepared.columns and "predicted_odds" in prepared.columns:
            prepared["expected_value"] = prepared["probability"] * prepared["predicted_odds"] - 1.0
        else:
            prepared["expected_value"] = pd.NA

    if "expected_value_per_unit" not in prepared.columns:
        if (
            "probability" in prepared.columns
            and "confirmed_odds" in prepared.columns
        ):
            prepared["expected_value_per_unit"] = (
                prepared["probability"] * prepared["confirmed_odds"] - 1.0
            )
        elif "expected_value" in prepared.columns:
            prepared["expected_value_per_unit"] = prepared["expected_value"]
        else:
            prepared["expected_value_per_unit"] = pd.NA

    prepared["expected_value"] = pd.to_numeric(prepared["expected_value"], errors="coerce")
    prepared["expected_value_per_unit"] = pd.to_numeric(
        prepared["expected_value_per_unit"], errors="coerce"
    )

    if "profit" in prepared.columns:
        prepared["profit"] = prepared["profit"].fillna(0.0)
        prepared["cumulative_pnl"] = prepared["profit"].cumsum()
    else:
        prepared["profit"] = 0.0
        prepared["cumulative_pnl"] = 0.0

    if "hit" in prepared.columns:
        prepared["hit"] = prepared["hit"].fillna(0).astype(float)

    return prepared


def build_calibration_frame(frame: pd.DataFrame, bins: int = 10) -> pd.DataFrame:
    if frame.empty or "probability" not in frame.columns or "hit" not in frame.columns:
        return pd.DataFrame()

    working = frame[["probability", "hit"]].dropna().copy()
    if working.empty:
        return pd.DataFrame()

    working["bin"] = pd.cut(working["probability"], bins=bins, include_lowest=True, duplicates="drop")
    grouped = working.groupby("bin", observed=False).agg(
        predicted_probability=("probability", "mean"),
        observed_hit_rate=("hit", "mean"),
        count=("hit", "size"),
    )
    grouped = grouped.reset_index(drop=True)
    grouped["bin_center"] = grouped["predicted_probability"]
    grouped["calibration_gap"] = (grouped["observed_hit_rate"] - grouped["predicted_probability"]).abs()
    return grouped


def _plot_calibration(frame: pd.DataFrame):
    if frame.empty:
        return None

    if _PLOTLY_AVAILABLE:
        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=frame["predicted_probability"],
                y=frame["observed_hit_rate"],
                mode="lines+markers",
                name="Observed hit rate",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=[0, 1],
                y=[0, 1],
                mode="lines",
                name="Perfect calibration",
                line=dict(dash="dash"),
            )
        )
        fig.update_layout(
            title="Calibration / Reliability Diagram",
            xaxis_title="Predicted probability",
            yaxis_title="Observed hit rate",
            template="plotly_white",
            height=420,
        )
        return fig

    return frame.set_index("bin_center")[["predicted_probability", "observed_hit_rate"]]


def _plot_slippage(frame: pd.DataFrame):
    if frame.empty:
        return None

    slippage = frame[["predicted_odds", "confirmed_odds"]].dropna()
    if slippage.empty:
        return None

    if _PLOTLY_AVAILABLE:
        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=slippage["predicted_odds"],
                y=slippage["confirmed_odds"],
                mode="markers",
                name="Execution points",
                marker=dict(size=8, opacity=0.75),
            )
        )
        min_odds = float(min(slippage["predicted_odds"].min(), slippage["confirmed_odds"].min()))
        max_odds = float(max(slippage["predicted_odds"].max(), slippage["confirmed_odds"].max()))
        fig.add_trace(
            go.Scatter(
                x=[min_odds, max_odds],
                y=[min_odds, max_odds],
                mode="lines",
                name="No slippage",
                line=dict(dash="dash"),
            )
        )
        fig.update_layout(
            title="Predicted vs Confirmed Odds",
            xaxis_title="Predicted odds",
            yaxis_title="Confirmed odds",
            template="plotly_white",
            height=420,
        )
        return fig

    return slippage


def _plot_ev_and_pnl(frame: pd.DataFrame):
    if frame.empty:
        return None, None

    ev_series = frame["expected_value_per_unit"].dropna()
    pnl_series = frame["cumulative_pnl"].dropna()

    if _PLOTLY_AVAILABLE:
        ev_fig = go.Figure()
        if not ev_series.empty:
            ev_fig.add_trace(
                go.Histogram(
                    x=ev_series,
                    nbinsx=30,
                    name="EV distribution",
                    opacity=0.8,
                )
            )
        ev_fig.update_layout(
            title="EV Distribution",
            xaxis_title="Expected value per unit",
            yaxis_title="Count",
            template="plotly_white",
            height=360,
        )

        pnl_fig = go.Figure()
        if not pnl_series.empty:
            pnl_fig.add_trace(
                go.Scatter(
                    x=list(range(len(pnl_series))),
                    y=pnl_series,
                    mode="lines",
                    name="Cumulative PNL",
                    line=dict(width=3),
                )
            )
        pnl_fig.update_layout(
            title="Cumulative PNL",
            xaxis_title="Bet sequence",
            yaxis_title="PNL",
            template="plotly_white",
            height=360,
        )
        return ev_fig, pnl_fig

    ev_frame = pd.DataFrame()
    if not ev_series.empty:
        ev_frame = ev_series.to_frame(name="expected_value_per_unit")
    pnl_frame = pd.DataFrame()
    if not pnl_series.empty:
        pnl_frame = pnl_series.to_frame(name="cumulative_pnl")
    return ev_frame, pnl_frame


def render_execution_gap_dashboard(
    data_source: DataSource = "derived/bets.csv",
    *,
    slippage_threshold: float = 0.10,
    recent_window: int = 20,
    title: str = "Execution Gap Monitor",
) -> Optional[pd.DataFrame]:
    frame = prepare_execution_gap_frame(load_execution_gap_frame(data_source))

    st.subheader(title)

    if frame.empty:
        st.info("execution log is unavailable")
        return None

    if "slippage_pct" in frame.columns:
        recent_slippage = frame["slippage_pct"].dropna().tail(recent_window)
        if not recent_slippage.empty and recent_slippage.mean() <= -abs(slippage_threshold):
            st.warning("Slippage Warning: キャリブレーションの再評価が必要です")

    calibration_frame = build_calibration_frame(frame)
    slippage_frame = frame[["predicted_odds", "confirmed_odds", "slippage_pct"]].dropna()

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Rows", len(frame))
    with col2:
        avg_slippage = float(frame["slippage_pct"].dropna().mean()) if frame["slippage_pct"].notna().any() else 0.0
        st.metric("Avg Slippage", f"{avg_slippage:.2%}")
    with col3:
        worst_slippage = float(frame["slippage_pct"].dropna().min()) if frame["slippage_pct"].notna().any() else 0.0
        st.metric("Worst Slippage", f"{worst_slippage:.2%}")
    with col4:
        cumulative_pnl = float(frame["cumulative_pnl"].iloc[-1]) if "cumulative_pnl" in frame.columns and not frame["cumulative_pnl"].empty else 0.0
        st.metric("Cumulative PNL", f"{cumulative_pnl:,.0f}")

    tab_calibration, tab_slippage, tab_ev, tab_data = st.tabs([
        "Calibration",
        "Slippage",
        "EV / PNL",
        "Raw Data",
    ])

    with tab_calibration:
        if calibration_frame.empty:
            st.info("calibration data is unavailable")
        else:
            fig = _plot_calibration(calibration_frame)
            if _PLOTLY_AVAILABLE and fig is not None:
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.line_chart(
                    calibration_frame.set_index("bin_center")[["predicted_probability", "observed_hit_rate"]]
                )
            st.dataframe(calibration_frame, use_container_width=True)

    with tab_slippage:
        if slippage_frame.empty:
            st.info("slippage data is unavailable")
        else:
            fig = _plot_slippage(frame)
            if _PLOTLY_AVAILABLE and fig is not None:
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.scatter_chart(slippage_frame[["predicted_odds", "confirmed_odds"]])
            st.dataframe(
                slippage_frame.assign(
                    slippage_pct=slippage_frame["slippage_pct"].map(lambda x: f"{x:.2%}")
                ),
                use_container_width=True,
            )

    with tab_ev:
        ev_fig, pnl_fig = _plot_ev_and_pnl(frame)
        if _PLOTLY_AVAILABLE:
            if ev_fig is not None:
                st.plotly_chart(ev_fig, use_container_width=True)
            if pnl_fig is not None:
                st.plotly_chart(pnl_fig, use_container_width=True)
        else:
            if ev_fig is not None and not ev_fig.empty:
                st.bar_chart(ev_fig)
            if pnl_fig is not None and not pnl_fig.empty:
                st.line_chart(pnl_fig)

    with tab_data:
        display_columns = [
            column
            for column in [
                "timestamp",
                "race_id",
                "selection",
                "probability",
                "odds",
                "predicted_odds",
                "confirmed_odds",
                "slippage_pct",
                "expected_value_per_unit",
                "profit",
                "cumulative_pnl",
                "mode",
                "api_status",
                "api_error",
            ]
            if column in frame.columns
        ]
        st.dataframe(frame[display_columns].tail(100), use_container_width=True)

    return frame
