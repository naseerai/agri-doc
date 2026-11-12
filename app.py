"""
app.py — Agri Doctor · AI Crop Health Assistant
Run: source venv/bin/activate && streamlit run app.py
"""
import io, os, uuid, time, json, logging, urllib.parse, webbrowser
from datetime import datetime
from typing import Optional, Dict, Any

import streamlit as st
import streamlit.components.v1 as components
from PIL import Image

try:
    from streamlit_lottie import st_lottie
    LOTTIE_OK = True
except ImportError:
    LOTTIE_OK = False

from config import (
    APP_VERSION,
    WATSONX_API_KEY, WATSONX_PROJECT_ID, WATSONX_URL, WATSONX_MODEL_ID,
    GROQ_API_KEY, GROQ_MODEL_ID, GEMINI_API_KEY, GEMINI_MODEL_ID,
    DEFAULT_WA_PHONE, TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER,
    WHATSAPP_ACCESS_TOKEN, WHATSAPP_PHONE_NUMBER_ID,
    save_env_variables,
)
from database import (
    initialize_database, save_diagnosis, get_recent_diagnoses,
    get_diagnosis_stats, get_recent_wa_deliveries,
)
from agents.pathologist_agent import PathologistAgent
from agents.extension_officer_agent import ExtensionOfficerAgent
from services.ibm_service import test_watsonx_connection
from services.gemini_service import test_gemini_connection
from services.groq_service import test_groq_connection
from services.whatsapp_service import (
    send_whatsapp_report, get_whatsapp_urls, PYWHATKIT_AVAILABLE,
    format_report_as_whatsapp_text, split_message_into_parts,
)
from agents.whatsapp_agent import (
    WhatsAppReportAgent,
    STATUS_IDLE, STATUS_READY, STATUS_PREPARED, STATUS_SENT,
    STATUS_FAILED, STATUS_PROCESSING, STATUS_DELIVERED, STATUS_READ,
    AGENT_NAME as WA_AGENT_NAME,
)
from dashboard import render_performance_dashboard

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
initialize_database()

# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Agri Doctor",
    page_icon="🌿",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Load Lottie assets ────────────────────────────────────────────────────────
_A = os.path.join(os.path.dirname(__file__), "assets")
def _lj(n):
    try:
        with open(os.path.join(_A, n), encoding="utf-8") as f: return json.load(f)
    except: return None

LOTTIE_CORN = _lj("corn_growing.json")
LOTTIE_GIRL = _lj("girl_watering.json")

# ══════════════════════════════════════════════════════════════════════════════
#  GLOBAL CSS  — Brand-new design language
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("""
<style>
/* ═══ Root variables ══════════════════════════════════════════════════════ */
:root {
  --green:   #16a34a;
  --dark:    #14532d;
  --darker:  #052e16;
  --light:   #f0fdf4;
  --cream:   #fafaf8;
  --muted:   #6b7280;
  --border:  #e5e7eb;
  --radius:  14px;
  --shadow:  0 1px 3px rgba(0,0,0,.07), 0 8px 24px rgba(0,0,0,.06);
}

/* ═══ Reset ═══════════════════════════════════════════════════════════════ */
html, body, [data-testid="stAppViewContainer"],
[data-testid="stMain"], .main {
  background: var(--cream) !important;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif !important;
}
.block-container {
  padding: 0 2rem 4rem !important;
  max-width: 1160px !important;
  margin: 0 auto !important;
}

/* ═══ Sidebar ═════════════════════════════════════════════════════════════ */
[data-testid="stSidebar"] {
  background: var(--darker) !important;
  border-right: 1px solid rgba(255,255,255,.05) !important;
}
[data-testid="stSidebar"] * { color: #a7f3d0 !important; }
[data-testid="stSidebar"] .stRadio label {
  font-size: .82rem !important; padding: .05rem 0 !important;
}
[data-testid="stSidebar"] hr {
  border-color: rgba(255,255,255,.08) !important;
  margin: .5rem 0 !important;
}

/* ═══ Lottie — no black box ═══════════════════════════════════════════════ */
[data-testid="stLottie"], iframe[title="streamlit_lottie"],
.stLottie, div.stLottie > iframe,
.element-container iframe, iframe {
  background: transparent !important;
  border: none !important;
  box-shadow: none !important;
}

/* ═══ Top navigation bar ══════════════════════════════════════════════════ */
.topbar {
  background: var(--dark);
  padding: 1rem 2rem;
  margin: 0 -2rem 2rem;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid rgba(255,255,255,.08);
}
.topbar-brand {
  font-size: 1.25rem;
  font-weight: 800;
  color: #fff !important;
  display: flex;
  align-items: center;
  gap: .5rem;
}
.topbar-sub { font-size: .72rem; color: #6ee7b7 !important; font-weight: 400; }

/* ═══ Hero ════════════════════════════════════════════════════════════════ */
.hero {
  background: linear-gradient(135deg, var(--darker) 0%, #14532d 50%, #166534 100%);
  border-radius: 24px;
  padding: 3rem 3.5rem;
  margin-bottom: 2.5rem;
  position: relative;
  overflow: hidden;
  box-shadow: 0 20px 60px rgba(5,46,22,.4);
}
.hero::before {
  content: '';
  position: absolute;
  top: -80px; right: -80px;
  width: 360px; height: 360px;
  background: radial-gradient(circle, rgba(74,222,128,.12) 0%, transparent 70%);
  border-radius: 50%;
  pointer-events: none;
}
.hero-tag {
  display: inline-block;
  background: rgba(74,222,128,.15);
  border: 1px solid rgba(74,222,128,.3);
  border-radius: 100px;
  padding: 3px 14px;
  font-size: .68rem;
  font-weight: 700;
  letter-spacing: 1.5px;
  text-transform: uppercase;
  color: #4ade80 !important;
  margin-bottom: .9rem;
}
.hero h1 {
  font-size: 3rem;
  font-weight: 900;
  color: #fff !important;
  margin: 0 0 .8rem;
  line-height: 1.1;
  letter-spacing: -1px;
}
.hero h1 em { color: #4ade80 !important; font-style: normal; }
.hero p {
  font-size: 1.05rem;
  color: rgba(255,255,255,.70) !important;
  margin: 0 0 1.4rem;
  line-height: 1.65;
  max-width: 520px;
}
.hero-chips { display: flex; flex-wrap: wrap; gap: .5rem; }
.hero-chip {
  background: rgba(255,255,255,.1);
  border: 1px solid rgba(255,255,255,.18);
  border-radius: 100px;
  padding: 4px 14px;
  font-size: .71rem;
  font-weight: 600;
  color: #d1fae5 !important;
}

/* ═══ Section heading ═════════════════════════════════════════════════════ */
.sec-head {
  font-size: .68rem;
  font-weight: 700;
  letter-spacing: 1.5px;
  text-transform: uppercase;
  color: var(--green) !important;
  margin-bottom: .9rem;
  display: flex;
  align-items: center;
  gap: .4rem;
}
.sec-head::after {
  content: '';
  flex: 1;
  height: 1px;
  background: var(--border);
}

/* ═══ Metric cards ════════════════════════════════════════════════════════ */
.metric-card {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 1.4rem 1.2rem 1.2rem;
  position: relative;
  overflow: hidden;
  transition: box-shadow .2s, transform .2s;
  box-shadow: var(--shadow);
}
.metric-card:hover { transform: translateY(-3px); box-shadow: 0 12px 32px rgba(0,0,0,.1); }
.metric-card .mc-icon { font-size: 1.8rem; margin-bottom: .5rem; }
.metric-card .mc-val {
  font-size: 2rem; font-weight: 900; color: var(--darker) !important;
  line-height: 1; letter-spacing: -1px;
}
.metric-card .mc-lbl {
  font-size: .68rem; font-weight: 600; text-transform: uppercase;
  letter-spacing: .8px; color: var(--muted) !important; margin-top: .3rem;
}
.metric-card .mc-bar {
  position: absolute; bottom: 0; left: 0; right: 0;
  height: 3px; border-radius: 0 0 var(--radius) var(--radius);
}
.bar-green { background: linear-gradient(90deg,#16a34a,#4ade80); }
.bar-amber { background: linear-gradient(90deg,#d97706,#fbbf24); }
.bar-blue  { background: linear-gradient(90deg,#2563eb,#60a5fa); }
.bar-red   { background: linear-gradient(90deg,#dc2626,#f87171); }

/* ═══ Plain white card ════════════════════════════════════════════════════ */
.card {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 1.4rem 1.6rem;
  box-shadow: var(--shadow);
  margin-bottom: 1rem;
}
.card-green {
  background: #fff;
  border: 1px solid #bbf7d0;
  border-left: 4px solid var(--green);
  border-radius: 0 var(--radius) var(--radius) 0;
  padding: 1rem 1.4rem;
  margin-bottom: 1rem;
}

/* ═══ Feature step ════════════════════════════════════════════════════════ */
.feat-step {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 1.4rem 1.1rem;
  text-align: center;
  box-shadow: var(--shadow);
  transition: transform .2s;
  height: 100%;
}
.feat-step:hover { transform: translateY(-4px); }
.feat-num {
  display: inline-flex; align-items: center; justify-content: center;
  width: 30px; height: 30px; border-radius: 50%;
  background: var(--green); color: #fff !important;
  font-weight: 800; font-size: .78rem; margin-bottom: .6rem;
}
.feat-icon { font-size: 2.1rem; display: block; margin-bottom: .5rem; }
.feat-title { font-size: .88rem; font-weight: 700; color: var(--darker) !important; }
.feat-desc { font-size: .74rem; color: var(--muted) !important; margin-top: .3rem; line-height: 1.5; }

/* ═══ History rows ════════════════════════════════════════════════════════ */
.hrow {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: .85rem 1.2rem;
  margin-bottom: .4rem;
  display: flex;
  justify-content: space-between;
  align-items: center;
  transition: box-shadow .15s;
}
.hrow:hover { box-shadow: 0 4px 16px rgba(0,0,0,.08); }
.hrow-title { font-size: .88rem; font-weight: 600; color: var(--darker) !important; }
.hrow-meta  { font-size: .7rem; color: var(--muted) !important; margin-top: 2px; }

/* ═══ Confidence badges ═══════════════════════════════════════════════════ */
.badge {
  display: inline-block; padding: 2px 11px;
  border-radius: 100px; font-size: .68rem; font-weight: 700;
}
.b-high    { background:#dcfce7; color:#14532d !important; border:1px solid #86efac; }
.b-medium  { background:#fef9c3; color:#713f12 !important; border:1px solid #fde047; }
.b-low     { background:#fee2e2; color:#7f1d1d !important; border:1px solid #fca5a5; }
.b-unclear { background:#f3f4f6; color:#374151 !important; border:1px solid #d1d5db; }

/* ═══ Agent step ══════════════════════════════════════════════════════════ */
.agent-box {
  display: flex; align-items: flex-start; gap: 1rem;
  background: #fff; border: 1px solid var(--border);
  border-radius: var(--radius); padding: 1.1rem 1.4rem;
  margin-bottom: .8rem; box-shadow: var(--shadow);
}
.agent-num {
  min-width: 36px; height: 36px; border-radius: 50%;
  background: var(--green); display: flex; align-items: center;
  justify-content: center; color: #fff !important;
  font-weight: 900; font-size: .9rem; flex-shrink: 0;
  box-shadow: 0 4px 12px rgba(22,163,74,.35);
}
.agent-info strong { color: var(--darker) !important; font-size: .95rem; }
.agent-info small  { color: var(--muted) !important; font-size: .74rem; }

/* ═══ Status labels ═══════════════════════════════════════════════════════ */
.st-run { color: #2563eb !important; font-weight: 600; font-size: .84rem; }
.st-ok  { color: #16a34a !important; font-weight: 600; font-size: .84rem; }
.st-err { color: #dc2626 !important; font-weight: 600; font-size: .84rem; }
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.35} }
.blink { animation: pulse 1.3s infinite; }

/* ═══ WhatsApp section ════════════════════════════════════════════════════ */
.wa-section {
  background: linear-gradient(135deg, #f0fdf4, #dcfce7);
  border: 2px solid #86efac;
  border-radius: 20px;
  padding: 1.8rem 2rem;
  margin: 1.5rem 0;
  box-shadow: 0 4px 20px rgba(22,163,74,.12);
}
.wa-title {
  font-size: 1.15rem; font-weight: 800;
  color: var(--darker) !important; margin-bottom: .3rem;
}
.wa-sub { font-size: .82rem; color: #166534 !important; margin-bottom: 1.2rem; }

.wa-step {
  background: rgba(255,255,255,.8);
  border: 1px solid #bbf7d0;
  border-radius: 12px;
  padding: 1rem 1.2rem;
  margin-bottom: .8rem;
}
.wa-step-num {
  display: inline-flex; align-items: center; justify-content: center;
  width: 24px; height: 24px; border-radius: 50%;
  background: #16a34a; color: #fff !important;
  font-weight: 800; font-size: .68rem;
  margin-right: .5rem; flex-shrink: 0;
}
.wa-step-label { font-size: .82rem; font-weight: 700; color: var(--darker) !important; }
.wa-step-desc  { font-size: .74rem; color: #166534 !important; margin-top: .2rem; padding-left: 2rem; }

/* ═══ Upload zone ═════════════════════════════════════════════════════════ */
.upload-zone {
  background: #f9fafb;
  border: 2px dashed #d1d5db;
  border-radius: 20px;
  min-height: 260px;
  display: flex; flex-direction: column;
  align-items: center; justify-content: center;
  gap: .4rem; text-align: center; padding: 2rem;
}
.upload-zone:hover { border-color: var(--green); background: var(--light); }
.uz-icon  { font-size: 3.5rem; }
.uz-title { font-size: .92rem; font-weight: 600; color: var(--darker) !important; }
.uz-sub   { font-size: .74rem; color: var(--muted) !important; }

/* ═══ Pipeline ════════════════════════════════════════════════════════════ */
.pipeline { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.pipe-node {
  background: #fff; border: 1.5px solid #86efac;
  border-radius: 10px; padding: .55rem .9rem;
  text-align: center; min-width: 100px;
  transition: all .2s;
}
.pipe-node:hover { background: var(--light); border-color: var(--green); transform: scale(1.04); }
.pn-icon { font-size: 1.2rem; }
.pn-name { font-size: .72rem; font-weight: 700; color: var(--darker) !important; }
.pn-sub  { font-size: .6rem; color: var(--muted) !important; }
.pipe-arr { font-size: 1rem; color: #d1d5db !important; }

/* ═══ Disclaimer ══════════════════════════════════════════════════════════ */
.disclaimer {
  background: #fffbeb; border: 1px solid #fde047;
  border-left: 4px solid #ca8a04;
  border-radius: 10px; padding: .8rem 1.1rem;
  font-size: .78rem; color: #713f12 !important;
  margin-top: 1rem;
}

/* ═══ Guardrail card ══════════════════════════════════════════════════════ */
.gc {
  background: #fff; border: 1px solid var(--border);
  border-radius: 10px; padding: .75rem 1rem;
  margin-bottom: .35rem;
  display: flex; justify-content: space-between; align-items: center;
}
.gc-name { font-size: .85rem; font-weight: 600; color: var(--darker) !important; }
.gc-desc { font-size: .7rem; color: var(--muted) !important; margin-top: 1px; }

/* ═══ Sidebar status dots ═════════════════════════════════════════════════ */
.sdot {
  display: inline-block; width: 7px; height: 7px;
  border-radius: 50%; margin-right: 6px; flex-shrink: 0;
  vertical-align: middle;
}
.sd-g { background:#4ade80; box-shadow:0 0 6px rgba(74,222,128,.7); }
.sd-r { background:#f87171; box-shadow:0 0 6px rgba(248,113,113,.5); }
.sd-b { background:#60a5fa; box-shadow:0 0 6px rgba(96,165,250,.5); }

/* ═══ Typography ══════════════════════════════════════════════════════════ */
h1,h2,h3,h4 { color: var(--darker) !important; letter-spacing: -.2px; }
p,span,li   { color: #374151 !important; }
strong      { color: var(--darker) !important; }
label       { color: #374151 !important; }
.stMarkdown p { color: #374151 !important; }
[data-testid="stAlert"] p  { color: inherit !important; }
.stCaption p { color: var(--muted) !important; font-size: .72rem !important; }

/* ═══ Buttons ═════════════════════════════════════════════════════════════ */
[data-testid="stButton"] > button {
  border-radius: 10px !important; font-weight: 600 !important;
  font-size: .85rem !important; padding: .52rem 1.1rem !important;
  transition: all .17s !important;
}
[data-testid="stButton"] > button[kind="primary"] {
  background: var(--green) !important; color: #fff !important;
  border: none !important;
  box-shadow: 0 2px 10px rgba(22,163,74,.35) !important;
}
[data-testid="stButton"] > button[kind="primary"]:hover {
  background: var(--dark) !important;
  box-shadow: 0 4px 18px rgba(22,163,74,.5) !important;
  transform: translateY(-1px) !important;
}
[data-testid="stButton"] > button:not([kind="primary"]) {
  background: #fff !important; color: var(--dark) !important;
  border: 1.5px solid #d1fae5 !important;
}
[data-testid="stButton"] > button:not([kind="primary"]):hover {
  background: var(--light) !important; border-color: var(--green) !important;
  transform: translateY(-1px) !important;
}
[data-testid="stDownloadButton"] > button {
  background: var(--green) !important; color: #fff !important;
  border: none !important; border-radius: 10px !important;
  font-weight: 700 !important; width: 100% !important;
}
[data-testid="stFileUploader"] label { color: var(--darker) !important; font-weight: 600; }
[data-testid="stTextInput"] input,
[data-testid="stTextArea"] textarea {
  border-radius: 10px !important;
  border: 1.5px solid var(--border) !important;
}
[data-testid="stTextInput"] input:focus,
[data-testid="stTextArea"] textarea:focus {
  border-color: var(--green) !important;
  box-shadow: 0 0 0 3px rgba(22,163,74,.12) !important;
}
[data-testid="stSelectbox"] > div > div {
  border-radius: 10px !important; border: 1.5px solid var(--border) !important;
}
[data-testid="stTabs"] [role="tab"][aria-selected="true"] {
  color: var(--green) !important; border-bottom-color: var(--green) !important;
}

/* ═══ Mobile ══════════════════════════════════════════════════════════════ */
@media (max-width: 640px) {
  .block-container { padding: 0 .8rem 2rem !important; }
  .hero { padding: 1.8rem 1.4rem; }
  .hero h1 { font-size: 2rem !important; }
  .pipe-arr { display: none; }
}
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
#  Session state
# ══════════════════════════════════════════════════════════════════════════════
def _init():
    defaults = {
        "session_id":       str(uuid.uuid4()),
        "page":             "🏠 Home",
        "last_path_report": None,
        "last_ext_report":  None,
        "last_combined":    None,
        "last_img_bytes":   None,
        "last_img_name":    None,
        # API keys — NEVER pre-filled in the UI; always loaded from .env at runtime
        "gemini_key_ui":    "",
        "gemini_model_ui":  GEMINI_MODEL_ID,
        "groq_key_ui":      "",
        "groq_model_ui":    GROQ_MODEL_ID,
        "wx_key_ui":        "",
        "wx_proj_ui":       "",
        "wx_url_ui":        WATSONX_URL,
        "wx_model_ui":      WATSONX_MODEL_ID,
        # WhatsApp
        "wa_phone":         DEFAULT_WA_PHONE or "",
        "wa_web_opened":    False,
        "twilio_sid":       "",
        "twilio_token":     "",
        "twilio_from":      TWILIO_FROM_NUMBER or "whatsapp:+14155238886",
        # WhatsApp Business Cloud API (Meta)
        "wa_access_token":  "",
        "wa_phone_num_id":  "",
        # WhatsApp Agent
        "last_wa_delivery": None,   # Dict from WhatsAppReportAgent.run()
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

    # Sync only non-secret settings (model IDs, URLs, phone numbers) from .env
    if not st.session_state.get("gemini_model_ui") and GEMINI_MODEL_ID:
        st.session_state["gemini_model_ui"] = GEMINI_MODEL_ID
    if not st.session_state.get("groq_model_ui") and GROQ_MODEL_ID:
        st.session_state["groq_model_ui"] = GROQ_MODEL_ID
    if not st.session_state.get("wx_url_ui") and WATSONX_URL:
        st.session_state["wx_url_ui"] = WATSONX_URL
    if not st.session_state.get("wx_model_ui") and WATSONX_MODEL_ID:
        st.session_state["wx_model_ui"] = WATSONX_MODEL_ID
    if not st.session_state.get("wa_phone") and DEFAULT_WA_PHONE:
        st.session_state["wa_phone"] = DEFAULT_WA_PHONE
    if not st.session_state.get("twilio_from") and TWILIO_FROM_NUMBER:
        st.session_state["twilio_from"] = TWILIO_FROM_NUMBER

_init()


# ══════════════════════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════════════════════
def _C():
    # API keys always come from .env (never from UI session state)
    # Model IDs / URLs may be overridden via the Settings UI
    return dict(
        gemini_key   = GEMINI_API_KEY,
        gemini_model = st.session_state.gemini_model_ui or GEMINI_MODEL_ID,
        groq_key     = GROQ_API_KEY,
        groq_model   = st.session_state.groq_model_ui   or GROQ_MODEL_ID,
        wx_key       = WATSONX_API_KEY,
        wx_proj      = WATSONX_PROJECT_ID,
        wx_url       = st.session_state.wx_url_ui       or WATSONX_URL,
        wx_model     = st.session_state.wx_model_ui     or WATSONX_MODEL_ID,
    )

def _badge(c: str) -> str:
    cls = {"High":"b-high","Medium":"b-medium","Low":"b-low"}.get(c,"b-unclear")
    return f"<span class='badge {cls}'>{c}</span>"

def _lottie(anim, key, h=180, q="medium"):
    if LOTTIE_OK and anim:
        st_lottie(anim, height=h, key=key, loop=True, quality=q)


# ══════════════════════════════════════════════════════════════════════════════
#  Sidebar
# ══════════════════════════════════════════════════════════════════════════════
def _sidebar():
    C = _C()
    with st.sidebar:
        st.markdown("""
        <div style='text-align:center;padding:1.6rem 0 .6rem'>
            <div style='font-size:3rem;line-height:1'>🌿</div>
            <div style='font-size:1.15rem;font-weight:900;color:#4ade80;margin-top:8px;
                        letter-spacing:-.3px'>Agri Doctor</div>
            <div style='font-size:.66rem;color:#34d399;font-weight:500;margin-top:3px'>
                AI Crop Health · v%s
            </div>
        </div>""" % APP_VERSION, unsafe_allow_html=True)

        _lottie(LOTTIE_CORN, "sb_corn", h=90, q="low")
        st.divider()

        # Status pills
        def sdot(cls, lbl, val):
            st.markdown(
                f"<div style='display:flex;align-items:center;padding:.25rem 0;'>"
                f"<span class='sdot {cls}'></span>"
                f"<span style='font-size:.77rem;color:#a7f3d0!important;'>"
                f"<b style='color:#d1fae5!important'>{lbl}</b> {val}</span></div>",
                unsafe_allow_html=True)

        gem_ok = bool(GEMINI_API_KEY)
        ibm_ok = bool(WATSONX_API_KEY and WATSONX_PROJECT_ID)
        sdot("sd-g" if gem_ok else "sd-r", "Gemini",
             f"{C['gemini_model']}" if gem_ok else "→ .env")
        sdot("sd-g" if ibm_ok else "sd-r", "IBM",
             "Connected" if ibm_ok else "Not configured")
        _wa_last = st.session_state.get("last_wa_delivery")
        _wa_cls  = "sd-g" if (_wa_last and _wa_last.get("status") in ("ready","sent","delivered")) else                    "sd-r" if (_wa_last and _wa_last.get("status") == "failed") else "sd-b"
        _wa_lbl  = ("📱 Agent ready" if (_wa_last and _wa_last.get("status") in ("ready","sent")) else
                    "Twilio ✓" if (st.session_state.twilio_sid and st.session_state.twilio_token)
                    else "Web ready")
        sdot(_wa_cls, "WhatsApp", _wa_lbl)
        st.divider()

        pages = ["🏠 Home","🔬 Diagnose Crop","🤖 Agent Workflow",
                 "📱 WhatsApp Agent","📋 History","📊 Performance",
                 "🛡️ Guardrails","⚙️ Settings"]
        sel = st.radio("", pages, key="nav", label_visibility="collapsed")
        st.session_state.page = sel

_sidebar()


# ══════════════════════════════════════════════════════════════════════════════
#  WHATSAPP SHARE SECTION  (shown after every diagnosis)
# ══════════════════════════════════════════════════════════════════════════════
def _wa_section(report_or_p, ext: Optional[Dict] = None, full_report: str = "", key_suffix: str = "diag"):
    """
    WhatsApp sharing widget shown after every diagnosis.

    key_suffix must be unique per call site to avoid Streamlit DuplicateWidgetID
    errors when this function is rendered on multiple pages simultaneously.
    """
    # ── Build the WhatsApp message text ──────────────────────────────────────
    if isinstance(report_or_p, dict):
        wa_text = _build_whatsapp_summary(report_or_p, ext)
    elif isinstance(report_or_p, str):
        if "SECTION 1" in report_or_p and st.session_state.get("last_path_report"):
            wa_text = _build_whatsapp_summary(
                st.session_state.last_path_report or {},
                st.session_state.last_ext_report or {}
            )
        else:
            wa_text = report_or_p
    else:
        wa_text = str(report_or_p)

    st.markdown("""
    <div class='wa-section'>
        <div class='wa-title'>📱 Share Report via WhatsApp</div>
        <div class='wa-sub'>
            Send this advisory directly to any farmer's WhatsApp.
            WhatsApp will open with the message pre-filled — the farmer must tap <strong>Send</strong>.
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Phone number input ────────────────────────────────────────────────────
    st.markdown("""
    <div class='wa-step'>
        <div style='display:flex;align-items:center;'>
            <span class='wa-step-num'>1</span>
            <span class='wa-step-label'>Enter farmer's WhatsApp number</span>
        </div>
        <div class='wa-step-desc'>
            10-digit Indian number (e.g. <b>9876543210</b>) or with country code
            (e.g. <b>+919876543210</b>). Spaces, dashes and brackets are ignored.
        </div>
    </div>
    """, unsafe_allow_html=True)

    phone_key  = f"wa_share_phone_{key_suffix}"
    msg_key    = f"wa_custom_text_{key_suffix}"
    twilio_key = f"wa_tsid_{key_suffix}"
    twilio_tok = f"wa_ttok_{key_suffix}"
    twilio_frm = f"wa_tfrm_{key_suffix}"

    ph_col, btn_col = st.columns([3, 2])
    with ph_col:
        phone = st.text_input(
            "📞 Farmer's WhatsApp Number",
            value=st.session_state.wa_phone or DEFAULT_WA_PHONE or "",
            placeholder="e.g. 9876543210 or +919876543210",
            label_visibility="collapsed",
            key=phone_key,
        )
        if phone:
            st.session_state.wa_phone = phone

    target_phone = phone.strip() if phone.strip() else (st.session_state.wa_phone or DEFAULT_WA_PHONE or "")

    # Validate phone number and generate URLs before rendering buttons
    urls_ok, clean_ph, urls = get_whatsapp_urls(target_phone, wa_text)

    with btn_col:
        if urls_ok:
            # Use the official wa.me click-to-chat URL — works on both desktop
            # (redirects to WhatsApp Web) and mobile (opens WhatsApp app).
            st.link_button(
                "📲 Open WhatsApp & Send",
                url=urls["wa_me"],
                type="primary",
                use_container_width=True,
                help=(
                    "Opens WhatsApp with the diagnosis report pre-filled. "
                    "Click Send in WhatsApp to deliver the message."
                ),
            )
        else:
            st.button(
                "📲 Open WhatsApp & Send",
                type="primary",
                use_container_width=True,
                key=f"send_wa_disabled_{key_suffix}",
                disabled=True,
            )
            if target_phone:
                st.caption(f"⚠️ {clean_ph}")
            else:
                st.caption("⬆️ Enter a phone number above.")

    # ── Validation feedback ───────────────────────────────────────────────────
    if urls_ok:
        st.markdown(f"""
        <div style='background:#f0fdf4;border:1.5px solid #86efac;border-radius:12px;
                    padding:0.9rem 1.2rem;margin:0.8rem 0;'>
            <div style='font-size:0.9rem;font-weight:700;color:#166534;margin-bottom:0.5rem;'>
                ✅ Ready to send to {clean_ph}
            </div>
            <div style='font-size:0.8rem;color:#15803d;margin-bottom:0.75rem;'>
                WhatsApp will open with the report pre-filled.
                The farmer must tap <strong>Send</strong> to deliver it.
            </div>
            <div style='display:flex;gap:0.6rem;flex-wrap:wrap;'>
                <a href='{urls["wa_me"]}' target='_blank' style='
                    display:inline-block;background:#25D366;color:#ffffff;font-weight:700;
                    padding:0.5rem 1.2rem;border-radius:8px;text-decoration:none;font-size:0.85rem;
                    box-shadow:0 2px 6px rgba(37,211,102,.3);'>
                    🚀 wa.me (Recommended)
                </a>
                <a href='{urls["web_url"]}' target='_blank' style='
                    display:inline-block;background:#059669;color:#ffffff;font-weight:600;
                    padding:0.5rem 1rem;border-radius:8px;text-decoration:none;font-size:0.85rem;'>
                    🌐 WhatsApp Web
                </a>
                <a href='{urls["api_url"]}' target='_blank' style='
                    display:inline-block;background:#047857;color:#ffffff;font-weight:600;
                    padding:0.5rem 1rem;border-radius:8px;text-decoration:none;font-size:0.85rem;'>
                    📱 WhatsApp App
                </a>
            </div>
        </div>
        """, unsafe_allow_html=True)

    # ── Preview / edit message ────────────────────────────────────────────────
    st.markdown("""
    <div class='wa-step' style='margin-top:.6rem'>
        <div style='display:flex;align-items:center;'>
            <span class='wa-step-num'>2</span>
            <span class='wa-step-label'>Preview or edit the advisory message</span>
        </div>
        <div class='wa-step-desc'>
            The full diagnosis report is included. You can edit it before sending.
        </div>
    </div>
    """, unsafe_allow_html=True)

    with st.expander("📝 View / Edit WhatsApp Message", expanded=False):
        custom_msg = st.text_area(
            "Message Text (edit before sending)",
            value=wa_text,
            height=200,
            key=msg_key,
        )
        # If the user edited the message, regenerate URLs with the new text
        edited = custom_msg.strip() if (custom_msg and custom_msg.strip()) else wa_text
        if edited != wa_text:
            urls_ok2, clean_ph2, urls2 = get_whatsapp_urls(target_phone, edited)
            if urls_ok2:
                st.link_button(
                    "📲 Send Edited Message via WhatsApp",
                    url=urls2["wa_me"],
                    type="primary",
                    use_container_width=True,
                )

        # Copy button — shows the full text in a selectable area
        st.markdown("**📋 Copy Report Text:**")
        st.text_area(
            "Select all and copy (Ctrl+A / Cmd+A)",
            value=wa_text,
            height=120,
            key=f"wa_copy_{key_suffix}",
            label_visibility="collapsed",
            disabled=False,
        )
        st.caption("Select all text above and copy it to share anywhere.")

    # Advanced: Twilio option (collapsed)
    with st.expander("🔧 Advanced: Send silently via Twilio API"):
        tc1, tc2, tc3 = st.columns(3)
        with tc1:
            t_sid = st.text_input("Twilio SID",
                value=st.session_state.twilio_sid, type="password", key=twilio_key)
        with tc2:
            t_tok = st.text_input("Auth Token",
                value=st.session_state.twilio_token, type="password", key=twilio_tok)
        with tc3:
            t_frm = st.text_input("From",
                value=st.session_state.twilio_from, key=twilio_frm)
        if st.button("📲 Send via Twilio API", key=f"send_twilio_btn_{key_suffix}"):
            if not target_phone.strip():
                st.error("❌ Please enter a phone number.")
            else:
                st.session_state.twilio_sid   = t_sid
                st.session_state.twilio_token = t_tok
                st.session_state.twilio_from  = t_frm
                with st.spinner("Sending via Twilio API…"):
                    ok, msg = send_whatsapp_report(
                        phone_number=target_phone,
                        report_text=wa_text,
                        method="twilio",
                        twilio_sid=t_sid,
                        twilio_token=t_tok,
                        twilio_from=t_frm,
                    )
                (st.success if ok else st.error)(msg)


# ══════════════════════════════════════════════════════════════════════════════
#  HOME
# ══════════════════════════════════════════════════════════════════════════════
def page_home():
    C = _C()

    # ── Hero ─────────────────────────────────────────────────────────────────
    hcol, lcol = st.columns([3, 2], gap="medium")
    with hcol:
        st.markdown("""
        <div class='hero'>
            <div class='hero-tag'>✦ AI-Powered Agriculture</div>
            <h1>Diagnose crops<br>with <em>AI precision</em></h1>
            <p>Upload a photo → two AI agents identify the disease and
            generate a complete treatment plan → share to WhatsApp instantly.</p>
            <div class='hero-chips'>
                <span class='hero-chip'>🔬 Google Gemini Vision</span>
                <span class='hero-chip'>🌿 IBM Granite LLM</span>
                <span class='hero-chip'>🛡️ Safety Guardrails</span>
                <span class='hero-chip'>📱 WhatsApp Share</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

    with lcol:
        st.markdown(
            "<div style='display:flex;align-items:center;justify-content:center;"
            "min-height:280px;background:transparent'>",
            unsafe_allow_html=True)
        _lottie(LOTTIE_GIRL, "hero_girl", h=290, q="high")
        st.markdown("</div>", unsafe_allow_html=True)

    if not GEMINI_API_KEY:
        st.warning(
            "🔑 **Gemini key not configured.** Add `GEMINI_API_KEY` to your `.env` file and restart the app.",
            icon="⚠️")

    # ── Stats ─────────────────────────────────────────────────────────────────
    stats = get_diagnosis_stats()
    st.markdown("<div class='sec-head'>📊 Dashboard</div>", unsafe_allow_html=True)
    c1,c2,c3,c4 = st.columns(4, gap="small")
    for col, icon, val, lbl, bar in [
        (c1,"🔬", stats["total_diagnoses"],            "Total Diagnoses",   "bar-green"),
        (c2,"✅", stats["healthy_crops"],              "Healthy Crops",     "bar-green"),
        (c3,"🦠", stats["detected_diseases"],          "Diseases Found",    "bar-amber"),
        (c4,"⚡", f"{stats['avg_processing_time']:.1f}","Avg Speed (s)",     "bar-blue"),
    ]:
        with col:
            st.markdown(
                f"<div class='metric-card'>"
                f"<div class='mc-icon'>{icon}</div>"
                f"<div class='mc-val'>{val}</div>"
                f"<div class='mc-lbl'>{lbl}</div>"
                f"<div class='mc-bar {bar}'></div>"
                f"</div>", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Quick actions + How it works ──────────────────────────────────────────
    act, how = st.columns([1, 2], gap="large")
    with act:
        st.markdown("<div class='sec-head'>⚡ Quick Actions</div>", unsafe_allow_html=True)
        if st.button("🔬  Diagnose a Crop", use_container_width=True, type="primary"):
            st.session_state.page = "🔬 Diagnose Crop"; st.rerun()
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("📋  View History", use_container_width=True):
            st.session_state.page = "📋 History"; st.rerun()
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("⚙️  Settings", use_container_width=True):
            st.session_state.page = "⚙️ Settings"; st.rerun()

    with how:
        st.markdown("<div class='sec-head'>📖 How It Works</div>", unsafe_allow_html=True)
        sc = st.columns(4, gap="small")
        steps = [
            ("📸", "Upload", "Clear photo of affected leaves or stems"),
            ("🔬", "Analyse", "Gemini Vision detects disease & causes"),
            ("🌿", "Advise", "IBM Granite writes the treatment plan"),
            ("📱", "Share", "Send to WhatsApp with one tap"),
        ]
        for i, (col, (icon, title, desc)) in enumerate(zip(sc, steps)):
            with col:
                st.markdown(
                    f"<div class='feat-step'>"
                    f"<div class='feat-num'>{i+1}</div>"
                    f"<span class='feat-icon'>{icon}</span>"
                    f"<div class='feat-title'>{title}</div>"
                    f"<div class='feat-desc'>{desc}</div>"
                    f"</div>", unsafe_allow_html=True)

    # ── Recent diagnoses ──────────────────────────────────────────────────────
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("<div class='sec-head'>🕒 Recent Diagnoses</div>", unsafe_allow_html=True)
    recent = get_recent_diagnoses(limit=6)
    if recent:
        for d in recent:
            conf = d.get("confidence_level","—")
            bcls = {"High":"b-high","Medium":"b-medium","Low":"b-low"}.get(conf,"b-unclear")
            st.markdown(
                f"<div class='hrow'>"
                f"<div>"
                f"<div class='hrow-title'>🌱 {d.get('suspected_disease','Unknown')}</div>"
                f"<div class='hrow-meta'>🕒 {d.get('created_at','')[:19]} · "
                f"📁 {d.get('image_filename','—')}</div></div>"
                f"<span class='badge {bcls}'>{conf}</span>"
                f"</div>", unsafe_allow_html=True)
    else:
        st.markdown(
            "<div class='card' style='text-align:center;padding:3rem'>"
            "<div style='font-size:3.5rem'>🌱</div>"
            "<p style='font-weight:700;color:#14532d!important;margin:.6rem 0 .2rem'>No diagnoses yet</p>"
            "<p style='color:#6b7280!important;font-size:.82rem'>Upload a crop photo to run your first AI diagnosis.</p>"
            "</div>", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
#  DIAGNOSE CROP
# ══════════════════════════════════════════════════════════════════════════════
def page_diagnose():
    st.markdown("""
    <div style='background:var(--dark);border-radius:16px;padding:1.4rem 1.8rem;
                margin-bottom:1.6rem;box-shadow:0 4px 20px rgba(5,46,22,.25)'>
        <h2 style='color:#fff!important;margin:0 0 .2rem;font-size:1.4rem'>🔬 Diagnose Your Crop</h2>
        <p style='color:rgba(255,255,255,.65)!important;margin:0;font-size:.85rem'>
            Upload a clear photo — two AI agents will analyse it and generate a full advisory report.
        </p>
    </div>
    """, unsafe_allow_html=True)

    left, right = st.columns([1, 1], gap="large")
    with left:
        uploaded = st.file_uploader("📸 Crop Image (JPG / PNG)",
            type=["jpg","jpeg","png"], key="crop_uploader",
            help="Best: clear, well-lit close-up of affected leaf or stem")
        notes = st.text_area("📝 Farmer's Notes (optional)",
            placeholder="e.g. Leaves yellowing for 5 days, sandy soil, 32°C…",
            max_chars=500, key="fn")
        ca, cb = st.columns(2)
        with ca: crop_type = st.text_input("🌱 Crop Type", placeholder="e.g. Tomato", key="ct")
        with cb: location  = st.text_input("📍 Location", placeholder="e.g. Karnataka", key="fl")

        # ── Farmer WhatsApp number ─────────────────────────────────────────
        st.markdown(
            "<div style='background:#f0fdf4;border:1.5px solid #86efac;border-radius:12px;"
            "padding:0.75rem 1rem;margin:0.5rem 0 0.75rem;'>"
            "<div style='font-size:0.88rem;font-weight:700;color:#166534;margin-bottom:0.3rem;'>"
            "📱 Send Report to WhatsApp (auto)</div>"
            "<div style='font-size:0.78rem;color:#15803d;'>"
            "Enter the farmer's number — the diagnosis report will open in WhatsApp automatically.</div>"
            "</div>",
            unsafe_allow_html=True,
        )
        wa_phone_input = st.text_input(
            "Farmer's WhatsApp Number",
            value=st.session_state.wa_phone or DEFAULT_WA_PHONE or "",
            placeholder="e.g. 9876543210  or  +919876543210",
            label_visibility="collapsed",
            key="diag_wa_phone",
            help="10-digit Indian number or with +91 country code. Leave blank to skip auto-send.",
        )
        if wa_phone_input.strip():
            st.session_state.wa_phone = wa_phone_input.strip()

        run_btn = st.button("🚀 Run AI Diagnosis", type="primary",
            use_container_width=True, disabled=not uploaded)
        if not uploaded:
            st.caption("⬆️ Upload an image first")

    with right:
        if uploaded:
            img_bytes = uploaded.read()
            st.session_state.last_img_bytes = img_bytes
            st.session_state.last_img_name  = uploaded.name
            img = Image.open(io.BytesIO(img_bytes))
            st.image(img, caption=f"📷 {uploaded.name}", use_container_width=True)
            st.caption(f"📐 {img.size[0]}×{img.size[1]} · 📦 {len(img_bytes)/1024:.1f} KB")
        else:
            st.markdown(
                "<div class='upload-zone'>"
                "<div class='uz-icon'>🌾</div>"
                "<div class='uz-title'>Your crop image will appear here</div>"
                "<div class='uz-sub'>JPG or PNG · Max 10 MB</div>"
                "</div>", unsafe_allow_html=True)

    if run_btn and uploaded:
        _run_workflow(
            img_bytes=st.session_state.last_img_bytes,
            img_name=st.session_state.last_img_name,
            img_mime=uploaded.type or "image/jpeg",
            notes=notes, crop_type=crop_type, location=location,
        )


# ══════════════════════════════════════════════════════════════════════════════
#  WORKFLOW ENGINE
# ══════════════════════════════════════════════════════════════════════════════
def _run_workflow(img_bytes, img_name, img_mime, notes, crop_type, location):
    C   = _C()
    sid = st.session_state.session_id
    st.markdown("---")
    st.markdown("### 🤖 AI Analysis in Progress")
    t0 = time.time()

    # ── Agent 1 ──────────────────────────────────────────────────────────────
    st.markdown(
        "<div class='agent-box'>"
        "<div class='agent-num'>1</div>"
        "<div class='agent-info'>"
        "<strong>Pathologist Agent — Google Gemini Vision</strong><br>"
        "<small>Identifying disease, symptoms and root causes from your crop image</small>"
        "</div></div>", unsafe_allow_html=True)
    p_ph  = st.empty()
    p_bar = st.progress(0, text="Preparing image…")
    p_ph.markdown("<span class='st-run blink'>⏳ Sending to Gemini Vision…</span>", unsafe_allow_html=True)
    p_bar.progress(30, text="Analysing…")

    t1 = time.time()
    try:
        p_ok, p_rep, _ = PathologistAgent(
            gemini_api_key=C["gemini_key"] or None,
            gemini_model=C["gemini_model"] or None,
            groq_api_key=C["groq_key"] or None,
            groq_model=C["groq_model"] or None,
        ).run(image_bytes=img_bytes, image_filename=img_name,
              image_mime_type=img_mime, farmer_notes=notes, session_id=sid)
    except Exception as e:
        p_ok, p_rep = False, {"error": str(e)}
    pt = round(time.time()-t1, 2)
    p_bar.progress(100, text=f"Pathologist: {pt}s")

    if p_ok:
        p_ph.markdown(
            f"<span class='st-ok'>✅ Pathologist complete — {pt}s · "
            f"Provider: {p_rep.get('vision_provider','?')}</span>",
            unsafe_allow_html=True)
        st.session_state.last_path_report = p_rep
        _show_path_report(p_rep)
    else:
        err = p_rep.get("error","Unknown error")
        p_ph.markdown("<span class='st-err'>❌ Pathologist failed</span>", unsafe_allow_html=True)
        st.error(f"**Pathologist failed:** {err}")
        if not C["gemini_key"]:
            st.info("💡 Add Gemini API key in ⚙️ Settings → Gemini Vision.\n"
                    "Free key: https://aistudio.google.com/app/apikey")
        return

    # ── Agent 2 ──────────────────────────────────────────────────────────────
    st.markdown(
        "<div class='agent-box'>"
        "<div class='agent-num'>2</div>"
        "<div class='agent-info'>"
        "<strong>Extension Officer Agent — IBM Granite</strong><br>"
        "<small>Generating personalised treatment plan and farm advisory</small>"
        "</div></div>", unsafe_allow_html=True)
    e_ph  = st.empty()
    e_bar = st.progress(0, text="Preparing advisory…")
    e_ph.markdown("<span class='st-run blink'>⏳ IBM Granite writing advisory…</span>", unsafe_allow_html=True)
    e_bar.progress(30, text="IBM Granite processing…")

    t2 = time.time()
    try:
        e_ok, e_rep, _ = ExtensionOfficerAgent(
            watsonx_api_key=C["wx_key"] or None,
            watsonx_project_id=C["wx_proj"] or None,
            watsonx_url=C["wx_url"] or None,
            watsonx_model=C["wx_model"] or None,
        ).run(pathologist_report=p_rep, crop_type=crop_type, location=location, session_id=sid)
    except Exception as ex:
        e_ok, e_rep = False, {"error": str(ex)}
    et = round(time.time()-t2, 2)
    e_bar.progress(100, text=f"Extension Officer: {et}s")

    if e_ok:
        e_ph.markdown(f"<span class='st-ok'>✅ Extension Officer complete — {et}s</span>",
                      unsafe_allow_html=True)
        st.session_state.last_ext_report = e_rep
        _show_ext_report(e_rep)
    else:
        e_ph.markdown("<span class='st-err'>❌ Extension Officer failed</span>", unsafe_allow_html=True)
        st.error(f"**Extension Officer failed:** {e_rep.get('error','')}")
        if not C["wx_key"] or not C["wx_proj"]:
            st.info("💡 Add IBM watsonx credentials in ⚙️ Settings → IBM watsonx.ai")

    # ── Summary ───────────────────────────────────────────────────────────────
    total = round(time.time()-t0, 2)
    st.markdown("---")
    st.markdown(
        f"<div style='background:linear-gradient(135deg,#052e16,#14532d);border-radius:16px;"
        f"padding:1.2rem 1.6rem;margin-bottom:1rem;box-shadow:0 4px 16px rgba(5,46,22,.3);'>"
        f"<h3 style='color:#fff!important;margin:0 0 .2rem'>✅ Analysis Complete</h3>"
        f"<p style='color:rgba(255,255,255,.65)!important;margin:0;font-size:.84rem'>"
        f"Total: <strong style='color:#4ade80!important'>{total}s</strong> &nbsp;·&nbsp; "
        f"Pathologist: {pt}s &nbsp;·&nbsp; Extension Officer: {et}s</p>"
        f"</div>", unsafe_allow_html=True)

    combined = _build_report(p_rep, e_rep if e_ok else {})
    st.session_state.last_combined = combined

    try:
        save_diagnosis(
            session_id=sid, image_filename=img_name,
            image_size_kb=len(img_bytes)/1024,
            pathologist_report=p_rep,
            extension_report=e_rep if e_ok else {},
            combined_report=combined,
            suspected_disease=p_rep.get("suspected_disease","Unknown"),
            confidence_level=p_rep.get("confidence_level","Unknown"),
            processing_time_seconds=total,
            status="completed" if e_ok else "partial",
        )
    except Exception as db_e:
        logger.warning(f"DB save error: {db_e}")

    # ── Auto-trigger WhatsApp Agent ───────────────────────────────────────────
    _wa_phone = st.session_state.wa_phone
    if _wa_phone and _wa_phone.strip():
        st.markdown("---")
        st.markdown(
            "<div style='background:linear-gradient(135deg,#064e3b,#065f46);border-radius:14px;"
            "padding:1rem 1.4rem;margin-bottom:0.8rem;display:flex;align-items:center;gap:0.75rem;'>"
            "<div style='font-size:1.8rem;'>📱</div>"
            "<div>"
            "<div style='color:#fff;font-weight:700;font-size:1rem;'>Sending Report via WhatsApp</div>"
            "<div style='color:rgba(255,255,255,.65);font-size:.8rem;margin-top:2px;'>"
            f"Preparing advisory for {_wa_phone}…</div>"
            "</div></div>",
            unsafe_allow_html=True,
        )
        _wa_status_box = st.empty()
        try:
            with st.spinner("🤖 WhatsApp Agent processing…"):
                _wa_agent  = WhatsAppReportAgent()
                _wa_result = _wa_agent.run(
                    phone=_wa_phone,
                    report_text=combined,
                    report_title=p_rep.get("suspected_disease", "Crop Advisory") + " Advisory",
                    session_id=sid,
                    recipient_name="",
                    method="auto",
                    wa_access_token=st.session_state.get("wa_access_token", ""),
                    wa_phone_number_id=st.session_state.get("wa_phone_num_id", ""),
                    twilio_sid=st.session_state.get("twilio_sid", ""),
                    twilio_token=st.session_state.get("twilio_token", ""),
                    twilio_from=st.session_state.get("twilio_from", ""),
                )
            st.session_state.last_wa_delivery = _wa_result

            if _wa_result.get("sent"):
                # Automatic send succeeded (Selenium / Meta API / Twilio)
                _wa_status_box.success(
                    f"✅ **WhatsApp report sent automatically** to "
                    f"`{_wa_result.get('phone_masked', _wa_phone)}` "
                    f"via **{_wa_result.get('method_used', '').upper()}**. "
                    f"The farmer will receive the full diagnosis advisory."
                )

            elif _wa_result.get("prepared") and _wa_result.get("wa_url"):
                # URL prepared — user must tap Send inside WhatsApp
                _wa_url   = _wa_result["wa_url"]
                _wa_clean = _wa_result.get("phone_masked", _wa_phone)
                _wa_status_box.empty()
                st.markdown(
                    f"<div style='background:#f0fdf4;border:2px solid #25D366;border-radius:14px;"
                    f"padding:1.1rem 1.4rem;margin:0.5rem 0 1rem;'>"
                    f"<div style='font-size:1rem;font-weight:800;color:#166534;margin-bottom:0.4rem;'>"
                    f"✅ Report Ready — Open WhatsApp to Send</div>"
                    f"<div style='font-size:0.82rem;color:#15803d;margin-bottom:0.85rem;'>"
                    f"The full diagnosis report is pre-filled for <strong>{_wa_clean}</strong>. "
                    f"Tap the button below — WhatsApp opens with the message ready. "
                    f"Tap <strong>Send</strong> in WhatsApp to deliver it to the farmer.</div>"
                    f"<a href='{_wa_url}' target='_blank' style='"
                    f"display:inline-block;background:#25D366;color:#ffffff;font-weight:800;"
                    f"padding:0.65rem 2rem;border-radius:10px;text-decoration:none;font-size:1rem;"
                    f"box-shadow:0 3px 10px rgba(37,211,102,.4);letter-spacing:0.01em;'>"
                    f"📲 Open WhatsApp &amp; Send Report"
                    f"</a>"
                    f"<div style='font-size:0.72rem;color:#6b7280;margin-top:0.6rem;'>"
                    f"WhatsApp does not send automatically — you must tap Send inside the app.</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
                # Also render a Streamlit link_button so it works in all browser configurations
                from services.whatsapp_service import get_whatsapp_urls as _gwu
                _ok2, _, _urls2 = _gwu(_wa_phone, combined)
                if _ok2:
                    st.link_button(
                        "📲 Open WhatsApp & Send Report",
                        url=_urls2["wa_me"],
                        type="primary",
                        use_container_width=True,
                    )

            else:
                # Agent failed — still give a manual fallback button
                _err = _wa_result.get("error", "Unknown error")
                _wa_status_box.warning(
                    f"⚠️ Auto-send failed: {_err}. Use the WhatsApp sharing section below."
                )
        except Exception as _wa_e:
            logger.warning(f"WhatsApp Agent auto-trigger error: {_wa_e}")
            _wa_status_box.warning(
                f"⚠️ WhatsApp Agent error: {_wa_e}. Use the sharing section below."
            )

    # ── Download ──────────────────────────────────────────────────────────────
    dl, _ = st.columns([2,1])
    with dl:
        st.download_button(
            "⬇️ Download Full Advisory (TXT)", combined.encode(),
            f"agri_advisory_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
            "text/plain", use_container_width=True)

    # ── WhatsApp share — ALWAYS shown after diagnosis ─────────────────────────
    _wa_section(p_rep, e_rep if e_ok else {}, combined, key_suffix="run")

    st.markdown(
        "<div class='disclaimer'>⚠️ <strong>Disclaimer:</strong> AI-generated preliminary assessment — "
        "NOT a confirmed laboratory diagnosis. Always consult a qualified agricultural expert "
        "before applying any treatment.</div>", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
#  REPORT RENDERERS
# ══════════════════════════════════════════════════════════════════════════════
def _show_path_report(r: Dict):
    with st.expander("🔬 Pathologist Report", expanded=True):
        sev_col = {"Mild":"#16a34a","Moderate":"#d97706","Severe":"#dc2626","Unclear":"#6b7280"}.get(
            r.get("disease_severity","Unclear"), "#6b7280")
        st.markdown(
            f"<div class='card-green'>"
            f"<div style='font-size:1.05rem;font-weight:800;color:#14532d!important;margin-bottom:.5rem'>"
            f"🦠 {r.get('suspected_disease','Unknown')}</div>"
            f"<div style='display:flex;gap:1rem;flex-wrap:wrap;align-items:center'>"
            f"<span>Confidence: {_badge(r.get('confidence_level','Unclear'))}</span>"
            f"<span>Severity: <strong style='color:{sev_col}!important'>"
            f"{r.get('disease_severity','?')}</strong></span>"
            f"<span>Lab: <strong>{'⚠️ Required' if r.get('requires_lab_confirmation') else '✅ Not required'}</strong></span>"
            f"</div></div>", unsafe_allow_html=True)

        c1, c2 = st.columns(2, gap="medium")
        with c1:
            if r.get("symptoms_observed"):
                st.markdown("**🔴 Symptoms**")
                for s in r["symptoms_observed"]: st.markdown(f"- {s}")
            if r.get("affected_plant_parts"):
                st.markdown("**🌿 Affected Parts**")
                for p in r["affected_plant_parts"]: st.markdown(f"- {p}")
        with c2:
            if r.get("possible_causes"):
                st.markdown("**💡 Possible Causes**")
                for c in r["possible_causes"]: st.markdown(f"- {c}")
            if r.get("alternative_diagnoses"):
                st.markdown("**🔄 Alternatives**")
                for a in r["alternative_diagnoses"]: st.markdown(f"- {a}")

        if r.get("pathologist_notes"): st.info(f"📋 {r['pathologist_notes']}")
        if r.get("_confidence_warning"): st.warning(r["_confidence_warning"])
        st.caption(f"Vision: {r.get('vision_provider','?')} · Quality: {r.get('image_quality','?')} · {r.get('image_filename','?')}")


def _show_ext_report(r: Dict):
    with st.expander("🌿 Farm Advisory", expanded=True):
        if r.get("crop_condition_summary"):
            st.markdown(
                f"<div class='card-green'>"
                f"<strong>📋 Summary</strong><br>"
                f"<span style='font-size:.9rem'>{r['crop_condition_summary']}</span>"
                f"</div>", unsafe_allow_html=True)

        c1, c2 = st.columns(2, gap="medium")
        with c1:
            if r.get("immediate_actions"):
                st.markdown("**🚨 Immediate Actions**")
                for a in r["immediate_actions"]: st.markdown(f"- ✅ {a}")
            if r.get("crop_care_tips"):
                st.markdown("**🌱 Care Tips**")
                for t in r["crop_care_tips"]: st.markdown(f"- 🌿 {t}")
        with c2:
            if r.get("preventive_measures"):
                st.markdown("**🛡️ Prevention**")
                for p in r["preventive_measures"]: st.markdown(f"- 🔒 {p}")
            if r.get("when_to_seek_expert_help"): st.warning(f"👨‍🔬 {r['when_to_seek_expert_help']}")

        if r.get("treatment_options"):
            st.markdown("**💊 Treatment Options**")
            for tr in r["treatment_options"]:
                with st.expander(f"{tr.get('type','?')} — {tr.get('name','?')}"):
                    if tr.get("instructions"):      st.markdown(f"📋 {tr['instructions']}")
                    if tr.get("ppe_required"):      st.markdown(f"🥽 **PPE:** {tr['ppe_required']}")
                    if tr.get("environmental_notes"): st.markdown(f"🌍 {tr['environmental_notes']}")

        rec  = r.get("estimated_recovery_time","")
        conf = r.get("advisory_confidence","")
        if rec or conf:
            parts = []
            if rec:  parts.append(f"⏱️ Recovery: <strong>{rec}</strong>")
            if conf: parts.append(f"Confidence: {_badge(conf)}")
            st.markdown(
                f"<div class='card' style='padding:.7rem 1rem;background:#f0fdf4;'>"
                f"{'&nbsp; · &nbsp;'.join(parts)}</div>", unsafe_allow_html=True)

        st.markdown(
            "<div class='disclaimer'>⚠️ AI advisory — verify with a qualified agricultural "
            "extension officer before acting.</div>", unsafe_allow_html=True)


def _build_whatsapp_summary(p: Dict, e: Optional[Dict] = None) -> str:
    """Generate a clean, compact WhatsApp message suitable for quick messaging."""
    if not p:
        return "🌿 *Agri Doctor Crop Health Advisory*\nNo diagnosis details available."

    disease = p.get("suspected_disease", "Crop Health Analysis")
    conf = p.get("confidence_level", "Medium")
    severity = p.get("disease_severity", "Moderate")

    lines = [
        "🌿 *AGRI DOCTOR — CROP HEALTH ADVISORY*",
        f"📅 {datetime.now().strftime('%d %b %Y, %I:%M %p')}",
        "",
        f"🌱 *Suspected Disease:* {disease}",
        f"📊 *Confidence:* {conf}  |  *Severity:* {severity}",
    ]

    symptoms = p.get("symptoms_observed", [])
    if symptoms and symptoms != ["None clearly observed"]:
        lines.append("\n🔬 *Key Symptoms:*")
        for s in symptoms[:3]:
            lines.append(f"• {s}")

    if e:
        summary = e.get("crop_condition_summary")
        if summary:
            lines.append(f"\n📋 *Summary:* {summary}")

        actions = e.get("immediate_actions", [])
        if actions:
            lines.append("\n🚨 *Immediate Actions:*")
            for a in actions[:3]:
                lines.append(f"• {a}")

        treatments = e.get("treatment_options", [])
        if treatments:
            lines.append("\n💊 *Recommended Treatment:*")
            for t in treatments[:2]:
                tname = t.get("name", "Treatment")
                ttype = t.get("type", "")
                tinstr = t.get("instructions", "")
                prefix = f"[{ttype}] " if ttype else ""
                lines.append(f"• {prefix}{tname}")
                if tinstr:
                    lines.append(f"   ↳ {tinstr[:100]}")

        recovery = e.get("estimated_recovery_time")
        if recovery and recovery != "?":
            lines.append(f"\n⏳ *Est. Recovery:* {recovery}")

    lines.append("\n⚠️ *Disclaimer:* AI advisory — consult a qualified agricultural expert.")
    return "\n".join(lines)


def _build_report(p: Dict, e: Dict) -> str:
    lines = [
        "="*68, "AGRI DOCTOR — AI CROP HEALTH ADVISORY REPORT",
        f"Generated : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "="*68, "",
        "DISCLAIMER: AI preliminary assessment — NOT a confirmed lab diagnosis.",
        "Always consult a qualified agricultural expert before treatment.", "",
        "="*68, "SECTION 1 — PATHOLOGIST REPORT (Google Gemini Vision)", "="*68, "",
        f"Suspected Disease : {p.get('suspected_disease','Unknown')}",
        f"Confidence Level  : {p.get('confidence_level','Unknown')}",
        f"Disease Severity  : {p.get('disease_severity','Unknown')}",
        f"Image Quality     : {p.get('image_quality','Unknown')}",
        f"Lab Confirmation  : {'Required' if p.get('requires_lab_confirmation') else 'Not required'}",
        f"Vision Provider   : {p.get('vision_provider','Unknown')}",
        "", "Symptoms:",
    ]
    for s in p.get("symptoms_observed",[]): lines.append(f"  • {s}")
    lines += ["","Causes:"]
    for c in p.get("possible_causes",[]): lines.append(f"  • {c}")
    lines += ["","Affected Parts:"]
    for pt in p.get("affected_plant_parts",[]): lines.append(f"  • {pt}")
    if p.get("pathologist_notes"): lines += ["", f"Notes: {p['pathologist_notes']}"]
    if e:
        lines += ["","="*68,"SECTION 2 — FARM ADVISORY (IBM Granite)","="*68,"",
                  f"Summary: {e.get('crop_condition_summary','')}","","Immediate Actions:"]
        for a in e.get("immediate_actions",[]): lines.append(f"  √ {a}")
        lines += ["","Prevention:"]
        for pm in e.get("preventive_measures",[]): lines.append(f"  √ {pm}")
        lines += ["","Treatments:"]
        for tr in e.get("treatment_options",[]):
            lines.append(f"  [{tr.get('type','?')}] {tr.get('name','?')}")
            if tr.get("instructions"): lines.append(f"    → {tr['instructions']}")
            if tr.get("ppe_required"):  lines.append(f"    PPE: {tr['ppe_required']}")
        lines += ["", f"Est. Recovery : {e.get('estimated_recovery_time','?')}",
                  f"Confidence    : {e.get('advisory_confidence','?')}"]
    lines += ["","="*68,"END OF REPORT — Agri Doctor","="*68]
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
#  AGENT WORKFLOW
# ══════════════════════════════════════════════════════════════════════════════
def page_workflow():
    st.markdown("""
    <div style='background:var(--dark);border-radius:16px;padding:1.4rem 1.8rem;
                margin-bottom:1.6rem;box-shadow:0 4px 20px rgba(5,46,22,.25)'>
        <h2 style='color:#fff!important;margin:0 0 .2rem'>🤖 Multi-Agent Workflow</h2>
        <p style='color:rgba(255,255,255,.65)!important;margin:0;font-size:.85rem'>
            Sequential AI pipeline: Image → Pathologist Agent → Extension Officer Agent → Report
        </p>
    </div>""", unsafe_allow_html=True)

    steps = [("📸","Upload","Farmer"),("🔬","Pathologist","Gemini Vision"),
             ("📋","Report","Handoff"),("🌿","Extension","IBM Granite"),("📱","Export","WhatsApp")]
    html = ""
    for i,(icon,name,sub) in enumerate(steps):
        html += (f"<div class='pipe-node'>"
                 f"<div class='pn-icon'>{icon}</div>"
                 f"<div class='pn-name'>{name}</div>"
                 f"<div class='pn-sub'>{sub}</div></div>")
        if i < len(steps)-1: html += "<div class='pipe-arr'>→</div>"
    st.markdown(f"<div class='card'><div class='pipeline'>{html}</div></div>", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    if st.session_state.last_path_report:
        st.markdown("### 📋 Last Results")
        _show_path_report(st.session_state.last_path_report)
        if st.session_state.last_ext_report:
            _show_ext_report(st.session_state.last_ext_report)
        if st.session_state.last_combined:
            st.download_button("⬇️ Download Advisory", st.session_state.last_combined.encode(),
                               "agri_advisory.txt","text/plain", use_container_width=True)
            _wa_section(st.session_state.last_path_report or {}, st.session_state.last_ext_report or {}, st.session_state.last_combined, key_suffix="wf")
    else:
        st.markdown(
            "<div class='card' style='text-align:center;padding:3rem'>"
            "<div style='font-size:3.5rem'>🤖</div>"
            "<p style='font-weight:700;color:#14532d!important;font-size:1rem;margin:.6rem 0 .2rem'>No results yet</p>"
            "<p style='color:#6b7280!important;font-size:.82rem'>Run a diagnosis from <strong>🔬 Diagnose Crop</strong>.</p>"
            "</div>", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
#  HISTORY
# ══════════════════════════════════════════════════════════════════════════════
def page_history():
    st.markdown("""
    <div style='background:var(--dark);border-radius:16px;padding:1.4rem 1.8rem;
                margin-bottom:1.6rem;box-shadow:0 4px 20px rgba(5,46,22,.25)'>
        <h2 style='color:#fff!important;margin:0 0 .2rem'>📋 Advisory History</h2>
        <p style='color:rgba(255,255,255,.65)!important;margin:0;font-size:.85rem'>
            All past diagnoses stored in your local SQLite database.
        </p>
    </div>""", unsafe_allow_html=True)

    limit = st.slider("Show last N records", 5, 100, 20, key="hist_lim")
    diags = get_recent_diagnoses(limit=limit)
    if not diags:
        st.markdown(
            "<div class='card' style='text-align:center;padding:3rem'>"
            "<div style='font-size:3.5rem'>📂</div>"
            "<p style='font-weight:700;color:#14532d!important'>No history yet</p>"
            "<p style='color:#6b7280!important;font-size:.82rem'>Run your first diagnosis to see records here.</p>"
            "</div>", unsafe_allow_html=True)
        return
    for d in diags:
        conf = d.get("confidence_level","?")
        with st.expander(f"🌱 {d.get('suspected_disease','Unknown')} — {d.get('created_at','')[:19]}"):
            r1,r2,r3 = st.columns(3)
            r1.markdown(f"**Disease:** {d.get('suspected_disease','—')}")
            r2.markdown(f"**Confidence:** {conf}")
            r3.markdown(f"**Status:** {d.get('status','—')}")
            r4,r5 = st.columns(2)
            r4.markdown(f"**File:** {d.get('image_filename','—')}")
            r5.markdown(f"**Processing:** {d.get('processing_time_seconds',0):.2f}s")
            if d.get("combined_report"):
                st.download_button("⬇️ Download Report", d["combined_report"].encode(),
                    f"advisory_{d['id']}.txt","text/plain", key=f"dl_{d['id']}")


# ══════════════════════════════════════════════════════════════════════════════
#  GUARDRAILS
# ══════════════════════════════════════════════════════════════════════════════
def page_guardrails():
    st.markdown("""
    <div style='background:var(--dark);border-radius:16px;padding:1.4rem 1.8rem;
                margin-bottom:1.6rem;box-shadow:0 4px 20px rgba(5,46,22,.25)'>
        <h2 style='color:#fff!important;margin:0 0 .2rem'>🛡️ Guardrails &amp; Security</h2>
        <p style='color:rgba(255,255,255,.65)!important;margin:0;font-size:.85rem'>
            All safety layers applied to inputs and outputs in the pipeline.
        </p>
    </div>""", unsafe_allow_html=True)

    t1,t2,t3 = st.tabs(["🔒 Input Guardrails","🔍 Output Guardrails","📋 Event Log"])

    def gc(name, desc):
        st.markdown(
            f"<div class='gc'><div>"
            f"<div class='gc-name'>✅ {name}</div>"
            f"<div class='gc-desc'>{desc}</div>"
            f"</div><span class='badge b-high'>ACTIVE</span></div>",
            unsafe_allow_html=True)

    with t1:
        for n,d in [
            ("Image Format Validation","Only JPG/PNG under 10 MB"),
            ("Image Integrity Check","PIL verify() — detects corrupted files"),
            ("Image Dimension Check","Min 50×50 px, max 8000×8000 px"),
            ("Prompt Injection Detection","Blocks injection phrases in text fields"),
            ("Toxicity Filtering","Removes harmful/abusive content"),
            ("PII Detection","Warns on phone/email/national ID"),
            ("Text Length Limit","Max 2000 chars per free-text field"),
            ("HTML / Control Char Strip","Removes tags and null bytes"),
        ]: gc(n,d)
    with t2:
        for n,d in [
            ("Pathologist Output Validation","Requires disease, symptoms, causes"),
            ("Extension Output Validation","Requires actions, preventive measures"),
            ("Hallucination Signal Detection","Blocks 'I cannot see the image'"),
            ("Overconfidence Detection","Flags '100% certain' or 'guaranteed cure'"),
            ("Unsafe Chemical Advice Filter","Blocks dangerous mixing instructions"),
            ("Output Toxicity Filter","Blocks harmful language"),
            ("Script / HTML Strip","Removes <script> tags from LLM output"),
            ("Mandatory Safety Disclaimer","Appended to every output"),
            ("Cross-Agent Verification","Extension Officer validates pathologist"),
        ]: gc(n,d)
    with t3:
        from database import get_guardrail_events
        import pandas as pd
        events = get_guardrail_events(days=30)
        if events:
            df = pd.DataFrame(events)[["created_at","event_type","agent_name","severity","details"]]
            df.columns = ["Time","Event","Agent","Severity","Details"]
            st.dataframe(df.head(30), use_container_width=True)
        else:
            st.success("✅ No guardrail events in the last 30 days. System clean.")


# ══════════════════════════════════════════════════════════════════════════════
#  SETTINGS
# ══════════════════════════════════════════════════════════════════════════════
def page_settings():
    def _save_all():
        # Only save non-secret values (model IDs, URLs) via the UI
        # API keys are managed exclusively via the .env file
        updates = {}
        if st.session_state.gemini_model_ui:
            updates["GEMINI_MODEL_ID"] = st.session_state.gemini_model_ui
        if st.session_state.groq_model_ui:
            updates["GROQ_MODEL_ID"] = st.session_state.groq_model_ui
        if st.session_state.wx_url_ui:
            updates["WATSONX_URL"] = st.session_state.wx_url_ui
        if st.session_state.wx_model_ui:
            updates["WATSONX_MODEL_ID"] = st.session_state.wx_model_ui
        if st.session_state.wa_phone:
            updates["DEFAULT_WA_PHONE"] = st.session_state.wa_phone
        if st.session_state.twilio_from:
            updates["TWILIO_FROM_NUMBER"] = st.session_state.twilio_from
        save_env_variables(updates)
        st.success("✅ Settings saved to `.env` — model IDs and URLs updated.")

    # ── Header Banner ────────────────────────────────────────────────────────
    col_hdr, col_btn = st.columns([3, 1])
    with col_hdr:
        st.markdown("""
        <div style='background:var(--dark);border-radius:16px;padding:1.3rem 1.6rem;
                    margin-bottom:1rem;box-shadow:0 4px 20px rgba(5,46,22,.25)'>
            <h2 style='color:#fff!important;margin:0 0 .2rem'>⚙️ Settings & API Configuration</h2>
            <p style='color:rgba(255,255,255,.75)!important;margin:0;font-size:.85rem'>
                Configure AI models and WhatsApp. Click <b>💾 Save to .env</b> so you never have to re-enter your keys.
            </p>
        </div>""", unsafe_allow_html=True)
    with col_btn:
        st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
        if st.button("💾 Save All to .env", type="primary", use_container_width=True, key="save_all_top"):
            _save_all()

    t1, t2, t3, t4 = st.tabs(["🟢 Gemini & Groq Vision", "🔵 IBM watsonx.ai", "🔧 Advanced Defaults", "📱 WhatsApp"])

    # ── TAB 1: Gemini & Groq ──────────────────────────────────────────────────
    with t1:
        st.markdown("#### 🌿 Google Gemini Vision (Primary Pathologist)")
        # API key status — loaded from .env, never shown
        gem_configured = bool(GEMINI_API_KEY)
        if gem_configured:
            st.success("🔑 **Gemini API Key:** Configured via `.env` (hidden for security)")
        else:
            st.error("🔑 **Gemini API Key:** Not set — add `GEMINI_API_KEY` to your `.env` file.")
        gm = st.text_input("Gemini Model ID",
                           value=st.session_state.gemini_model_ui or GEMINI_MODEL_ID,
                           help="Recommended: gemini-2.5-flash or gemini-2.0-flash", key="g_mdl")
        st.session_state.gemini_model_ui = gm

        b_t1, b_s1 = st.columns([1, 1])
        with b_t1:
            if st.button("🧪 Test Gemini Connection", key="t_gem", use_container_width=True):
                with st.spinner("Testing Gemini connection…"):
                    ok, msg = test_gemini_connection(
                        api_key=GEMINI_API_KEY,
                        model=st.session_state.gemini_model_ui or GEMINI_MODEL_ID)
                (st.success if ok else st.error)(f"{'✅' if ok else '❌'} {msg}")
        with b_s1:
            if st.button("💾 Save Gemini Model to .env", key="save_gem_btn", use_container_width=True):
                save_env_variables({"GEMINI_MODEL_ID": st.session_state.gemini_model_ui})
                st.success("✅ Gemini model ID saved to `.env`!")

        st.markdown("---")
        st.markdown("#### ⚡ Groq Vision (Automatic Fallback)")
        st.caption("Groq acts as the high-speed fallback if Gemini experiences rate-limits or network interruptions.")
        groq_configured = bool(GROQ_API_KEY)
        if groq_configured:
            st.success("🔑 **Groq API Key:** Configured via `.env` (hidden for security)")
        else:
            st.error("🔑 **Groq API Key:** Not set — add `GROQ_API_KEY` to your `.env` file.")
        gqm = st.text_input("Groq Model ID",
                            value=st.session_state.groq_model_ui or GROQ_MODEL_ID,
                            help="Recommended: qwen/qwen3.8-27b", key="gq_mdl")
        st.session_state.groq_model_ui = gqm

        b_t2, b_s2 = st.columns([1, 1])
        with b_t2:
            if st.button("🧪 Test Groq Connection", key="t_groq", use_container_width=True):
                with st.spinner("Testing Groq connection…"):
                    ok, msg = test_groq_connection(
                        api_key=GROQ_API_KEY,
                        model=st.session_state.groq_model_ui or GROQ_MODEL_ID)
                (st.success if ok else st.error)(f"{'✅' if ok else '❌'} {msg}")
        with b_s2:
            if st.button("💾 Save Groq Model to .env", key="save_groq_btn", use_container_width=True):
                save_env_variables({"GROQ_MODEL_ID": st.session_state.groq_model_ui})
                st.success("✅ Groq model ID saved to `.env`!")

    # ── TAB 2: IBM watsonx ───────────────────────────────────────────────────
    with t2:
        st.markdown("#### 🏛️ IBM watsonx.ai (Extension Officer Agent)")
        # API key / project status — loaded from .env, never shown
        ibm_key_ok  = bool(WATSONX_API_KEY)
        ibm_proj_ok = bool(WATSONX_PROJECT_ID)
        if ibm_key_ok:
            st.success("🔑 **IBM API Key:** Configured via `.env` (hidden for security)")
        else:
            st.error("🔑 **IBM API Key:** Not set — add `WATSONX_API_KEY` to your `.env` file.")
        if ibm_proj_ok:
            st.success(f"🗂️ **Project ID:** Configured via `.env` (hidden for security)")
        else:
            st.error("🗂️ **Project ID:** Not set — add `WATSONX_PROJECT_ID` to your `.env` file.")

        c2_col1, c2_col2 = st.columns(2)
        with c2_col1:
            wu = st.text_input("watsonx URL", value=st.session_state.wx_url_ui or WATSONX_URL, key="wx_u")
            st.session_state.wx_url_ui = wu
        with c2_col2:
            wm = st.text_input("IBM Model ID",
                               value=st.session_state.wx_model_ui or WATSONX_MODEL_ID,
                               help="e.g. openai/gpt-oss-120b or ibm/granite-4-0-tiny-preview", key="wx_m")
            st.session_state.wx_model_ui = wm

        b_t3, b_s3 = st.columns([1, 1])
        with b_t3:
            if st.button("🧪 Test IBM Connection", key="t_wx", use_container_width=True):
                with st.spinner("Testing watsonx connection…"):
                    ok, msg = test_watsonx_connection(
                        api_key=WATSONX_API_KEY,
                        project_id=WATSONX_PROJECT_ID,
                        url=st.session_state.wx_url_ui or WATSONX_URL,
                        model=st.session_state.wx_model_ui or WATSONX_MODEL_ID)
                (st.success if ok else st.error)(f"{'✅' if ok else '❌'} {msg}")
        with b_s3:
            if st.button("💾 Save IBM Model/URL to .env", key="save_ibm_btn", use_container_width=True):
                save_env_variables({
                    "WATSONX_URL": st.session_state.wx_url_ui,
                    "WATSONX_MODEL_ID": st.session_state.wx_model_ui,
                })
                st.success("✅ IBM model ID and URL saved to `.env`!")

    # ── TAB 3: Advanced Defaults ─────────────────────────────────────────────
    with t3:
        st.markdown("#### ⚙️ Active Configuration from `.env`")
        st.info("🔒 API keys are stored securely in `.env` and never displayed here.")
        st.json({
            "GEMINI_API_KEY": "●●●●●●●●" if GEMINI_API_KEY else "(not set)",
            "GEMINI_MODEL_ID": GEMINI_MODEL_ID,
            "GROQ_API_KEY": "●●●●●●●●" if GROQ_API_KEY else "(not set)",
            "GROQ_MODEL_ID": GROQ_MODEL_ID,
            "WATSONX_API_KEY": "●●●●●●●●" if WATSONX_API_KEY else "(not set)",
            "WATSONX_PROJECT_ID": "●●●●●●●●" if WATSONX_PROJECT_ID else "(not set)",
            "WATSONX_MODEL_ID": WATSONX_MODEL_ID,
            "WATSONX_URL": WATSONX_URL,
            "DEFAULT_WA_PHONE": DEFAULT_WA_PHONE or "(not set)",
            "DATABASE_PATH": "agri_doctor.db",
            "MAX_IMAGE_MB": 10,
            "MAX_OUTPUT_TOKENS": 1024,
        })
        if st.button("🔄 Reset Models to Recommended Working Defaults", use_container_width=True):
            save_env_variables({
                "GEMINI_MODEL_ID": "gemini-2.5-flash",
                "GROQ_MODEL_ID": "qwen/qwen3.8-27b",
                "WATSONX_MODEL_ID": "openai/gpt-oss-120b",
            })
            st.session_state.gemini_model_ui = "gemini-2.5-flash"
            st.session_state.groq_model_ui = "qwen/qwen3.8-27b"
            st.session_state.wx_model_ui = "openai/gpt-oss-120b"
            st.success("✅ Recommended working defaults restored and written to `.env`!")
            st.rerun()

    # ── TAB 4: WhatsApp ──────────────────────────────────────────────────────
    with t4:
        st.markdown("### 📱 WhatsApp Integration")
        st.markdown("""
        Agri Doctor makes it seamless to share diagnostic advisories directly with farmers via WhatsApp.
        - **Direct WhatsApp Web:** Click one button to open the chat pre-filled with the diagnosis.
        - **Automatic Formatting:** 10-digit phone numbers (e.g. `9876543210`) automatically receive the `+91` country code.
        - **Persistent Number:** Save your phone number below so it's always ready when you diagnose crops.
        """)

        st.markdown("---")
        st.markdown("#### 1️⃣ Connect WhatsApp Web")
        st.markdown("Open WhatsApp Web in your browser and scan the QR code once with your phone. Your session stays logged in.")
        c_qr, c_status = st.columns([2, 3])
        with c_qr:
            if st.button("🌐 Open WhatsApp Web", use_container_width=True, key="qr_open"):
                webbrowser.open("https://web.whatsapp.com")
                components.html("<script>window.open('https://web.whatsapp.com', '_blank');</script>", height=0)
                st.session_state.wa_web_opened = True
                st.success("✅ WhatsApp Web opened. Scan QR code if not logged in.")
        with c_status:
            if st.session_state.wa_web_opened:
                st.success("✅ WhatsApp Web session active — advisories will open directly in chat.")
            else:
                st.info("ℹ️ Click the button to the left to ensure WhatsApp Web is open in another tab.")

        st.markdown("---")
        st.markdown("#### 2️⃣ Default Farmer / Agronomist Phone Number")
        p_c1, p_c2 = st.columns([3, 1])
        with p_c1:
            w_ph = st.text_input("Default WhatsApp Number",
                                 value=st.session_state.wa_phone or DEFAULT_WA_PHONE,
                                 placeholder="e.g. 9876543210 or +919876543210",
                                 help="Indian 10-digit numbers automatically get +91 prefix.")
            st.session_state.wa_phone = w_ph
        with p_c2:
            st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
            if st.button("💾 Save Phone to .env", use_container_width=True, key="save_phone_btn"):
                save_env_variables({"DEFAULT_WA_PHONE": w_ph})
                st.success("✅ Default phone number saved to `.env`!")

        st.markdown("---")
        st.markdown("#### 3️⃣ Send Test Message")
        t_col1, t_col2 = st.columns([3, 2])
        with t_col1:
            tphone = st.text_input("Recipient Phone Number",
                                   value=st.session_state.wa_phone or DEFAULT_WA_PHONE,
                                   placeholder="+919876543210 or 9876543210",
                                   key="t_phone_input_val")
            if tphone:
                st.session_state.wa_phone = tphone

        target_test_phone = tphone or st.session_state.wa_phone or DEFAULT_WA_PHONE
        test_txt = "🌿 *Agri Doctor — Test Advisory*\n\n✅ WhatsApp integration is working successfully!\nYou can now receive crop health advisories directly via WhatsApp."
        t_ok, t_clean, t_urls = get_whatsapp_urls(target_test_phone, test_txt)

        with t_col2:
            if t_ok:
                st.link_button(
                    "📲 Open Test in WhatsApp",
                    url=t_urls["wa_me"],
                    type="primary",
                    use_container_width=True,
                    help="Opens WhatsApp with the test message pre-filled (wa.me — official URL)",
                )
            else:
                st.button("📲 Open Test in WhatsApp", type="primary", use_container_width=True,
                          key="btn_test_disabled", disabled=True)
                if target_test_phone:
                    st.caption(f"⚠️ {t_clean}")

        if t_ok:
            st.markdown(f"""
            <div style='background:#f0fdf4;border:1.5px solid #86efac;border-radius:10px;padding:0.75rem 1rem;margin:0.6rem 0;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:0.6rem;'>
                <div>
                    <strong style='color:#166534;'>💬 Test Ready for {t_clean}</strong>
                    <div style='font-size:0.8rem;color:#15803d;'>WhatsApp will open with the message pre-filled — tap Send to deliver it:</div>
                </div>
                <div style='display:flex;gap:0.5rem;flex-wrap:wrap;'>
                    <a href='{t_urls["wa_me"]}' target='_blank' style='
                        display:inline-block;background:#25D366;color:#ffffff;font-weight:700;
                        padding:0.45rem 1.1rem;border-radius:6px;text-decoration:none;
                        font-size:0.85rem;box-shadow:0 2px 6px rgba(37,211,102,.3);'>
                        🚀 wa.me (Recommended)
                    </a>
                    <a href='{t_urls["web_url"]}' target='_blank' style='
                        display:inline-block;background:#059669;color:#ffffff;font-weight:600;
                        padding:0.45rem 0.9rem;border-radius:6px;text-decoration:none;font-size:0.85rem;'>
                        🌐 Web
                    </a>
                </div>
            </div>
            """, unsafe_allow_html=True)

        st.markdown("---")
        with st.expander("☁️ Meta WhatsApp Business Cloud API (Preferred)", expanded=False):
            st.markdown(
                "Get credentials at [developers.facebook.com](https://developers.facebook.com/apps) "
                "→ Your App → WhatsApp → Getting Started. "
                "Set `WHATSAPP_ACCESS_TOKEN` and `WHATSAPP_PHONE_NUMBER_ID`."
            )
            mc1, mc2 = st.columns(2)
            with mc1:
                n_token = st.text_input(
                    "Access Token",
                    value=st.session_state.get("wa_access_token", ""),
                    placeholder="EAAxxxxxxx…",
                    type="password",
                    key="wa_meta_token",
                )
            with mc2:
                n_ph_id = st.text_input(
                    "Phone Number ID",
                    value=st.session_state.get("wa_phone_num_id", ""),
                    placeholder="123456789012345",
                    key="wa_meta_ph_id",
                )
            if st.button("💾 Save Meta Cloud API Credentials to .env", key="save_meta_wa"):
                st.session_state["wa_access_token"] = n_token
                st.session_state["wa_phone_num_id"] = n_ph_id
                save_env_variables({
                    "WHATSAPP_ACCESS_TOKEN":    n_token,
                    "WHATSAPP_PHONE_NUMBER_ID": n_ph_id,
                })
                st.success("✅ Meta Cloud API credentials saved to `.env`!")
                st.rerun()

        with st.expander("☁️ Twilio WhatsApp API (Alternative)", expanded=False):
            tc1, tc2 = st.columns(2)
            with tc1:
                ns = st.text_input("Account SID", value=st.session_state.twilio_sid,
                                   placeholder="ACxxxxxxxx", type="password", key="wa_sid")
            with tc2:
                nt = st.text_input("Auth Token", value=st.session_state.twilio_token,
                                   placeholder="••••••••", type="password", key="wa_tok")
            nf = st.text_input("From Number", value=st.session_state.twilio_from,
                               placeholder="whatsapp:+14155238886", key="wa_from")
            if st.button("💾 Save Twilio Credentials to .env", key="save_twilio"):
                st.session_state.twilio_sid   = ns
                st.session_state.twilio_token = nt
                st.session_state.twilio_from  = nf
                save_env_variables({
                    "TWILIO_ACCOUNT_SID": ns,
                    "TWILIO_AUTH_TOKEN": nt,
                    "TWILIO_FROM_NUMBER": nf,
                })
                st.success("✅ Twilio credentials saved to `.env`!")


# ══════════════════════════════════════════════════════════════════════════════
#  WHATSAPP AGENT DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════

def _wa_status_badge(status: str) -> str:
    """Return an HTML badge for a given WA delivery status."""
    styles = {
        "idle":        ("⧞ Idle",           "#6b7280","#f3f4f6"),
        "processing":  ("⏳ Processing",     "#1d4ed8","#eff6ff"),
        "validating":  ("🔍 Validating",     "#1d4ed8","#eff6ff"),
        "preparing":   ("🔧 Preparing",      "#92400e","#fef3c7"),
        "connecting":  ("🔌 Connecting",     "#0369a1","#e0f2fe"),
        "sending":     ("📡 Sending",        "#0369a1","#e0f2fe"),
        "ready":       ("📋 Prepared",       "#166534","#dcfce7"),
        "prepared":    ("📋 Prepared",       "#166534","#dcfce7"),
        "sent":        ("📤 Sent",           "#166534","#dcfce7"),
        "delivered":   ("📬 Delivered",      "#166534","#f0fdf4"),
        "read":        ("👁️ Read",           "#7c3aed","#f5f3ff"),
        "failed":      ("❌ Failed",         "#991b1b","#fee2e2"),
    }
    lbl, color, bg = styles.get(status, (status.title(), "#374151", "#f3f4f6"))
    return (
        f"<span style='background:{bg};color:{color};"
        f"border-radius:20px;padding:3px 12px;font-size:.78rem;"
        f"font-weight:700;border:1px solid {color}33;'>{lbl}</span>"
    )


def _wa_step_row(label: str, done: bool, detail: str = "", ts: str = "") -> str:
    """Render a single delivery pipeline step row."""
    color = "#166534" if done else "#6b7280"
    bg    = "#f0fdf4" if done else "#f9fafb"
    border= "#86efac" if done else "#e5e7eb"
    tick  = "✅" if done else "⏸️"
    det_html = f"<div style='font-size:.73rem;color:#6b7280;margin-top:1px;'>{detail}</div>" if detail else ""
    ts_html  = f"<div style='font-size:.68rem;color:#9ca3af;white-space:nowrap;'>{ts}</div>" if ts else ""
    return (
        f"<div style='display:flex;align-items:flex-start;gap:0.75rem;"
        f"background:{bg};border:1px solid {border};border-radius:10px;"
        f"padding:0.6rem 0.9rem;margin-bottom:0.4rem;'>"
        f"<span style='font-size:1.1rem;line-height:1.4'>{tick}</span>"
        f"<div style='flex:1'>"
        f"<div style='font-size:.82rem;font-weight:700;color:{color};'>{label}</div>"
        f"{det_html}"
        f"</div>"
        f"{ts_html}"
        f"</div>"
    )


def page_whatsapp_agent():
    """📱 WhatsApp Report Delivery Agent dashboard page."""
    st.markdown(
        "<div class='sec-head'>📱 WhatsApp Report Delivery Agent</div>",
        unsafe_allow_html=True,
    )

    # ── Detect active sending method ──────────────────────────────────────────
    from agents.whatsapp_agent import SELENIUM_AVAILABLE as _WA_SEL
    _has_meta   = bool(st.session_state.get("wa_access_token") and st.session_state.get("wa_phone_num_id"))
    _has_twilio = bool(st.session_state.get("twilio_sid") and st.session_state.get("twilio_token"))
    if _WA_SEL:
        _active_method_label = "WhatsApp Web via Selenium (automatic — Chrome)"
        _method_color = "#166534"
    elif _has_meta:
        _active_method_label = "Meta Business Cloud API (automatic)"
        _method_color = "#166534"
    elif _has_twilio:
        _active_method_label = "Twilio WhatsApp API (automatic)"
        _method_color = "#1d4ed8"
    else:
        _active_method_label = "WhatsApp Web URL (browser — you click Send)"
        _method_color = "#92400e"

    st.markdown(
        f"<p style='color:#6b7280;font-size:.85rem;margin-top:-.4rem'>"
        f"Agent: <strong>{WA_AGENT_NAME}</strong> · "
        f"Delivery method: <span style='color:{_method_color};font-weight:600'>{_active_method_label}</span></p>",
        unsafe_allow_html=True,
    )

    if _WA_SEL:
        st.success(
            "✅ **Selenium + Chrome available** — the full report will be pushed directly into "
            "WhatsApp Web and sent automatically when you click **Send Report to WhatsApp** below."
        )
    elif not _has_meta and not _has_twilio:
        st.info(
            "💡 **Install Selenium** (`pip install selenium`) to send automatically via WhatsApp Web. "
            "Or configure the Meta Business Cloud API in ⚙️ Settings → WhatsApp. "
            "Without either, messages are *prepared* as a URL — you must click **Send** in the browser."
        )

    last = st.session_state.get("last_wa_delivery")

    if last:
        st.markdown("### 📊 Latest Delivery")
        status       = last.get("status", "idle")
        phone_m      = last.get("phone_masked", "—")
        title        = last.get("report_title", "—")
        wa_url       = last.get("wa_url", "")
        error        = last.get("error")
        d_id         = last.get("delivery_id", "")
        steps        = last.get("steps", [])
        msg_ids      = last.get("msg_ids", [])
        parts_total  = last.get("parts_total", 0)
        parts_sent   = last.get("parts_sent", 0)
        method_used  = last.get("method_used", "")
        was_sent     = last.get("sent", False)
        was_prepared = last.get("prepared", False)

        # ── Header card ────────────────────────────────────────────────────────
        st.markdown(
            f"<div style='background:linear-gradient(135deg,#052e16,#14532d);"
            f"border-radius:16px;padding:1.2rem 1.6rem;margin-bottom:1rem;"
            f"box-shadow:0 4px 16px rgba(5,46,22,.3);display:flex;"
            f"justify-content:space-between;align-items:center;flex-wrap:wrap;gap:0.75rem;'>"
            f"<div>"
            f"<div style='color:#4ade80;font-size:1rem;font-weight:800;'>🤖 {WA_AGENT_NAME}</div>"
            f"<div style='color:rgba(255,255,255,.65);font-size:.78rem;margin-top:3px;'>"
            f"ID: <code style='color:#86efac'>{d_id}</code> · "
            f"To: <strong style='color:#d1fae5'>{phone_m}</strong>"
            f"</div>"
            f"</div>"
            f"<div style='text-align:right'>"
            f"{_wa_status_badge(status)}"
            f"<div style='color:rgba(255,255,255,.5);font-size:.7rem;margin-top:4px'>{title[:60]}</div>"
            f"</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

        # ── Metrics row ────────────────────────────────────────────────────────
        mc1, mc2, mc3, mc4 = st.columns(4)
        mc1.metric("Method", method_used.upper() if method_used else "—")
        mc2.metric("Parts", f"{parts_sent}/{parts_total}" if parts_total else "—")
        mc3.metric("Message IDs", str(len(msg_ids)) if msg_ids else "—")
        status_lbl = "✅ Sent" if was_sent else ("📋 Prepared" if was_prepared else "❌ Failed")
        mc4.metric("Delivery", status_lbl)

        # ── Note for prepared (browser) messages ──────────────────────────────
        if was_prepared and wa_url:
            st.warning(
                "📋 **Message Prepared** — The report has been formatted and a WhatsApp Web link "
                "is ready. Click the button below to open WhatsApp Web with the report pre-filled, "
                "then click **Send** in the chat."
            )
        elif was_sent:
            st.success(
                f"✅ **Message Sent** — The complete Agri Doctor report was delivered to {phone_m} "
                f"via {method_used.upper()}."
                + (f" Message IDs: `{', '.join(msg_ids)}`" if msg_ids else "")
            )

        # ── Delivery pipeline steps ────────────────────────────────────────────
        if steps:
            st.markdown("**🔄 Delivery Pipeline**")
            for s in steps:
                st.markdown(
                    _wa_step_row(
                        label=s.get("name", ""),
                        done=s.get("ok", False),
                        detail=s.get("detail", ""),
                        ts=s.get("time", ""),
                    ),
                    unsafe_allow_html=True,
                )

        # ── Action buttons ─────────────────────────────────────────────────────
        c1, c2, c3 = st.columns(3)
        with c1:
            if wa_url and status not in ("failed",):
                st.link_button(
                    "📲 Open in WhatsApp Web",
                    url=wa_url,
                    type="primary",
                    use_container_width=True,
                )
        with c2:
            # Preview the formatted WhatsApp message
            report_text = st.session_state.get("last_combined", "")
            if report_text:
                with st.expander("👁️ Preview Message"):
                    preview = format_report_as_whatsapp_text(
                        report_text,
                        report_title=title,
                        report_id=d_id,
                    )
                    st.text_area("Formatted WhatsApp Text", preview, height=300,
                                 key="wa_preview_text", disabled=True)
        with c3:
            if status == "failed" and d_id:
                if st.button("🔄 Retry Delivery", use_container_width=True, key="wa_retry_btn"):
                    with st.spinner("Retrying delivery…"):
                        agent = WhatsAppReportAgent()
                        result = agent.retry(d_id)
                    st.session_state.last_wa_delivery = result
                    st.rerun()

        if error:
            st.error(f"⚠️ **Error:** {error}")

    else:
        st.markdown(
            "<div class='card' style='text-align:center;padding:2.5rem'>"
            "<div style='font-size:3rem'>📱</div>"
            "<p style='font-weight:700;color:#14532d!important;margin:.6rem 0 .2rem'>"
            "No deliveries yet</p>"
            "<p style='color:#6b7280!important;font-size:.82rem'>"
            "Run a diagnosis and use the panel below to send your WhatsApp report.</p>"
            "</div>",
            unsafe_allow_html=True,
        )

    st.markdown("---")

    # ── Send / Trigger panel ───────────────────────────────────────────────────
    with st.expander("🚀 Send a Report via WhatsApp", expanded=not bool(last)):
        st.markdown("#### Trigger the WhatsApp Report Agent")

        m_c1, m_c2 = st.columns([2, 1])
        with m_c1:
            m_phone = st.text_input(
                "Recipient WhatsApp Number",
                value=st.session_state.wa_phone or DEFAULT_WA_PHONE,
                placeholder="9876543210 or +919876543210",
                key="wa_agent_phone",
            )
        with m_c2:
            m_name = st.text_input("Recipient Name (optional)", key="wa_agent_name")

        last_disease = ""
        if st.session_state.get("last_path_report"):
            last_disease = st.session_state.last_path_report.get("suspected_disease", "")
        m_title = st.text_input(
            "Report Title (optional)",
            value=(last_disease + " Advisory").strip() if last_disease else "",
            key="wa_agent_title",
        )

        # Sending method selector
        from agents.whatsapp_agent import SELENIUM_AVAILABLE as _WA_SELENIUM_OK
        method_options = [
            "auto (WhatsApp Web → API)",
            "selenium (WhatsApp Web — automatic)",
            "meta (Cloud API)",
            "twilio",
            "webbrowser (manual — you click Send)",
        ]
        m_method = st.selectbox(
            "Sending Method",
            method_options,
            index=0,
            key="wa_send_method",
            help="'auto' uses WhatsApp Web (Selenium) automatically. Selenium requires Chrome.",
        )
        chosen_method = m_method.split(" ")[0]  # "auto", "selenium", "meta", "twilio", "webbrowser"

        if chosen_method in ("auto", "selenium"):
            if _WA_SELENIUM_OK:
                st.success(
                    "✅ **Selenium + Chrome is ready.** The report will be pushed directly "
                    "into WhatsApp Web and sent automatically. Make sure you are logged into "
                    "WhatsApp Web in Chrome."
                )
            else:
                st.warning(
                    "⚠️ Selenium is not installed. Install with: `pip install selenium`. "
                    "Falling back to manual browser URL."
                )

        has_report = bool(st.session_state.get("last_combined"))
        if has_report:
            st.success("✅ Latest diagnosis report from this session will be sent.")
        else:
            st.info("ℹ️ No session report — will use the most recent database record.")

        if st.button("📲 Send Report to WhatsApp", type="primary", use_container_width=True, key="wa_run_manual_btn"):
            if not m_phone.strip():
                st.error("❌ Please enter a phone number.")
            else:
                # Live progress status box
                progress_log = []
                status_placeholder = st.empty()

                def _wa_progress(step_text: str):
                    progress_log.append(step_text)
                    status_placeholder.info(
                        "🔄 **Sending…**\n\n"
                        + "\n\n".join(f"• {s}" for s in progress_log[-5:])
                    )

                with st.spinner("🤖 WhatsApp Agent running…"):
                    agent = WhatsAppReportAgent()
                    result = agent.run(
                        phone=m_phone.strip(),
                        report_text=st.session_state.get("last_combined", ""),
                        report_title=m_title.strip(),
                        session_id=st.session_state.session_id,
                        recipient_name=m_name.strip(),
                        method=chosen_method,
                        wa_access_token=st.session_state.get("wa_access_token", ""),
                        wa_phone_number_id=st.session_state.get("wa_phone_num_id", ""),
                        twilio_sid=st.session_state.get("twilio_sid", ""),
                        twilio_token=st.session_state.get("twilio_token", ""),
                        twilio_from=st.session_state.get("twilio_from", ""),
                        progress_callback=_wa_progress,
                    )

                status_placeholder.empty()
                st.session_state.last_wa_delivery = result
                st.session_state.wa_phone = m_phone.strip()
                st.rerun()

    # ── Delivery History ───────────────────────────────────────────────────────
    st.markdown("### 🕒 Delivery History")
    try:
        history = get_recent_wa_deliveries(limit=10)
    except Exception:
        history = []

    if history:
        for rec in history:
            status_h = rec.get("status", "idle")
            d_id_h   = rec.get("delivery_id", "")[:8]
            phone_h  = rec.get("phone_normalized") or rec.get("phone_raw", "—")
            title_h  = rec.get("report_title", "—")[:50]
            ts_h     = rec.get("created_at", "")[:19]
            err_h    = rec.get("error_message", "") or ""
            wa_url_h = rec.get("wa_url", "")
            err_disp = ("  · ⚠️ " + err_h[:60]) if err_h else ""

            st.markdown(
                f"<div class='hrow'>"
                f"<div>"
                f"<div class='hrow-title'>📱 {title_h}</div>"
                f"<div class='hrow-meta'>🕒 {ts_h} · {phone_h} · "
                f"<code style='font-size:.7rem'>{d_id_h}…</code>"
                f"{err_disp}</div>"
                f"</div>"
                f"{_wa_status_badge(status_h)}"
                f"</div>",
                unsafe_allow_html=True,
            )
            if wa_url_h and status_h in ("ready", "sent", "prepared"):
                st.link_button(
                    "📲 Re-open in WhatsApp",
                    url=wa_url_h,
                    use_container_width=False,
                )
    else:
        st.markdown(
            "<div class='card' style='text-align:center;padding:1.5rem'>"
            "<p style='color:#6b7280!important;font-size:.82rem'>No delivery records yet.</p>"
            "</div>",
            unsafe_allow_html=True,
        )


# ══════════════════════════════════════════════════════════════════════════════
#  ROUTER
# ══════════════════════════════════════════════════════════════════════════════
_p = st.session_state.get("page","🏠 Home")
if   _p == "🏠 Home":           page_home()
elif _p == "🔬 Diagnose Crop":  page_diagnose()
elif _p == "🤖 Agent Workflow": page_workflow()
elif _p == "📱 WhatsApp Agent": page_whatsapp_agent()
elif _p == "📋 History":        page_history()
elif _p == "📊 Performance":    render_performance_dashboard()
elif _p == "🛡️ Guardrails":    page_guardrails()
elif _p == "⚙️ Settings":       page_settings()
