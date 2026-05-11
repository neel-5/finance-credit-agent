"""
Finance Credit Follow-Up Email Agent – Streamlit Dashboard
Tabs: Invoice Overview | Email Generation & Preview | Audit Log | Escalations
"""

import os
import sqlite3
from datetime import date, datetime

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv()


def load_streamlit_secrets_into_env() -> None:
    """
    Streamlit Cloud exposes secrets through st.secrets. Copy the keys this app
    needs into os.environ before importing agent.py, whose constants read env.
    """
    secret_keys = (
        "GEMINI_API_KEY",
        "GEMINI_MODEL",
        "DB_PATH",
        "SMTP_HOST",
        "SMTP_PORT",
        "SMTP_USER",
        "SMTP_PASS",
        "SENDER_EMAIL",
    )
    try:
        for key in secret_keys:
            if key in st.secrets and not os.getenv(key):
                os.environ[key] = str(st.secrets[key])
    except Exception:
        # Local runs often do not have a Streamlit secrets file.
        pass


load_streamlit_secrets_into_env()

from agent import (
    DB_PATH,
    GEMINI_MODEL,
    STAGE_CONFIG,
    determine_stage,
    generate_email,
    init_db,
    load_invoices,
    log_email,
    log_escalation,
    process_invoices,
    send_email,
)

# ── Page Config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Credit Follow-Up Agent",
    page_icon="",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

    /* ── Base Reset ── */
    html, body, [class*="css"] {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
        color: #1e293b;
    }

    .main .block-container {
        padding-top: 1.5rem;
        padding-bottom: 2rem;
        max-width: 1280px;
    }

    /* ── Sidebar ── */
    div[data-testid="stSidebar"] {
        background: #f8fafc;
        border-right: 1px solid #e2e8f0;
    }
    div[data-testid="stSidebar"] * {
        color: #334155 !important;
    }
    div[data-testid="stSidebar"] .stTextInput > label,
    div[data-testid="stSidebar"] .stToggle > label {
        font-size: 0.78rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        color: #64748b !important;
    }
    div[data-testid="stSidebar"] .sidebar-logo {
        font-size: 1.05rem;
        font-weight: 700;
        color: #0f172a !important;
        letter-spacing: -0.3px;
    }
    div[data-testid="stSidebar"] .sidebar-divider {
        border: none;
        border-top: 1px solid #e2e8f0;
        margin: 1rem 0;
    }
    div[data-testid="stSidebar"] .sidebar-meta-label {
        font-size: 0.7rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.07em;
        color: #94a3b8 !important;
        margin-bottom: 0.15rem;
    }
    div[data-testid="stSidebar"] .sidebar-meta-value {
        font-size: 0.82rem;
        font-family: 'JetBrains Mono', monospace;
        color: #334155 !important;
        background: #f1f5f9;
        border: 1px solid #e2e8f0;
        border-radius: 4px;
        padding: 3px 8px;
        display: inline-block;
        margin-bottom: 0.6rem;
    }

    /* ── Page Header ── */
    .page-header {
        display: flex;
        align-items: center;
        gap: 0.75rem;
        margin-bottom: 0.2rem;
    }
    .page-header-icon {
        width: 36px;
        height: 36px;
        background: linear-gradient(135deg, #0f4c81 0%, #0d7e8a 100%);
        border-radius: 8px;
        display: flex;
        align-items: center;
        justify-content: center;
    }
    .page-title {
        font-size: 1.45rem;
        font-weight: 700;
        color: #0f172a;
        letter-spacing: -0.5px;
        line-height: 1.2;
        margin: 0;
    }
    .page-subtitle {
        font-size: 0.82rem;
        color: #64748b;
        margin: 0 0 1.4rem 0;
        font-weight: 400;
    }

    /* ── Section Headings ── */
    .section-heading {
        font-size: 0.7rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.1em;
        color: #94a3b8;
        margin-bottom: 0.75rem;
        margin-top: 0.25rem;
    }

    /* ── KPI Cards ── */
    .kpi-card {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        padding: 1.1rem 1.25rem;
        box-shadow: 0 1px 4px rgba(15,23,42,0.05);
        position: relative;
        overflow: hidden;
    }
    .kpi-card::before {
        content: '';
        position: absolute;
        top: 0; left: 0;
        width: 3px; height: 100%;
        background: #0d7e8a;
        border-radius: 10px 0 0 10px;
    }
    .kpi-card.accent-navy::before  { background: #0f4c81; }
    .kpi-card.accent-teal::before  { background: #0d7e8a; }
    .kpi-card.accent-amber::before { background: #d97706; }
    .kpi-card.accent-rose::before  { background: #be123c; }
    .kpi-label {
        font-size: 0.7rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.07em;
        color: #64748b;
        margin-bottom: 0.35rem;
    }
    .kpi-value {
        font-size: 1.65rem;
        font-weight: 700;
        color: #0f172a;
        line-height: 1;
        letter-spacing: -0.5px;
    }
    .kpi-sub {
        font-size: 0.73rem;
        color: #94a3b8;
        margin-top: 0.3rem;
    }

    /* ── Content Cards ── */
    .content-card {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        padding: 1.25rem 1.4rem;
        box-shadow: 0 1px 4px rgba(15,23,42,0.04);
        margin-bottom: 1rem;
    }

    /* ── Stage Badges ── */
    .badge {
        display: inline-flex;
        align-items: center;
        padding: 2px 9px;
        border-radius: 20px;
        font-size: 0.7rem;
        font-weight: 600;
        letter-spacing: 0.03em;
        font-family: 'Inter', sans-serif;
    }
    .badge-stage-1  { background: #dcfce7; color: #166534; }
    .badge-stage-2  { background: #fef9c3; color: #854d0e; }
    .badge-stage-3  { background: #ffedd5; color: #9a3412; }
    .badge-stage-4  { background: #fee2e2; color: #991b1b; }
    .badge-escalated { background: #ede9fe; color: #5b21b6; }
    .badge-sent     { background: #dcfce7; color: #166534; }
    .badge-dryrun   { background: #f0f9ff; color: #0369a1; }
    .badge-warning  { background: #fffbeb; color: #92400e; }
    .badge-error    { background: #fff1f2; color: #be123c; }

    /* ── Invoice Detail Row ── */
    .detail-row {
        display: flex;
        flex-direction: column;
        gap: 0.1rem;
        margin-bottom: 0.6rem;
    }
    .detail-label {
        font-size: 0.68rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        color: #94a3b8;
    }
    .detail-value {
        font-size: 0.88rem;
        font-weight: 500;
        color: #1e293b;
    }

    /* ── Email Preview ── */
    .email-preview-wrap {
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 1.25rem 1.4rem;
    }
    .email-subject {
        font-size: 0.78rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.07em;
        color: #64748b;
        margin-bottom: 0.2rem;
    }
    .email-subject-value {
        font-size: 0.92rem;
        font-weight: 600;
        color: #0f172a;
        font-family: 'JetBrains Mono', monospace;
        background: #f1f5f9;
        border: 1px solid #e2e8f0;
        padding: 5px 10px;
        border-radius: 5px;
        margin-bottom: 0.9rem;
        display: block;
    }
    .email-body {
        font-family: 'JetBrains Mono', monospace;
        font-size: 0.78rem;
        line-height: 1.75;
        color: #334155;
        white-space: pre-wrap;
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 6px;
        padding: 1rem 1.2rem;
    }

    /* ── Alert Variants ── */
    .alert {
        padding: 0.65rem 1rem;
        border-radius: 7px;
        font-size: 0.84rem;
        font-weight: 500;
        border-left: 3px solid;
        margin-bottom: 0.75rem;
    }
    .alert-info    { background: #f0f9ff; border-color: #0369a1; color: #0c4a6e; }
    .alert-warning { background: #fffbeb; border-color: #d97706; color: #78350f; }
    .alert-error   { background: #fff1f2; border-color: #be123c; color: #881337; }
    .alert-success { background: #f0fdf4; border-color: #16a34a; color: #14532d; }

    /* ── Escalation Card ── */
    .esc-banner {
        background: #fff1f2;
        border: 1px solid #fecdd3;
        border-left: 4px solid #be123c;
        border-radius: 8px;
        padding: 0.85rem 1.1rem;
        margin-bottom: 1rem;
    }
    .esc-banner-title {
        font-size: 0.78rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.07em;
        color: #be123c;
        margin-bottom: 0.2rem;
    }
    .esc-banner-body {
        font-size: 0.84rem;
        color: #4c1d24;
    }

    /* ── Next Steps ── */
    .next-steps {
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 0.9rem 1.1rem;
        font-size: 0.84rem;
        color: #475569;
        line-height: 1.6;
    }
    .next-steps strong {
        color: #0f172a;
    }

    /* ── Tabs ── */
    div[data-testid="stTabs"] button {
        font-size: 0.82rem;
        font-weight: 600;
        text-transform: none;
        letter-spacing: 0.01em;
        color: #64748b;
        border-radius: 0;
        padding: 0.5rem 1.1rem;
    }
    div[data-testid="stTabs"] button[aria-selected="true"] {
        color: #0d7e8a;
        border-bottom: 2px solid #0d7e8a;
    }

    /* ── Buttons ── */
    .stButton > button {
        border-radius: 7px;
        font-size: 0.83rem;
        font-weight: 600;
        letter-spacing: 0.01em;
        transition: all 0.15s ease;
    }
    .stButton > button[kind="primary"] {
        background: linear-gradient(135deg, #0f4c81 0%, #0d7e8a 100%);
        border: none;
        color: #ffffff;
    }
    .stButton > button[kind="primary"]:hover {
        opacity: 0.92;
        transform: translateY(-1px);
        box-shadow: 0 4px 12px rgba(13,78,138,0.25);
    }
    .stButton > button[kind="secondary"] {
        background: #ffffff;
        border: 1.5px solid #cbd5e1;
        color: #334155;
    }
    .stButton > button[kind="secondary"]:hover {
        border-color: #0d7e8a;
        color: #0d7e8a;
        background: #f0fafb;
    }

    /* ── Divider ── */
    .styled-divider {
        border: none;
        border-top: 1px solid #f1f5f9;
        margin: 1.2rem 0;
    }

    /* ── Status pill in result row ── */
    .result-row {
        display: flex;
        align-items: center;
        gap: 0.6rem;
        padding: 0.55rem 0;
        border-bottom: 1px solid #f1f5f9;
        font-size: 0.83rem;
    }
    .result-inv {
        font-family: 'JetBrains Mono', monospace;
        font-weight: 600;
        font-size: 0.78rem;
        color: #0f172a;
        min-width: 110px;
    }
    .result-client { color: #475569; flex: 1; }

    /* ── Table overrides ── */
    .stDataFrame { border-radius: 8px; overflow: hidden; border: 1px solid #e2e8f0; }

    /* ── Streamlit metric overrides ── */
    [data-testid="metric-container"] {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        padding: 0.9rem 1rem;
        box-shadow: 0 1px 3px rgba(15,23,42,0.05);
    }
    [data-testid="metric-container"] label {
        font-size: 0.7rem !important;
        font-weight: 600 !important;
        text-transform: uppercase;
        letter-spacing: 0.07em;
        color: #64748b !important;
    }
    [data-testid="metric-container"] [data-testid="stMetricValue"] {
        font-size: 1.6rem !important;
        font-weight: 700 !important;
        color: #0f172a !important;
        letter-spacing: -0.5px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

def get_db_conn():
    return sqlite3.connect(os.getenv("DB_PATH", DB_PATH))


def fetch_audit_log() -> pd.DataFrame:
    conn = get_db_conn()
    try:
        df = pd.read_sql_query("SELECT * FROM email_audit ORDER BY timestamp DESC", conn)
    except Exception:
        df = pd.DataFrame()
    conn.close()
    return df


def fetch_escalations() -> pd.DataFrame:
    conn = get_db_conn()
    try:
        df = pd.read_sql_query("SELECT * FROM escalation_log ORDER BY timestamp DESC", conn)
    except Exception:
        df = pd.DataFrame()
    conn.close()
    return df


def stage_label_html(stage):
    if pd.isna(stage) or stage == "ESCALATED":
        return '<span class="badge badge-escalated">Escalated</span>'
    m = {1: "badge-stage-1", 2: "badge-stage-2", 3: "badge-stage-3", 4: "badge-stage-4"}
    labels = {1: "Stage 1", 2: "Stage 2", 3: "Stage 3", 4: "Stage 4"}
    try:
        s = int(float(stage))
        return f'<span class="badge {m.get(s, "")}">{labels.get(s, stage)}</span>'
    except Exception:
        return f'<span class="badge badge-escalated">{stage}</span>'


def status_badge_html(status):
    status_text = str(status or "")
    if status_text == "sent":
        return '<span class="badge badge-sent">sent</span>'
    if status_text == "dry_run":
        return '<span class="badge badge-dryrun">dry run</span>'
    if status_text == "template_fallback":
        return '<span class="badge badge-warning">template fallback</span>'
    if status_text == "escalated":
        return '<span class="badge badge-escalated">escalated</span>'
    if status_text.startswith("generation_error"):
        return '<span class="badge badge-error">generation error</span>'
    if status_text.startswith("send_error"):
        return '<span class="badge badge-error">send error</span>'
    return f'<span class="badge badge-dryrun">{status_text}</span>'


def status_detail(status):
    status_text = str(status or "")
    if ": " in status_text:
        return status_text.split(": ", 1)[1]
    return ""


def load_data(csv_path: str) -> pd.DataFrame | None:
    try:
        df = load_invoices(csv_path)
        df["stage"] = df["days_overdue"].apply(determine_stage)
        return df
    except Exception as exc:
        st.error(f"Failed to load CSV: {exc}")
        return None


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown(
        '<div class="sidebar-logo">Finance Credit Agent</div>',
        unsafe_allow_html=True,
    )
    st.markdown('<hr class="sidebar-divider">', unsafe_allow_html=True)

    st.markdown('<div class="section-heading">Data Sources</div>', unsafe_allow_html=True)
    csv_path = st.text_input("CSV Path", value="invoices.csv")
    db_path  = st.text_input("SQLite DB", value=os.getenv("DB_PATH", DB_PATH))

    st.markdown('<hr class="sidebar-divider">', unsafe_allow_html=True)
    st.markdown('<div class="section-heading">Run Mode</div>', unsafe_allow_html=True)
    dry_run = st.toggle("Dry-Run Mode", value=True)
    if dry_run:
        st.markdown(
            '<div class="alert alert-info">Emails will be <strong>generated and logged</strong> but NOT sent.</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div class="alert alert-warning">Live mode: emails will be <strong>sent</strong> via SMTP.</div>',
            unsafe_allow_html=True,
        )

    st.markdown('<hr class="sidebar-divider">', unsafe_allow_html=True)
    st.markdown('<div class="section-heading">System Info</div>', unsafe_allow_html=True)

    st.markdown('<div class="sidebar-meta-label">Model</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="sidebar-meta-value">{GEMINI_MODEL}</div>', unsafe_allow_html=True)

    st.markdown('<div class="sidebar-meta-label">Framework</div>', unsafe_allow_html=True)
    st.markdown('<div class="sidebar-meta-value">Custom Agent + Gemini API</div>', unsafe_allow_html=True)

    api_key_set = bool(os.getenv("GEMINI_API_KEY"))
    if api_key_set:
        st.markdown(
            '<div class="alert alert-success" style="margin-top:0.5rem;">GEMINI_API_KEY loaded</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div class="alert alert-error" style="margin-top:0.5rem;">GEMINI_API_KEY not set</div>',
            unsafe_allow_html=True,
        )

init_db(db_path)

# ── Page Header ───────────────────────────────────────────────────────────────
st.markdown(
    """
    <div class="page-header">
        <div class="page-header-icon">
            <svg width="20" height="20" fill="none" viewBox="0 0 24 24">
                <path d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"
                      stroke="#ffffff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
        </div>
        <div>
            <div class="page-title">Credit Follow-Up Agent</div>
        </div>
    </div>
    <div class="page-subtitle">Automated overdue payment follow-up &nbsp;|&nbsp; AI-generated, human-reviewed</div>
    """,
    unsafe_allow_html=True,
)

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4 = st.tabs(
    ["Invoice Overview", "Email Generation & Preview", "Audit Log", "Escalations"]
)

# ════════════════════════════════════════════════════════════════════════════
# TAB 1 – Invoice Overview
# ════════════════════════════════════════════════════════════════════════════
with tab1:
    st.markdown('<div class="section-heading">Portfolio Summary</div>', unsafe_allow_html=True)

    df = load_data(csv_path)
    if df is None:
        st.stop()

    total        = len(df)
    escalated    = df["stage"].isna().sum()
    active       = total - escalated
    total_amount = df["amount"].sum()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Overdue",       total)
    c2.metric("Active  (Stage 1–4)", int(active))
    c3.metric("Escalated  (> 30 d)", int(escalated))
    c4.metric("Total Outstanding",   f"₹{total_amount:,.0f}")

    st.markdown('<hr class="styled-divider">', unsafe_allow_html=True)

    # Stage breakdown bar chart
    st.markdown('<div class="section-heading">Stage Distribution</div>', unsafe_allow_html=True)

    stage_counts = (
        df["stage"]
        .fillna("ESCALATED")
        .astype(str)
        .value_counts()
        .sort_index()
    )
    stage_df = stage_counts.reset_index()
    stage_df.columns = ["Stage", "Count"]

    st.bar_chart(
        stage_df.set_index("Stage"),
        color="#0d7e8a",
        height=220,
    )

    st.markdown('<hr class="styled-divider">', unsafe_allow_html=True)

    # Invoice table
    st.markdown('<div class="section-heading">Invoice Register</div>', unsafe_allow_html=True)

    display_df = df[[
        "invoice_no", "client_name", "amount", "currency",
        "due_date", "days_overdue", "stage", "contact_email",
    ]].copy()
    display_df["stage"] = display_df["stage"].fillna("ESCALATED")

    def style_stage(val):
        colours = {
            "1": "background-color:#dcfce7; color:#166534",
            "1.0": "background-color:#dcfce7; color:#166534",
            "2": "background-color:#fef9c3; color:#854d0e",
            "2.0": "background-color:#fef9c3; color:#854d0e",
            "3": "background-color:#ffedd5; color:#9a3412",
            "3.0": "background-color:#ffedd5; color:#9a3412",
            "4": "background-color:#fee2e2; color:#991b1b",
            "4.0": "background-color:#fee2e2; color:#991b1b",
            "ESCALATED": "background-color:#ede9fe; color:#5b21b6",
        }
        return colours.get(str(val), "")

    st.dataframe(
        display_df.style.map(style_stage, subset=["stage"]),
        use_container_width=True,
        hide_index=True,
    )

# ════════════════════════════════════════════════════════════════════════════
# TAB 2 – Email Generation & Preview
# ════════════════════════════════════════════════════════════════════════════
with tab2:
    st.markdown(
        '<div style="font-size:1.05rem;font-weight:700;color:#0f172a;margin-bottom:0.15rem;">Generate & Preview Follow-Up Emails</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div style="font-size:0.8rem;color:#64748b;margin-bottom:1rem;">Select an invoice to preview or run the agent across all records.</div>',
        unsafe_allow_html=True,
    )

    df2 = load_data(csv_path)
    if df2 is None:
        st.stop()

    col_a, col_b = st.columns([1, 2])

    with col_a:
        st.markdown('<div class="section-heading">Select Invoice</div>', unsafe_allow_html=True)
        invoice_options = df2["invoice_no"].tolist()
        selected_inv = st.selectbox("Invoice", invoice_options, key="inv_select", label_visibility="collapsed")

        row_sel   = df2[df2["invoice_no"] == selected_inv].iloc[0]
        stage_sel = row_sel["stage"]

        st.markdown(
            f"""
            <div class="content-card" style="margin-top:0.5rem;">
                <div class="detail-row">
                    <div class="detail-label">Client</div>
                    <div class="detail-value">{row_sel['client_name']}</div>
                </div>
                <div class="detail-row">
                    <div class="detail-label">Days Overdue</div>
                    <div class="detail-value" style="font-family:'JetBrains Mono',monospace;color:#be123c;font-weight:700;">{int(row_sel['days_overdue'])} days</div>
                </div>
                <div class="detail-row">
                    <div class="detail-label">Stage</div>
                    <div class="detail-value">{stage_label_html(stage_sel)}</div>
                </div>
                <div class="detail-row">
                    <div class="detail-label">Amount</div>
                    <div class="detail-value">{row_sel['currency']} {float(row_sel['amount']):,.2f}</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if pd.isna(stage_sel):
            st.markdown(
                '<div class="alert alert-error">This invoice is escalated (&gt;30 days). No email will be generated.</div>',
                unsafe_allow_html=True,
            )
        else:
            stage_label_text = STAGE_CONFIG[int(stage_sel)]["label"]
            st.markdown(
                f'<div class="alert alert-info">Tone: <strong>{STAGE_CONFIG[int(stage_sel)]["tone"]}</strong></div>',
                unsafe_allow_html=True,
            )

        st.markdown('<div style="height:0.5rem;"></div>', unsafe_allow_html=True)
        gen_single = st.button("Generate Email for This Invoice", use_container_width=True)
        st.markdown('<div style="height:0.4rem;"></div>', unsafe_allow_html=True)
        gen_all = st.button("Run Agent on ALL Invoices", type="primary", use_container_width=True)

    with col_b:
        if gen_single:
            if pd.isna(stage_sel):
                st.markdown(
                    '<div class="alert alert-warning">Cannot generate email — invoice is in legal escalation territory.</div>',
                    unsafe_allow_html=True,
                )
            else:
                with st.spinner("Calling Gemini API..."):
                    try:
                        row_dict = row_sel.to_dict()
                        row_dict["due_date"] = str(row_dict["due_date"])
                        result = generate_email(
                            row_dict,
                            int(stage_sel),
                            allow_template_fallback=dry_run,
                        )

                        success_text = (
                            "Template email prepared because Gemini is unavailable."
                            if result.get("provider") == "template_fallback"
                            else "Email generated successfully."
                        )
                        st.markdown(
                            f'<div class="alert alert-success">{success_text}</div>',
                            unsafe_allow_html=True,
                        )
                        if result.get("warning"):
                            st.markdown(
                                f'<div class="alert alert-warning">{result["warning"]}</div>',
                                unsafe_allow_html=True,
                            )
                        st.markdown(
                            f"""
                            <div class="email-preview-wrap">
                                <div class="email-subject">Subject</div>
                                <span class="email-subject-value">{result['subject']}</span>
                                <div class="email-subject" style="margin-top:0.5rem;">Body</div>
                                <div class="email-body">{result['body']}</div>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )

                        if dry_run:
                            send_status = (
                                "template_fallback"
                                if result.get("provider") == "template_fallback"
                                else "dry_run"
                            )
                        else:
                            try:
                                send_email(row_dict["contact_email"], result["subject"], result["body"])
                                send_status = "sent"
                                st.markdown(
                                    f'<div class="alert alert-success">Email dispatched to {row_dict["contact_email"]}</div>',
                                    unsafe_allow_html=True,
                                )
                            except Exception as e:
                                send_status = f"send_error: {e}"
                                st.markdown(
                                    f'<div class="alert alert-error">Send failed: {e}</div>',
                                    unsafe_allow_html=True,
                                )

                        log_email(
                            invoice_no    = row_dict["invoice_no"],
                            client_name   = row_dict["client_name"],
                            contact_email = row_dict["contact_email"],
                            amount        = float(row_dict["amount"]),
                            currency      = row_dict["currency"],
                            due_date      = row_dict["due_date"],
                            days_overdue  = int(row_dict["days_overdue"]),
                            stage         = int(stage_sel),
                            tone          = STAGE_CONFIG[int(stage_sel)]["tone"],
                            subject       = result["subject"],
                            body          = result["body"],
                            send_status   = send_status,
                            dry_run       = dry_run,
                            db_path       = db_path,
                        )
                    except Exception as e:
                        st.markdown(
                            f'<div class="alert alert-error">Generation failed: {e}</div>',
                            unsafe_allow_html=True,
                        )

        if gen_all:
            with st.spinner("Processing all overdue invoices..."):
                results = process_invoices(
                    csv_path=csv_path,
                    dry_run=dry_run,
                    db_path=db_path,
                    allow_template_fallback=dry_run,
                )

            st.markdown(
                f'<div class="alert alert-success">Processed {len(results)} invoices.</div>',
                unsafe_allow_html=True,
            )
            st.markdown('<div class="section-heading" style="margin-top:0.8rem;">Results</div>', unsafe_allow_html=True)

            for r in results:
                stage_disp  = r.get("stage", "ESCALATED")
                status_text = r.get("send_status", "—")
                badge_html  = stage_label_html(stage_disp)
                status_html = status_badge_html(status_text)

                st.markdown(
                    f"""
                    <div class="result-row">
                        <span class="result-inv">{r['invoice_no']}</span>
                        <span class="result-client">{r['client_name']}</span>
                        {badge_html}
                        {status_html}
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                detail = r.get("generation_warning") or status_detail(status_text)
                if detail:
                    st.markdown(
                        f'<div class="alert alert-warning">{detail}</div>',
                        unsafe_allow_html=True,
                    )
                if r.get("body"):
                    with st.expander(f"Preview: {r['invoice_no']}"):
                        st.markdown(
                            f"""
                            <div class="email-preview-wrap">
                                <div class="email-subject">Subject</div>
                                <span class="email-subject-value">{r.get('subject', '')}</span>
                                <div class="email-subject" style="margin-top:0.5rem;">Body</div>
                                <div class="email-body">{r['body']}</div>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )

# ════════════════════════════════════════════════════════════════════════════
# TAB 3 – Audit Log
# ════════════════════════════════════════════════════════════════════════════
with tab3:
    st.markdown(
        '<div style="font-size:1.05rem;font-weight:700;color:#0f172a;margin-bottom:0.15rem;">Email Audit Log</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div style="font-size:0.8rem;color:#64748b;margin-bottom:1rem;">Complete record of all generated and dispatched emails.</div>',
        unsafe_allow_html=True,
    )

    audit_df = fetch_audit_log()

    if audit_df.empty:
        st.markdown(
            '<div class="alert alert-info">No emails logged yet. Run the agent from the Email Generation tab.</div>',
            unsafe_allow_html=True,
        )
    else:
        sent_count = (audit_df["send_status"] == "sent").sum()
        dry_count  = (audit_df["send_status"] == "dry_run").sum()

        col1, col2, col3 = st.columns(3)
        col1.metric("Total Logged",   len(audit_df))
        col2.metric("Actually Sent",  int(sent_count))
        col3.metric("Dry-Run Only",   int(dry_count))

        st.markdown('<hr class="styled-divider">', unsafe_allow_html=True)

        st.markdown('<div class="section-heading">Filters</div>', unsafe_allow_html=True)
        fc1, fc2 = st.columns(2)
        with fc1:
            stage_filter = st.multiselect(
                "Stage",
                options=sorted(audit_df["stage"].unique().tolist()),
                default=[],
            )
        with fc2:
            status_filter = st.multiselect(
                "Send Status",
                options=sorted(audit_df["send_status"].unique().tolist()),
                default=[],
            )

        filtered = audit_df.copy()
        if stage_filter:
            filtered = filtered[filtered["stage"].isin(stage_filter)]
        if status_filter:
            filtered = filtered[filtered["send_status"].isin(status_filter)]

        display_cols = [
            "timestamp", "invoice_no", "client_name", "contact_email",
            "amount", "currency", "days_overdue", "stage", "tone",
            "subject", "send_status", "dry_run",
        ]
        st.dataframe(filtered[display_cols], use_container_width=True, hide_index=True)

        st.markdown('<hr class="styled-divider">', unsafe_allow_html=True)
        st.markdown('<div class="section-heading">Full Email Body</div>', unsafe_allow_html=True)

        if not filtered.empty:
            row_ids = filtered["id"].tolist()
            sel_id  = st.selectbox("Select Audit Record ID", row_ids)
            sel_row = filtered[filtered["id"] == sel_id].iloc[0]
            st.markdown(
                f"""
                <div class="email-preview-wrap">
                    <div class="email-subject">Subject</div>
                    <span class="email-subject-value">{sel_row['subject']}</span>
                    <div class="email-subject" style="margin-top:0.5rem;">Body</div>
                    <div class="email-body">{sel_row['body']}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

# ════════════════════════════════════════════════════════════════════════════
# TAB 4 – Escalations
# ════════════════════════════════════════════════════════════════════════════
with tab4:
    st.markdown(
        '<div style="font-size:1.05rem;font-weight:700;color:#0f172a;margin-bottom:0.15rem;">Legal / Finance Escalation Queue</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div style="font-size:0.8rem;color:#64748b;margin-bottom:1rem;">Invoices overdue by more than 30 days — no automated emails are sent for these records.</div>',
        unsafe_allow_html=True,
    )

    esc_df = fetch_escalations()

    if esc_df.empty:
        st.markdown(
            '<div class="alert alert-info">No escalations logged yet.</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f"""
            <div class="esc-banner">
                <div class="esc-banner-title">Action Required</div>
                <div class="esc-banner-body">
                    {len(esc_df)} invoice(s) require immediate human review.
                    No automated emails have been sent for these records.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.dataframe(
            esc_df[[
                "timestamp", "invoice_no", "client_name", "contact_email",
                "amount", "currency", "due_date", "days_overdue", "status",
            ]],
            use_container_width=True,
            hide_index=True,
        )

        st.markdown('<hr class="styled-divider">', unsafe_allow_html=True)

        st.markdown(
            """
            <div class="next-steps">
                <strong>Recommended next steps:</strong> Assign these records to a Finance Manager or Legal
                team member for manual review and potential formal proceedings.
                Ensure all correspondence is logged outside of this system.
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown('<div style="height:0.8rem;"></div>', unsafe_allow_html=True)
        st.markdown('<div class="section-heading">Mark as Reviewed</div>', unsafe_allow_html=True)

        inv_options = esc_df["invoice_no"].tolist()
        to_review   = st.selectbox("Invoice", inv_options, label_visibility="collapsed")

        if st.button("Mark Reviewed"):
            conn = get_db_conn()
            conn.execute(
                "UPDATE escalation_log SET status = 'reviewed' WHERE invoice_no = ?",
                (to_review,),
            )
            conn.commit()
            conn.close()
            st.markdown(
                f'<div class="alert alert-success">{to_review} marked as reviewed.</div>',
                unsafe_allow_html=True,
            )
            st.rerun()
