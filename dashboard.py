"""
dashboard.py — Analytics and performance dashboard for Agri Doctor.

Renders the LLM Performance Dashboard page using Plotly charts and
Streamlit components. All metrics displayed here are clearly labelled
as either "Measured" (from real data) or "Simulated" (illustrative only).
"""

import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any

import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd

from database import get_agent_metrics, get_guardrail_events, get_diagnosis_stats

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Colour palette (matches app theme)
# ──────────────────────────────────────────────────────────────────────────────
COLOR_PATH  = "#4a7c59"   # Pathologist — forest green
COLOR_EXT   = "#c8b560"   # Extension Officer — golden wheat
COLOR_MUTED = "#7a8c7b"
BG_COLOR    = "#ffffff"   # White chart background — ensures all text/lines are visible
PLOT_BG     = "#f8faf8"   # Slightly tinted plot area
GRID_COLOR  = "#e2e8e3"   # Subtle gridline colour


def _safe_avg(values: List[float]) -> float:
    return round(sum(values) / len(values), 3) if values else 0.0


def render_performance_dashboard() -> None:
    """Main entry point — renders the full LLM Performance Dashboard."""

    st.markdown(
        """
        <div style='background:linear-gradient(135deg,#4a7c59,#8fba8a);
                    padding:1.5rem 2rem; border-radius:12px; margin-bottom:1.5rem;'>
            <h2 style='color:white; margin:0; font-size:1.6rem;'>📊 LLM Performance Dashboard</h2>
            <p style='color:rgba(255,255,255,0.85); margin:0.3rem 0 0;'>
                Real-time agent metrics, cost tracking, and guardrail analytics.
                <strong style='color:#ffe08a;'>Measured</strong> = recorded from actual API calls.
                <em style='color:rgba(255,255,255,0.7);'>Simulated</em> = illustrative (no verified ground truth available).
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Date range filter
    col_f1, col_f2, _ = st.columns([1, 1, 2])
    with col_f1:
        days = st.selectbox("Date range", [7, 14, 30, 60, 90], index=2, key="dash_days")
    with col_f2:
        st.markdown("<br>", unsafe_allow_html=True)
        st.caption(f"Showing last {days} days of data")

    # Load data
    metrics: List[Dict] = get_agent_metrics(days=days)
    guardrail_events: List[Dict] = get_guardrail_events(days=days)
    stats = get_diagnosis_stats()

    # Split by agent
    path_metrics = [m for m in metrics if m.get("agent_name") == "pathologist"]
    ext_metrics   = [m for m in metrics if m.get("agent_name") == "extension_officer"]

    # ── Top KPI Cards ──────────────────────────────────────────────────────
    _render_kpi_cards(stats, path_metrics, ext_metrics, guardrail_events)

    st.markdown("---")

    # ── Tabs ───────────────────────────────────────────────────────────────
    tab1, tab2, tab3, tab4 = st.tabs([
        "⚡ Latency & Throughput",
        "🪙 Token & Cost Analysis",
        "🛡️ Guardrails & Errors",
        "🤖 Agent Comparison",
    ])

    with tab1:
        _render_latency_tab(path_metrics, ext_metrics)
    with tab2:
        _render_token_cost_tab(path_metrics, ext_metrics)
    with tab3:
        _render_guardrails_tab(guardrail_events, metrics)
    with tab4:
        _render_agent_comparison_tab(path_metrics, ext_metrics)

    st.markdown("---")
    _render_simulated_eval_section()


# ──────────────────────────────────────────────────────────────────────────────
# KPI Cards
# ──────────────────────────────────────────────────────────────────────────────

def _render_kpi_cards(stats, path_metrics, ext_metrics, guardrail_events):
    total_diagnoses = stats.get("total_diagnoses", 0)
    avg_latency_path = _safe_avg([m["latency_seconds"] for m in path_metrics])
    avg_latency_ext  = _safe_avg([m["latency_seconds"] for m in ext_metrics])
    total_errors = sum(1 for m in path_metrics + ext_metrics if m.get("api_status") == "error")
    guardrail_count  = len(guardrail_events)
    total_cost = sum(m.get("estimated_cost_usd", 0) for m in ext_metrics)

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    kpis = [
        (c1, "🌱", "Total Diagnoses", str(total_diagnoses), "MEASURED", "#4a7c59"),
        (c2, "⚡", "Avg Pathologist Latency", f"{avg_latency_path:.2f}s", "MEASURED", "#c8b560"),
        (c3, "⚡", "Avg Extension Latency", f"{avg_latency_ext:.2f}s", "MEASURED", "#4a7c59"),
        (c4, "❌", "API Errors", str(total_errors), "MEASURED", "#c0392b"),
        (c5, "🛡️", "Guardrail Events", str(guardrail_count), "MEASURED", "#2980b9"),
        (c6, "💰", "Est. IBM Cost (USD)", f"${total_cost:.4f}", "MEASURED", "#7a8c7b"),
    ]
    for col, icon, label, value, badge, color in kpis:
        with col:
            st.markdown(
                f"""
                <div style='background:#fff; border:1px solid #e5e7eb; border-radius:10px;
                            padding:0.8rem; text-align:center; height:130px;'>
                    <div style='font-size:1.4rem;'>{icon}</div>
                    <div style='font-size:0.72rem; color:#7a8c7b; margin-top:2px;'>{label}</div>
                    <div style='font-size:1.3rem; font-weight:700; color:{color};'>{value}</div>
                    <div style='font-size:0.62rem; background:#e8f5e9; color:#4a7c59;
                                border-radius:4px; padding:1px 4px; margin-top:4px;'>{badge}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )


# ──────────────────────────────────────────────────────────────────────────────
# Latency Tab
# ──────────────────────────────────────────────────────────────────────────────

def _render_latency_tab(path_metrics, ext_metrics):
    st.subheader("Response Latency Over Time")
    st.caption("🟢 MEASURED — recorded from actual API calls")

    if not path_metrics and not ext_metrics:
        st.info("No execution data yet. Run some diagnoses to populate this chart.")
        return

    def _to_df(metrics, agent_label):
        if not metrics:
            return pd.DataFrame()
        df = pd.DataFrame(metrics)
        df["agent"] = agent_label
        df["created_at"] = pd.to_datetime(df["created_at"])
        return df[["created_at", "latency_seconds", "agent"]]

    df_path = _to_df(path_metrics, "Pathologist (Gemini)")
    df_ext  = _to_df(ext_metrics,  "Extension Officer (IBM Granite)")
    df_all  = pd.concat([df_path, df_ext], ignore_index=True)

    if df_all.empty:
        st.info("No latency data available yet.")
        return

    fig = px.line(
        df_all, x="created_at", y="latency_seconds", color="agent",
        color_discrete_map={
            "Pathologist (Gemini)": COLOR_PATH,
            "Extension Officer (IBM Granite)": COLOR_EXT,
        },
        labels={"created_at": "Time", "latency_seconds": "Latency (s)", "agent": "Agent"},
        title="Agent Response Latency Over Time",
    )
    fig.update_layout(
        plot_bgcolor=PLOT_BG, paper_bgcolor=BG_COLOR,
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        font=dict(color="#1c2e1e"),
        xaxis=dict(gridcolor=GRID_COLOR, linecolor="#c0ccc1"),
        yaxis=dict(gridcolor=GRID_COLOR, linecolor="#c0ccc1"),
    )
    st.plotly_chart(fig, use_container_width=True)

    # Histogram
    col1, col2 = st.columns(2)
    with col1:
        if not df_path.empty:
            fig2 = px.histogram(
                df_path, x="latency_seconds", nbins=15,
                title="Pathologist Latency Distribution",
                color_discrete_sequence=[COLOR_PATH],
            )
            fig2.update_layout(
                plot_bgcolor=PLOT_BG, paper_bgcolor=BG_COLOR,
                font=dict(color="#1c2e1e"),
                xaxis=dict(gridcolor=GRID_COLOR, linecolor="#c0ccc1"),
                yaxis=dict(gridcolor=GRID_COLOR, linecolor="#c0ccc1"),
            )
            st.plotly_chart(fig2, use_container_width=True)
    with col2:
        if not df_ext.empty:
            fig3 = px.histogram(
                df_ext, x="latency_seconds", nbins=15,
                title="Extension Officer Latency Distribution",
                color_discrete_sequence=[COLOR_EXT],
            )
            fig3.update_layout(
                plot_bgcolor=PLOT_BG, paper_bgcolor=BG_COLOR,
                font=dict(color="#1c2e1e"),
                xaxis=dict(gridcolor=GRID_COLOR, linecolor="#c0ccc1"),
                yaxis=dict(gridcolor=GRID_COLOR, linecolor="#c0ccc1"),
            )
            st.plotly_chart(fig3, use_container_width=True)


# ──────────────────────────────────────────────────────────────────────────────
# Token & Cost Tab
# ──────────────────────────────────────────────────────────────────────────────

def _render_token_cost_tab(path_metrics, ext_metrics):
    st.subheader("Token Usage & Estimated Cost")
    st.caption("🟢 MEASURED — token counts from API responses. Cost is an estimate only.")

    all_metrics = path_metrics + ext_metrics
    if not all_metrics:
        st.info("No token data yet. Run some diagnoses to populate this chart.")
        return

    df = pd.DataFrame(all_metrics)
    df["agent_label"] = df["agent_name"].map({
        "pathologist": "Pathologist (Gemini)",
        "extension_officer": "Extension Officer (IBM Granite)",
    })
    df["created_at"] = pd.to_datetime(df["created_at"])
    df["total_tokens"] = df["input_tokens"] + df["output_tokens"]

    # Tokens bar
    fig = px.bar(
        df, x="created_at", y="total_tokens", color="agent_label",
        color_discrete_map={
            "Pathologist (Gemini)": COLOR_PATH,
            "Extension Officer (IBM Granite)": COLOR_EXT,
        },
        title="Token Usage Per Request",
        labels={"total_tokens": "Total Tokens", "created_at": "Time"},
    )
    fig.update_layout(
        plot_bgcolor=PLOT_BG, paper_bgcolor=BG_COLOR,
        font=dict(color="#1c2e1e"),
        xaxis=dict(gridcolor=GRID_COLOR, linecolor="#c0ccc1"),
        yaxis=dict(gridcolor=GRID_COLOR, linecolor="#c0ccc1"),
    )
    st.plotly_chart(fig, use_container_width=True)

    # Cost area chart (IBM only — Groq cost not tracked)
    if not df[df["agent_name"] == "extension_officer"].empty:
        df_ext_cost = df[df["agent_name"] == "extension_officer"].copy()
        df_ext_cost = df_ext_cost.sort_values("created_at")
        df_ext_cost["cumulative_cost"] = df_ext_cost["estimated_cost_usd"].cumsum()
        fig2 = px.area(
            df_ext_cost, x="created_at", y="cumulative_cost",
            title="Cumulative IBM watsonx Estimated Cost (USD)",
            color_discrete_sequence=[COLOR_EXT],
        )
        fig2.update_layout(
            plot_bgcolor=PLOT_BG, paper_bgcolor=BG_COLOR,
            font=dict(color="#1c2e1e"),
            xaxis=dict(gridcolor=GRID_COLOR, linecolor="#c0ccc1"),
            yaxis=dict(gridcolor=GRID_COLOR, linecolor="#c0ccc1"),
        )
        st.plotly_chart(fig2, use_container_width=True)

    # Summary table
    st.markdown("**Token Summary by Agent**")
    summary = df.groupby("agent_label").agg(
        Calls=("agent_name", "count"),
        Avg_Input_Tokens=("input_tokens", "mean"),
        Avg_Output_Tokens=("output_tokens", "mean"),
        Total_Tokens=("total_tokens", "sum"),
        Est_Cost_USD=("estimated_cost_usd", "sum"),
    ).round(2)
    st.dataframe(summary, use_container_width=True)


# ──────────────────────────────────────────────────────────────────────────────
# Guardrails Tab
# ──────────────────────────────────────────────────────────────────────────────

def _render_guardrails_tab(guardrail_events, all_metrics):
    st.subheader("Guardrail Activity & API Errors")
    st.caption("🟢 MEASURED — all events recorded in real time")

    col1, col2 = st.columns(2)

    # Guardrail events by type
    with col1:
        if guardrail_events:
            df_g = pd.DataFrame(guardrail_events)
            type_counts = df_g["event_type"].value_counts().reset_index()
            type_counts.columns = ["Event Type", "Count"]
            fig = px.pie(
                type_counts, values="Count", names="Event Type",
                title="Guardrail Events by Type",
                color_discrete_sequence=px.colors.qualitative.Set2,
            )
            fig.update_layout(
                paper_bgcolor=BG_COLOR,
                font=dict(color="#1c2e1e"),
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No guardrail events recorded yet.")

    # API errors by agent
    with col2:
        if all_metrics:
            df_m = pd.DataFrame(all_metrics)
            error_counts = df_m.groupby(["agent_name", "api_status"]).size().reset_index(name="count")
            fig2 = px.bar(
                error_counts, x="agent_name", y="count", color="api_status",
                title="API Call Status by Agent",
                color_discrete_map={"success": COLOR_PATH, "error": "#c0392b", "timeout": COLOR_EXT},
            )
            fig2.update_layout(
                plot_bgcolor=PLOT_BG, paper_bgcolor=BG_COLOR,
                font=dict(color="#1c2e1e"),
                xaxis=dict(gridcolor=GRID_COLOR, linecolor="#c0ccc1"),
                yaxis=dict(gridcolor=GRID_COLOR, linecolor="#c0ccc1"),
            )
            st.plotly_chart(fig2, use_container_width=True)
        else:
            st.info("No API call data available yet.")

    # Recent guardrail events table
    if guardrail_events:
        st.markdown("**Recent Guardrail Events**")
        df_show = pd.DataFrame(guardrail_events)[["created_at", "event_type", "agent_name", "severity", "details"]]
        df_show.columns = ["Time", "Event Type", "Agent", "Severity", "Details"]
        st.dataframe(df_show.head(20), use_container_width=True)


# ──────────────────────────────────────────────────────────────────────────────
# Agent Comparison Tab
# ──────────────────────────────────────────────────────────────────────────────

def _render_agent_comparison_tab(path_metrics, ext_metrics):
    st.subheader("Agent Performance Comparison")
    st.caption("🟢 MEASURED where available | 🔶 SIMULATED metrics are illustrative only")

    # Radar chart with measured + simulated metrics
    measured_path_latency = _safe_avg([m["latency_seconds"] for m in path_metrics])
    measured_ext_latency  = _safe_avg([m["latency_seconds"] for m in ext_metrics])
    path_success = (
        sum(1 for m in path_metrics if m.get("api_status") == "success") / len(path_metrics) * 100
        if path_metrics else 0
    )
    ext_success = (
        sum(1 for m in ext_metrics if m.get("api_status") == "success") / len(ext_metrics) * 100
        if ext_metrics else 0
    )

    categories = ["Success Rate %", "Avg Tokens/100", "Speed Score", "Cost Efficiency"]
    # Normalise latency to speed score (lower latency = higher score)
    path_speed = max(0, 100 - measured_path_latency * 10)
    ext_speed  = max(0, 100 - measured_ext_latency * 10)
    path_tokens_norm = _safe_avg([m.get("output_tokens", 0) for m in path_metrics]) / 100
    ext_tokens_norm  = _safe_avg([m.get("output_tokens", 0) for m in ext_metrics]) / 100
    path_cost_eff = 90  # Groq is low-cost — simulated
    ext_cost_eff  = 75  # IBM Granite — simulated

    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(
        r=[path_success, path_tokens_norm, path_speed, path_cost_eff],
        theta=categories, fill="toself",
        name="Pathologist (Gemini)", line_color=COLOR_PATH,
    ))
    fig.add_trace(go.Scatterpolar(
        r=[ext_success, ext_tokens_norm, ext_speed, ext_cost_eff],
        theta=categories, fill="toself",
        name="Extension Officer (IBM Granite)", line_color=COLOR_EXT,
    ))
    fig.update_layout(
        polar=dict(radialaxis=dict(
            visible=True, range=[0, 100],
            gridcolor=GRID_COLOR, linecolor="#c0ccc1",
            tickfont=dict(color="#1c2e1e"),
        )),
        showlegend=True,
        paper_bgcolor=BG_COLOR,
        font=dict(color="#1c2e1e"),
        title="Agent Performance Radar (⚠️ some values are simulated)",
    )
    st.plotly_chart(fig, use_container_width=True)

    # Side-by-side comparison table
    comparison_data = {
        "Metric": [
            "Total Calls", "Success Rate", "Avg Latency (s)",
            "Avg Input Tokens", "Avg Output Tokens",
            "API Errors",
        ],
        "Pathologist (Gemini) 🟢": [
            len(path_metrics),
            f"{path_success:.1f}% 🟢",
            f"{measured_path_latency:.2f}s 🟢",
            f"{_safe_avg([m.get('input_tokens',0) for m in path_metrics]):.0f} 🟢",
            f"{_safe_avg([m.get('output_tokens',0) for m in path_metrics]):.0f} 🟢",
            f"{sum(1 for m in path_metrics if m.get('api_status')=='error')} 🟢",
        ],
        "Extension Officer (IBM Granite) 🟢": [
            len(ext_metrics),
            f"{ext_success:.1f}% 🟢",
            f"{measured_ext_latency:.2f}s 🟢",
            f"{_safe_avg([m.get('input_tokens',0) for m in ext_metrics]):.0f} 🟢",
            f"{_safe_avg([m.get('output_tokens',0) for m in ext_metrics]):.0f} 🟢",
            f"{sum(1 for m in ext_metrics if m.get('api_status')=='error')} 🟢",
        ],
    }
    st.dataframe(pd.DataFrame(comparison_data), use_container_width=True)


# ──────────────────────────────────────────────────────────────────────────────
# Simulated Evaluation Section
# ──────────────────────────────────────────────────────────────────────────────

def _render_simulated_eval_section():
    """
    Display simulated/illustrative NLP evaluation metrics with clear labelling.
    These are NOT computed against verified ground-truth data.
    """
    st.subheader("🔶 NLP Evaluation Metrics (Illustrative — Not Verified Ground Truth)")
    st.warning(
        "The metrics below are **SIMULATED** for display purposes only. "
        "They do NOT represent verified accuracy against labelled test data. "
        "To compute real evaluation metrics, upload a verified ground-truth dataset "
        "in the Settings page (future feature)."
    )

    col1, col2 = st.columns(2)
    with col1:
        metrics_data = {
            "Metric": ["Accuracy", "Precision", "Recall", "F1 Score", "Semantic Similarity"],
            "Pathologist (Simulated)": [0.82, 0.79, 0.85, 0.82, 0.88],
            "Extension Officer (Simulated)": [0.78, 0.76, 0.81, 0.78, 0.84],
        }
        df_sim = pd.DataFrame(metrics_data)
        fig = px.bar(
            df_sim.melt(id_vars="Metric", var_name="Agent", value_name="Score"),
            x="Metric", y="Score", color="Agent", barmode="group",
            color_discrete_map={
                "Pathologist (Simulated)": COLOR_PATH,
                "Extension Officer (Simulated)": COLOR_EXT,
            },
            title="Simulated NLP Evaluation Metrics",
            range_y=[0, 1],
        )
        fig.update_layout(
            plot_bgcolor=PLOT_BG, paper_bgcolor=BG_COLOR,
            font=dict(color="#1c2e1e"),
            xaxis=dict(gridcolor=GRID_COLOR, linecolor="#c0ccc1"),
            yaxis=dict(gridcolor=GRID_COLOR, linecolor="#c0ccc1"),
        )
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        workflow_data = {
            "Metric": [
                "Task Completion Rate", "Agent Coordination Score",
                "Handoff Accuracy", "Tool Execution Success",
                "Hallucination Rate", "Guardrail Intervention Rate",
            ],
            "Value (Simulated)": ["91%", "87%", "94%", "96%", "4%", "3%"],
            "Status": [
                "SIMULATED", "SIMULATED", "SIMULATED",
                "SIMULATED", "SIMULATED", "SIMULATED",
            ],
        }
        st.dataframe(pd.DataFrame(workflow_data), use_container_width=True)
        st.caption(
            "🔶 All values above are illustrative. Future releases will compute "
            "these from verified test cases stored in the database."
        )
