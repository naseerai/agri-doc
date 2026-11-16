"""
dashboard.py — Analytics and performance dashboard for Agri Doctor.

Renders the LLM Performance Dashboard page using Plotly charts and
Streamlit components. All metrics displayed here are clearly labelled
as either "Measured" (from real data) or "Simulated" (illustrative only).
"""

import json
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any

import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd

from database import get_agent_metrics, get_guardrail_events, get_diagnosis_stats, get_recent_diagnoses

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

    # ── Diagnosis Reports — always rendered last ──────────────────────────────
    st.markdown("<div style='margin-top:2.5rem'></div>", unsafe_allow_html=True)
    _render_diagnosis_reports_section()


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
    Display real workflow health metrics derived from the live database.
    All values are computed from actual recorded data — no simulated numbers.
    """
    from database import get_recent_diagnoses, get_agent_metrics, get_guardrail_events

    st.subheader("📈 Workflow Health Metrics (Real-Time)")
    st.info(
        "All values below are computed from your actual diagnosis history and agent execution "
        "records stored in the local database. No simulated or placeholder data is shown."
    )

    # ── Load real data ────────────────────────────────────────────────────────
    all_diagnoses = get_recent_diagnoses(limit=1000)
    all_metrics   = get_agent_metrics(days=90)
    all_guardrails = get_guardrail_events(days=90)

    total        = len(all_diagnoses)
    completed    = sum(1 for d in all_diagnoses if d.get("status") == "completed")
    partial      = sum(1 for d in all_diagnoses if d.get("status") == "partial")
    failed_diag  = sum(1 for d in all_diagnoses if d.get("status") == "failed")

    path_calls   = [m for m in all_metrics if m.get("agent_name") == "pathologist"]
    ext_calls    = [m for m in all_metrics if m.get("agent_name") == "extension_officer"]

    path_success = sum(1 for m in path_calls if m.get("api_status") == "success")
    ext_success  = sum(1 for m in ext_calls  if m.get("api_status") == "success")

    path_rate = round(path_success / len(path_calls) * 100, 1) if path_calls else None
    ext_rate  = round(ext_success  / len(ext_calls)  * 100, 1) if ext_calls  else None
    task_rate = round(completed / total * 100, 1) if total else None
    gr_rate   = round(len(all_guardrails) / total * 100, 1) if total else None

    if total == 0:
        st.warning("No diagnosis records yet. Run at least one diagnosis to populate these metrics.")
        return

    col1, col2 = st.columns(2)

    # ── Left: API success rate bar chart ────────────────────────────────────
    with col1:
        agents, success_rates = [], []
        if path_calls:
            agents.append("Pathologist\n(Gemini)")
            success_rates.append(path_rate)
        if ext_calls:
            agents.append("Extension Officer\n(IBM Granite)")
            success_rates.append(ext_rate)

        if agents:
            fig = px.bar(
                x=agents,
                y=success_rates,
                color=agents,
                color_discrete_sequence=[COLOR_PATH, COLOR_EXT],
                title="Agent API Success Rate (%) — MEASURED",
                labels={"x": "Agent", "y": "Success Rate (%)"},
                range_y=[0, 100],
                text=success_rates,
            )
            fig.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
            fig.update_layout(
                plot_bgcolor=PLOT_BG, paper_bgcolor=BG_COLOR,
                showlegend=False,
                font=dict(color="#1c2e1e"),
                xaxis=dict(gridcolor=GRID_COLOR, linecolor="#c0ccc1"),
                yaxis=dict(gridcolor=GRID_COLOR, linecolor="#c0ccc1"),
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No agent execution data yet.")

    # ── Right: real workflow metrics table ───────────────────────────────────
    with col2:
        rows = [
            ("Task Completion Rate",
             f"{task_rate}%" if task_rate is not None else "—",
             "MEASURED"),
            ("Completed Diagnoses",
             str(completed),
             "MEASURED"),
            ("Partial Diagnoses (1 agent)",
             str(partial),
             "MEASURED"),
            ("Failed Diagnoses",
             str(failed_diag),
             "MEASURED"),
            ("Pathologist API Success Rate",
             f"{path_rate}%" if path_rate is not None else "No data",
             "MEASURED" if path_calls else "NO DATA"),
            ("Extension Officer API Success Rate",
             f"{ext_rate}%" if ext_rate is not None else "No data",
             "MEASURED" if ext_calls else "NO DATA"),
            ("Total Guardrail Events (90 days)",
             str(len(all_guardrails)),
             "MEASURED"),
            ("Guardrail Rate per Diagnosis",
             f"{gr_rate}%" if gr_rate is not None else "—",
             "MEASURED"),
        ]
        workflow_data = {
            "Metric":  [r[0] for r in rows],
            "Value":   [r[1] for r in rows],
            "Source":  [r[2] for r in rows],
        }
        st.dataframe(pd.DataFrame(workflow_data), use_container_width=True)
        st.caption(
            "🟢 All values above are computed from live database records. "
            "NLP ground-truth metrics (Accuracy, Precision, F1) require a labelled "
            "test dataset and are not displayed until one is provided."
        )


# ──────────────────────────────────────────────────────────────────────────────
# Diagnosis Reports Section
# ──────────────────────────────────────────────────────────────────────────────

def _conf_badge(level: str) -> str:
    """Return a styled HTML badge for a confidence level."""
    styles = {
        "High":    ("background:#dcfce7;color:#14532d;border:1px solid #86efac;", "High"),
        "Medium":  ("background:#fef9c3;color:#713f12;border:1px solid #fde047;", "Medium"),
        "Low":     ("background:#fee2e2;color:#7f1d1d;border:1px solid #fca5a5;", "Low"),
    }
    s, lbl = styles.get(level, ("background:#f3f4f6;color:#374151;border:1px solid #d1d5db;", level or "—"))
    return (
        f"<span style='display:inline-block;padding:2px 11px;border-radius:100px;"
        f"font-size:.68rem;font-weight:700;{s}'>{lbl}</span>"
    )


def _sev_color(severity: str) -> str:
    return {"Mild": "#16a34a", "Moderate": "#d97706",
            "Severe": "#dc2626", "Unclear": "#6b7280"}.get(severity, "#6b7280")


def _render_pathologist_card(p: Dict) -> None:
    """Render a pathologist report dict as a styled card."""
    disease  = p.get("suspected_disease", "Unknown")
    conf     = p.get("confidence_level", "Unclear")
    severity = p.get("disease_severity", "Unclear")
    sev_col  = _sev_color(severity)

    st.markdown(
        f"<div style='background:#fff;border:1px solid #bbf7d0;border-left:4px solid #16a34a;"
        f"border-radius:0 12px 12px 0;padding:1rem 1.4rem;margin-bottom:.75rem;'>"
        f"<div style='font-size:1rem;font-weight:800;color:#14532d;margin-bottom:.5rem;'>"
        f"🦠 {disease}</div>"
        f"<div style='display:flex;gap:.8rem;flex-wrap:wrap;align-items:center;'>"
        f"<span>Confidence: {_conf_badge(conf)}</span>"
        f"<span style='font-size:.82rem;'>Severity: "
        f"<strong style='color:{sev_col};'>{severity}</strong></span>"
        f"<span style='font-size:.82rem;'>Lab confirmation: "
        f"<strong>{'⚠️ Required' if p.get('requires_lab_confirmation') else '✅ Not required'}</strong></span>"
        f"</div></div>",
        unsafe_allow_html=True,
    )

    c1, c2 = st.columns(2, gap="medium")
    with c1:
        if p.get("symptoms_observed"):
            st.markdown("**🔴 Symptoms Observed**")
            for s in p["symptoms_observed"]:
                st.markdown(f"- {s}")
        if p.get("affected_plant_parts"):
            st.markdown("**🌿 Affected Parts**")
            for part in p["affected_plant_parts"]:
                st.markdown(f"- {part}")
    with c2:
        if p.get("possible_causes"):
            st.markdown("**💡 Possible Causes**")
            for cause in p["possible_causes"]:
                st.markdown(f"- {cause}")
        if p.get("alternative_diagnoses"):
            st.markdown("**🔄 Alternative Diagnoses**")
            for alt in p["alternative_diagnoses"]:
                st.markdown(f"- {alt}")

    if p.get("pathologist_notes"):
        st.info(f"📋 {p['pathologist_notes']}")
    if p.get("_confidence_warning"):
        st.warning(p["_confidence_warning"])
    st.caption(
        f"Vision: {p.get('vision_provider', '?')} · "
        f"Quality: {p.get('image_quality', '?')} · "
        f"File: {p.get('image_filename', '?')}"
    )


def _render_extension_card(e: Dict) -> None:
    """Render an extension officer report dict as a styled card."""
    if e.get("crop_condition_summary"):
        st.markdown(
            f"<div style='background:#fff;border:1px solid #bbf7d0;border-left:4px solid #16a34a;"
            f"border-radius:0 12px 12px 0;padding:.85rem 1.2rem;margin-bottom:.75rem;'>"
            f"<strong style='color:#14532d;'>📋 Crop Condition Summary</strong><br>"
            f"<span style='font-size:.9rem;color:#374151;'>{e['crop_condition_summary']}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

    c1, c2 = st.columns(2, gap="medium")
    with c1:
        if e.get("immediate_actions"):
            st.markdown("**🚨 Immediate Actions**")
            for a in e["immediate_actions"]:
                st.markdown(f"- ✅ {a}")
        if e.get("crop_care_tips"):
            st.markdown("**🌱 Crop Care Tips**")
            for t in e["crop_care_tips"]:
                st.markdown(f"- 🌿 {t}")
    with c2:
        if e.get("preventive_measures"):
            st.markdown("**🛡️ Prevention**")
            for pv in e["preventive_measures"]:
                st.markdown(f"- 🔒 {pv}")
        if e.get("when_to_seek_expert_help"):
            st.warning(f"👨‍🔬 {e['when_to_seek_expert_help']}")

    if e.get("treatment_options"):
        st.markdown("**💊 Treatment Options**")
        for tr in e["treatment_options"]:
            with st.expander(f"{tr.get('type', '?')} — {tr.get('name', '?')}"):
                if tr.get("instructions"):
                    st.markdown(f"📋 {tr['instructions']}")
                if tr.get("ppe_required"):
                    st.markdown(f"🥽 **PPE Required:** {tr['ppe_required']}")
                if tr.get("environmental_notes"):
                    st.markdown(f"🌍 {tr['environmental_notes']}")

    rec  = e.get("estimated_recovery_time", "")
    conf = e.get("advisory_confidence", "")
    if rec or conf:
        parts = []
        if rec:
            parts.append(f"⏱️ Recovery: <strong>{rec}</strong>")
        if conf:
            parts.append(f"Advisory Confidence: {_conf_badge(conf)}")
        st.markdown(
            f"<div style='background:#f0fdf4;border:1px solid #bbf7d0;border-radius:10px;"
            f"padding:.7rem 1rem;margin-top:.5rem;'>"
            f"{'&nbsp;&nbsp;·&nbsp;&nbsp;'.join(parts)}</div>",
            unsafe_allow_html=True,
        )

    st.markdown(
        "<div style='background:#fffbeb;border:1px solid #fde047;border-left:4px solid #ca8a04;"
        "border-radius:0 10px 10px 0;padding:.6rem 1rem;font-size:.78rem;color:#713f12;"
        "margin-top:.6rem;'>⚠️ AI advisory — verify with a qualified agricultural extension officer "
        "before acting.</div>",
        unsafe_allow_html=True,
    )


def _render_diagnosis_reports_section() -> None:
    """
    Render a full 'Recent Diagnosis Reports' section at the bottom of the
    Performance Dashboard.  Each diagnosis row is a clickable expander that
    shows the complete pathologist + extension officer report.
    """
    # ── Section banner ────────────────────────────────────────────────────────
    st.markdown(
        """
        <div style='background:linear-gradient(135deg,#052e16,#14532d);
                    padding:1.4rem 2rem;border-radius:14px;margin-bottom:1.4rem;
                    border:1px solid rgba(74,222,128,.15);'>
            <div style='font-size:1.4rem;font-weight:900;color:#4ade80;margin-bottom:.3rem;'>
                📋 Recent Diagnosis Reports
            </div>
            <div style='font-size:.85rem;color:rgba(255,255,255,.7);'>
                Full AI-generated pathologist &amp; farm advisory reports from every
                diagnosis stored in the database — click any row to expand.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ── Controls ──────────────────────────────────────────────────────────────
    ctrl_l, ctrl_r = st.columns([2, 1])
    with ctrl_l:
        limit = st.selectbox(
            "Show last N diagnoses",
            options=[5, 10, 20, 50],
            index=1,
            key="dash_report_limit",
        )
    with ctrl_r:
        show_raw = st.checkbox("Show raw combined report text", key="dash_show_raw")

    diagnoses = get_recent_diagnoses(limit=limit)

    if not diagnoses:
        st.info("No diagnosis records yet. Run at least one crop diagnosis to populate this section.")
        return

    for idx, d in enumerate(diagnoses):
        disease  = d.get("suspected_disease") or "Unknown Disease"
        conf     = d.get("confidence_level") or "—"
        status   = d.get("status") or "—"
        filename = d.get("image_filename") or "—"
        ts       = (d.get("created_at") or "")[:19]
        proc_t   = d.get("processing_time_seconds") or 0.0

        # Status colour
        status_color = {
            "completed": "#16a34a",
            "partial":   "#d97706",
            "failed":    "#dc2626",
        }.get(status, "#6b7280")

        expander_label = (
            f"🌱 {disease}  ·  {_conf_badge(conf)}  ·  "
            f"{ts}  ·  📁 {filename}"
        )

        with st.expander(expander_label, expanded=(idx == 0)):
            # ── Header row ────────────────────────────────────────────────
            h1, h2, h3 = st.columns([3, 1, 1])
            with h1:
                st.markdown(
                    f"<div style='font-size:1.05rem;font-weight:800;color:#14532d;'>"
                    f"🌱 {disease}</div>"
                    f"<div style='font-size:.78rem;color:#6b7280;margin-top:3px;'>"
                    f"🕒 {ts} &nbsp;·&nbsp; 📁 {filename} &nbsp;·&nbsp; "
                    f"⚡ {proc_t:.1f}s</div>",
                    unsafe_allow_html=True,
                )
            with h2:
                st.markdown(
                    f"<div style='margin-top:4px;'>Confidence: {_conf_badge(conf)}</div>",
                    unsafe_allow_html=True,
                )
            with h3:
                st.markdown(
                    f"<div style='margin-top:4px;font-size:.82rem;font-weight:700;"
                    f"color:{status_color};'>● {status.title()}</div>",
                    unsafe_allow_html=True,
                )

            st.markdown("<hr style='margin:.6rem 0;border-color:#e5e7eb;'>", unsafe_allow_html=True)

            # ── Pathologist report ─────────────────────────────────────────
            path_json = d.get("pathologist_report")
            ext_json  = d.get("extension_report")

            p_rep: Dict = {}
            e_rep: Dict = {}
            if path_json:
                try:
                    p_rep = json.loads(path_json) if isinstance(path_json, str) else path_json
                except (json.JSONDecodeError, TypeError):
                    p_rep = {}
            if ext_json:
                try:
                    e_rep = json.loads(ext_json) if isinstance(ext_json, str) else ext_json
                except (json.JSONDecodeError, TypeError):
                    e_rep = {}

            if p_rep:
                st.markdown(
                    "<div style='font-size:.72rem;font-weight:700;letter-spacing:1.2px;"
                    "text-transform:uppercase;color:#16a34a;margin-bottom:.4rem;'>"
                    "🔬 Pathologist Report — Google Gemini Vision</div>",
                    unsafe_allow_html=True,
                )
                _render_pathologist_card(p_rep)
            else:
                st.warning("Pathologist report not available for this diagnosis.")

            if e_rep:
                st.markdown(
                    "<div style='font-size:.72rem;font-weight:700;letter-spacing:1.2px;"
                    "text-transform:uppercase;color:#16a34a;margin:.8rem 0 .4rem;'>"
                    "🌿 Farm Advisory — IBM Granite</div>",
                    unsafe_allow_html=True,
                )
                _render_extension_card(e_rep)
            else:
                st.warning("Farm advisory report not available for this diagnosis.")

            # ── Combined plain-text report ────────────────────────────────
            combined = d.get("combined_report") or ""
            if combined:
                if show_raw:
                    st.markdown("**📄 Full Combined Report (plain text)**")
                    st.text_area(
                        "Full report text",
                        value=combined,
                        height=300,
                        key=f"dash_combined_{d.get('id', idx)}",
                        label_visibility="collapsed",
                        disabled=True,
                    )
                # Download button for each report
                st.download_button(
                    label="⬇️ Download Full Advisory (TXT)",
                    data=combined.encode(),
                    file_name=f"agri_advisory_{ts.replace(':', '-').replace(' ', '_')}.txt",
                    mime="text/plain",
                    key=f"dash_dl_{d.get('id', idx)}",
                )
