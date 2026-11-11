"""
config.py — Application-wide configuration for Agri Doctor.
Loads environment variables from .env and exposes typed constants.
Never hardcode API keys here; always read from environment.
"""

import os
from dotenv import load_dotenv

# Load .env file if present (development only)
load_dotenv()

# ──────────────────────────────────────────────
# IBM watsonx.ai Configuration
# ──────────────────────────────────────────────
WATSONX_API_KEY: str = os.getenv("WATSONX_API_KEY", "")
WATSONX_PROJECT_ID: str = os.getenv("WATSONX_PROJECT_ID", "")
WATSONX_URL: str = os.getenv("WATSONX_URL", "https://us-south.ml.cloud.ibm.com")

# Default model: IBM Granite 4 H Small (current supported identifier)
WATSONX_MODEL_ID: str = os.getenv("WATSONX_MODEL_ID", "ibm/granite-4-0-tiny-preview")

# ──────────────────────────────────────────────
# Google Gemini Vision Configuration (Primary)
# ──────────────────────────────────────────────
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL_ID: str = os.getenv("GEMINI_MODEL_ID", "gemini-2.5-flash")

# ──────────────────────────────────────────────
# Groq Vision LLM Configuration (Fallback)
# ──────────────────────────────────────────────
GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL_ID: str = os.getenv("GROQ_MODEL_ID", "qwen/qwen3.8-27b")

# ──────────────────────────────────────────────
# Application Settings
# ──────────────────────────────────────────────
APP_TITLE: str = "Agri Doctor"
APP_SUBTITLE: str = "AI-Powered Crop Health Assistant"
APP_VERSION: str = "1.0.0"

# WhatsApp & Twilio & Meta Cloud API Configuration
DEFAULT_WA_PHONE: str = os.getenv("DEFAULT_WA_PHONE", "")
TWILIO_ACCOUNT_SID: str = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN: str = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER: str = os.getenv("TWILIO_FROM_NUMBER", "whatsapp:+14155238886")

# WhatsApp Business Cloud API (Meta Graph API)
WHATSAPP_ACCESS_TOKEN: str = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID: str = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
WHATSAPP_BUSINESS_ACCOUNT_ID: str = os.getenv("WHATSAPP_BUSINESS_ACCOUNT_ID", "")
WHATSAPP_VERIFY_TOKEN: str = os.getenv("WHATSAPP_VERIFY_TOKEN", "")

# Database
DATABASE_PATH: str = os.getenv("DATABASE_PATH", "agri_doctor.db")

# Image upload constraints
MAX_IMAGE_SIZE_MB: int = 10
ALLOWED_IMAGE_TYPES: list = ["jpg", "jpeg", "png"]
ALLOWED_MIME_TYPES: list = ["image/jpeg", "image/png"]

# LLM token limits
MAX_INPUT_TOKENS: int = 4096
MAX_OUTPUT_TOKENS: int = 1024
WATSONX_MAX_TOKENS: int = 1024
WATSONX_TEMPERATURE: float = 0.3
WATSONX_TOP_P: float = 0.9

# Rate limiting
MAX_REQUESTS_PER_MINUTE: int = 10
REQUEST_TIMEOUT_SECONDS: int = 60

# Retry configuration
MAX_RETRIES: int = 3
RETRY_DELAY_SECONDS: float = 2.0

# ──────────────────────────────────────────────
# Guardrails Configuration
# ──────────────────────────────────────────────
# Prompt injection keywords to block
INJECTION_KEYWORDS: list = [
    "ignore previous instructions",
    "ignore all instructions",
    "disregard",
    "forget your instructions",
    "act as",
    "pretend you are",
    "jailbreak",
    "bypass",
    "override system",
    "you are now",
    "new persona",
    "DAN",
    "do anything now",
]

# Keywords that signal potentially dangerous pesticide advice
UNSAFE_CHEMICAL_KEYWORDS: list = [
    "mix chemicals",
    "dangerous combination",
    "lethal dose",
    "drink",
    "ingest",
    "poison",
]

# PII patterns (regex)
PII_PATTERNS: list = [
    r"\b\d{10,13}\b",          # Phone numbers
    r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}",  # Email
    r"\b\d{12}\b",              # Aadhaar-like
]

# Toxicity / harassment keywords
TOXICITY_KEYWORDS: list = [
    "hate", "kill", "murder", "attack", "terrorist",
    "bomb", "exploit", "illegal", "fraud",
]

# ──────────────────────────────────────────────
# UI Theme Colors
# ──────────────────────────────────────────────
COLORS = {
    "primary": "#4a7c59",       # Forest green
    "secondary": "#8fba8a",     # Sage green
    "accent": "#c8b560",        # Golden wheat
    "background": "#f7f5f0",    # Warm cream
    "surface": "#ffffff",       # White
    "text": "#2c3e2d",          # Dark forest
    "muted": "#7a8c7b",         # Muted green-grey
    "success": "#3a7d44",       # Success green
    "warning": "#d4a017",       # Warning amber
    "error": "#c0392b",         # Error red
    "info": "#2980b9",          # Info blue
}

# ──────────────────────────────────────────────
# Persistent Environment Storage Helper
# ──────────────────────────────────────────────
def save_env_variables(updates: dict) -> bool:
    """
    Save key-value pairs permanently to the .env file and update the in-memory config.
    """
    import sys
    this_module = sys.modules[__name__]
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

    lines = []
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

    updated_keys = set()
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                new_lines.append(f"{key}={updates[key]}\n")
                updated_keys.add(key)
                continue
        new_lines.append(line)

    for k, v in updates.items():
        if k not in updated_keys:
            new_lines.append(f"{k}={v}\n")

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    for k, v in updates.items():
        os.environ[k] = str(v)
        if hasattr(this_module, k):
            setattr(this_module, k, v)

    return True
