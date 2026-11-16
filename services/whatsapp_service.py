"""
services/whatsapp_service.py — WhatsApp messaging for Agri Doctor.

Method 1 (default): WhatsApp Web via Python built-in `webbrowser` module.
  - Zero extra dependencies — works out of the box.
  - Opens wa.me link or web.whatsapp.com/send in the system browser.
  - User must be logged into WhatsApp Web (once per browser).

Method 2 (pywhatkit / pyautogui): Uses pyautogui to auto-send via WhatsApp Web.
  - Requires pyautogui.
  - Opens browser → auto-fills & sends the message after a short delay.

Method 3 (twilio): Sends via Twilio WhatsApp API.
  - Requires Twilio account + WhatsApp-enabled number.

Method 4 (meta): WhatsApp Business Cloud API (Meta Graph API).
  - Requires META_WA_ACCESS_TOKEN and META_WA_PHONE_NUMBER_ID.
  - Sends actual WhatsApp messages — no browser needed.
  - Text-only; does not attach PDFs.
"""

import sys
import os
import logging
import re
import urllib.parse
import webbrowser
import time
import requests

logger = logging.getLogger(__name__)

# WhatsApp message limits
MAX_WA_MSG_CHARS    = 4096   # WhatsApp API hard limit per message
PREFERRED_PART_SIZE = 3800   # Split before this to keep headroom for part headers
TRUNCATION_SUFFIX   = "\n\n… [Report continues in next message]"

# ── Ensure venv packages are importable ───────────────────────────────────────
_venv_site = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "venv", "lib", "python3.9", "site-packages",
)
if os.path.isdir(_venv_site) and _venv_site not in sys.path:
    sys.path.insert(0, _venv_site)

# ── Keyboard automation for auto-sending via WhatsApp Web ─────────────────────
try:
    import pyautogui
    pyautogui.FAILSAFE = False
    PYAUTOGUI_AVAILABLE = True
except Exception:
    PYAUTOGUI_AVAILABLE = False

try:
    import pywhatkit as _pwk
    PYWHATKIT_AVAILABLE = True
except Exception:
    PYWHATKIT_AVAILABLE = PYAUTOGUI_AVAILABLE   # fall back to raw pyautogui path


# ─────────────────────────────────────────────────────────────────────────────
#  Phone number helpers
# ─────────────────────────────────────────────────────────────────────────────

def _clean_phone(phone: str, default_country: str = "91") -> tuple:
    """
    Clean and format phone number to E.164 (+<country_code><number>).
    Gracefully handles 10-digit Indian numbers, leading zeros, dashes, spaces.
    Returns (ok: bool, result: str) where result is E.164 number or error message.
    """
    p = phone.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if not p:
        return False, "Phone number is empty."

    digits = p.lstrip("+")
    if not digits.isdigit():
        return False, "Invalid phone number: contains non-digit characters."

    # Leading 0 → replace with country code (e.g. 09876543210 → 919876543210)
    if len(digits) == 11 and digits.startswith("0"):
        digits = default_country + digits[1:]
    # 10-digit number without country code → prepend default_country
    elif len(digits) == 10:
        digits = default_country + digits
    # 12-digit already prefixed correctly
    elif len(digits) == 12 and digits.startswith(default_country):
        pass

    if len(digits) < 8 or len(digits) > 15:
        return False, f"Invalid phone number length ({len(digits)} digits). Must be 8–15 digits."

    return True, "+" + digits


def _truncate(text: str, max_chars: int = MAX_WA_MSG_CHARS) -> str:
    """Truncate to max_chars adding a suffix to indicate truncation."""
    if len(text) <= max_chars:
        return text
    cut = max_chars - len(TRUNCATION_SUFFIX)
    return text[:cut] + TRUNCATION_SUFFIX


# ─────────────────────────────────────────────────────────────────────────────
#  Full-report WhatsApp text formatter
# ─────────────────────────────────────────────────────────────────────────────

def format_report_as_whatsapp_text(
    report_text: str,
    report_title: str = "",
    report_id: str = "",
) -> str:
    """
    Convert the Agri Doctor full diagnosis report into a properly structured
    WhatsApp text message using *bold*, line breaks, and relevant emojis.

    Only includes sections where actual content was generated.
    Does NOT invent information for missing sections.
    """
    now = time.strftime("%d %b %Y, %I:%M %p")
    id_line = f"\n🆔 Report ID: `{report_id}`" if report_id else ""

    header = (
        f"🌱 *AGRI DOCTOR – CROP HEALTH REPORT*\n"
        f"📅 {now}{id_line}\n"
        + ("─" * 30) + "\n\n"
    )

    if not report_text or not report_text.strip():
        return header + "_No report content available._\n\n— Agri Doctor AI 🤖"

    # ── Extract sections from the report using common heading patterns ────────
    sections = _parse_report_sections(report_text)

    body_parts = []

    # 1. Crop Information
    crop_info = _collect_fields(sections, [
        "crop", "crop name", "crop type", "crop information",
        "condition", "crop condition", "observed symptoms", "symptoms",
    ])
    if crop_info:
        body_parts.append("*1. Crop Information*\n" + crop_info)

    # 2. Disease Diagnosis
    diag = _collect_fields(sections, [
        "disease", "suspected disease", "diagnosis", "identified disease",
        "confidence", "confidence level", "diagnosis explanation",
        "possible causes", "other possible causes",
    ])
    if not diag:
        # Try to extract directly from raw text
        diag = _extract_inline(report_text, [
            "Suspected Disease", "Confidence", "Diagnosis", "Disease Name",
        ])
    if diag:
        body_parts.append("*2. Disease Diagnosis*\n" + diag)

    # 3. Symptoms Analysis
    symptoms = _collect_fields(sections, [
        "symptoms analysis", "visual evidence", "visual symptoms",
        "observed symptoms", "symptom details",
    ])
    if symptoms:
        body_parts.append("*3. Symptoms Analysis*\n" + symptoms)

    # 4. Treatment Recommendations
    treatment = _collect_fields(sections, [
        "treatment", "treatment recommendations", "recommended treatment",
        "organic", "organic alternatives", "natural alternatives",
        "preventive measures", "prevention",
    ])
    if treatment:
        body_parts.append("*4. Treatment Recommendations*\n" + treatment)

    # 5. Nutrient Recommendations
    nutrients = _collect_fields(sections, [
        "nutrient", "nutrient recommendations", "nutrient deficiency",
        "soil management", "fertilizer", "fertiliser",
    ])
    if nutrients:
        body_parts.append("*5. Nutrient Recommendations*\n" + nutrients)

    # 6. Risk Assessment
    risk = _collect_fields(sections, [
        "risk", "risk assessment", "severity", "disease severity",
        "spread risk", "urgency",
    ])
    if risk:
        body_parts.append("*6. Risk Assessment*\n" + risk)

    # 7. Additional Recommendations
    extra = _collect_fields(sections, [
        "additional recommendations", "monitoring", "follow-up",
        "precautions", "important", "notes",
    ])
    if extra:
        body_parts.append("*7. Additional Recommendations*\n" + extra)

    # ── If section parsing found nothing, fall back to cleaned raw text ───────
    if not body_parts:
        cleaned = _clean_raw_report(report_text)
        body_parts = [cleaned]

    body = "\n\n".join(body_parts)

    footer = (
        "\n\n" + ("─" * 30) + "\n"
        "_Report generated by Agri Doctor AI._\n"
        "_AI-generated assessment — consult a qualified agronomist before applying treatment._\n\n"
        "Thank you for using Agri Doctor! 🌾"
    )

    return header + body + footer


def _parse_report_sections(text: str) -> dict:
    """
    Parse a report text into a dict of {section_heading_lower: content_string}.
    Recognises common heading styles used by the Agri Doctor agents.
    """
    sections = {}
    current_key = None
    current_lines = []

    # Patterns for section headings
    heading_re = re.compile(
        r"^(?:#+\s*|={2,}\s*|\*{1,2}|[-]{2,}\s*)?([A-Za-z][A-Za-z0-9 /&,()-]{2,60})"
        r"(?:\s*[:\*#=\-]{0,3})\s*$"
    )

    for line in text.splitlines():
        stripped = line.strip()
        # Skip decoration lines
        if re.match(r"^[=\-*#]{3,}$", stripped):
            continue
        # Check if this looks like a heading
        m = heading_re.match(stripped)
        if m and len(stripped) < 80 and not stripped.endswith("."):
            # Save previous section
            if current_key and current_lines:
                sections[current_key] = "\n".join(current_lines).strip()
            current_key = m.group(1).strip().lower()
            current_lines = []
        else:
            if current_key is not None:
                current_lines.append(line)

    # Save last section
    if current_key and current_lines:
        sections[current_key] = "\n".join(current_lines).strip()

    return sections


def _collect_fields(sections: dict, keywords: list) -> str:
    """
    Collect content from sections matching any of the keywords.
    Returns formatted bullet-point string, or "" if nothing found.
    """
    collected = []
    seen_keys = set()
    for kw in keywords:
        kw_l = kw.lower()
        for key, content in sections.items():
            if key in seen_keys:
                continue
            if kw_l in key or key in kw_l:
                val = content.strip()
                if val and val not in ("", "N/A", "None", "n/a"):
                    # Format as clean bullet points
                    formatted = _format_section_content(val)
                    if formatted:
                        collected.append(formatted)
                        seen_keys.add(key)
    return "\n".join(collected)


def _format_section_content(text: str) -> str:
    """Convert multi-line section content to clean WhatsApp-friendly bullets."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    out = []
    for line in lines:
        # Already a bullet or numbered item
        if re.match(r"^[-•*\d+\.]", line):
            out.append(line)
        else:
            out.append(f"• {line}")
    return "\n".join(out)


def _extract_inline(text: str, field_names: list) -> str:
    """Extract field: value pairs from unstructured text."""
    results = []
    for name in field_names:
        pattern = re.compile(
            rf"{re.escape(name)}\s*[:\-]\s*(.+?)(?:\n|$)", re.IGNORECASE
        )
        m = pattern.search(text)
        if m:
            val = m.group(1).strip().strip("*_")
            if val and val.lower() not in ("n/a", "none", ""):
                results.append(f"• *{name}:* {val}")
    return "\n".join(results)


def _clean_raw_report(text: str) -> str:
    """Strip markdown-heavy formatting, return clean lines for WhatsApp."""
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        # Remove pure decoration lines
        if re.match(r"^[=\-*#_]{3,}$", stripped):
            continue
        # Remove excessive asterisks / hashes used as headers
        cleaned = re.sub(r"^#{1,6}\s*", "", stripped)
        cleaned = re.sub(r"^\*{2,}\s*", "*", cleaned)
        if cleaned:
            lines.append(cleaned)
    # Collapse multiple blank lines
    result = re.sub(r"\n{3,}", "\n\n", "\n".join(lines))
    return result.strip()


# ─────────────────────────────────────────────────────────────────────────────
#  Message splitting
# ─────────────────────────────────────────────────────────────────────────────

def split_message_into_parts(
    message: str,
    max_part_size: int = PREFERRED_PART_SIZE,
    report_id: str = "",
) -> list:
    """
    Split a long WhatsApp message into ordered parts that each fit within
    max_part_size characters.

    Each part is prefixed with a "Part X/N" header so the recipient knows
    the message sequence. All parts share the same report_id suffix.

    Returns a list of strings, each ≤ max_part_size chars.
    If the message fits in one part, returns a list with one item.
    """
    # Reserve chars for the "Part X/N" header prefix we add later
    HEADER_RESERVE = 60
    effective_max  = max_part_size - HEADER_RESERVE

    if len(message) <= max_part_size:
        return [message]

    chunks: list = []
    current = ""

    def _flush():
        nonlocal current
        if current.strip():
            chunks.append(current.rstrip())
        current = ""

    def _add_segment(seg: str):
        """Add a text segment, splitting it further if it alone exceeds effective_max."""
        nonlocal current
        # Force-slice any segment that by itself is longer than effective_max
        while len(seg) > effective_max:
            space_left = effective_max - len(current)
            if space_left >= 80:
                snip = seg[:space_left]
                current += snip
                seg = seg[space_left:]
                _flush()
            else:
                _flush()

        # Try appending the (now small enough) segment to the current chunk
        sep = "\n\n" if current else ""
        if len(current) + len(sep) + len(seg) <= effective_max:
            current = current + sep + seg
        else:
            _flush()
            current = seg

    # Walk paragraphs then lines for splitting
    for para in message.split("\n\n"):
        if len(para) <= effective_max:
            _add_segment(para)
        else:
            # Paragraph too big — try splitting by single newlines
            for line in para.split("\n"):
                if line.strip():
                    _add_segment(line)
    _flush()

    # Edge case: nothing accumulated
    if not chunks:
        return [message]

    # Single chunk — no Part header needed
    if len(chunks) == 1:
        return [message]

    # Add Part X/N prefix to each chunk
    total = len(chunks)
    parts = []
    id_suffix = f"\n🆔 `{report_id}`" if report_id else ""
    for i, chunk in enumerate(chunks, 1):
        header = f"📋 *Part {i}/{total}*{id_suffix}\n\n"
        parts.append(header + chunk)

    return parts


# ─────────────────────────────────────────────────────────────────────────────
#  URL helpers
# ─────────────────────────────────────────────────────────────────────────────

def get_whatsapp_urls(phone_number: str, message: str) -> tuple:
    """
    Generate direct WhatsApp click-to-chat links.

    Primary URL uses the official wa.me format which is universally supported
    on both desktop browsers (opens WhatsApp Web) and mobile (opens WhatsApp app).

    Returns (ok, phone_or_error, urls_dict).
    """
    ok, phone = _clean_phone(phone_number)
    if not ok:
        return False, phone, {}

    # Truncate to a safe URL length (browsers differ in their limits)
    url_text = _truncate(message, 1500)
    phone_digits = phone.lstrip("+")
    # urllib.parse.quote encodes spaces as %20 — correct for WhatsApp URLs
    encoded_msg = urllib.parse.quote(url_text, safe="")

    # wa.me is the official, universally-compatible click-to-chat URL
    wa_me_url  = f"https://wa.me/{phone_digits}?text={encoded_msg}"
    # Fallback URLs kept for completeness
    web_url    = f"https://web.whatsapp.com/send/?phone={phone_digits}&text={encoded_msg}"
    api_url    = f"https://api.whatsapp.com/send/?phone={phone_digits}&text={encoded_msg}"

    return True, phone, {
        "wa_me":   wa_me_url,   # Primary — official click-to-chat
        "web_url": web_url,     # Direct WhatsApp Web
        "api_url": api_url,     # api.whatsapp.com (mobile-friendly fallback)
    }


# ─────────────────────────────────────────────────────────────────────────────
#  Compact message builder  (fits within URL/pywhatkit limits)
# ─────────────────────────────────────────────────────────────────────────────

# pywhatkit encodes the full message in the URL — browsers reject URLs longer
# than ~2000 chars.  We build a compact but complete advisory that always fits.
_PYWHATKIT_MAX_CHARS = 1200

def _build_compact_advisory(full_text: str) -> str:
    """
    Extract the essential fields from the full report and return a compact
    WhatsApp-safe message (≤ _PYWHATKIT_MAX_CHARS chars).
    """
    lines = [l.strip() for l in full_text.splitlines() if l.strip()]

    def _get(labels):
        for label in labels:
            for line in lines:
                lw = line.lower()
                if lw.startswith(label.lower()):
                    val = re.sub(r"^[^:]+:\s*", "", line, count=1).strip(" *_")
                    if val and val.lower() not in ("none", "n/a", "unknown", "?"):
                        return val
        return ""

    disease   = _get(["Suspected Disease", "Disease", "Diagnosis"])
    conf      = _get(["Confidence Level", "Confidence"])
    severity  = _get(["Disease Severity", "Severity"])
    summary   = _get(["Summary"])
    recovery  = _get(["Est. Recovery", "Estimated Recovery"])

    # Bullet lists: grab first 3 items after a heading
    def _bullets(heading_kw, limit=3):
        capture = False
        items = []
        for line in lines:
            if heading_kw.lower() in line.lower() and ":" in line:
                capture = True
                continue
            if capture:
                if line.startswith(("•", "-", "√", "*")) or (line and line[0].isdigit()):
                    items.append(re.sub(r"^[•\-√*\d\.\s]+", "", line).strip())
                    if len(items) >= limit:
                        break
                elif any(kw in line.lower() for kw in
                         ["treatment", "prevention", "action", "recovery", "note",
                          "section", "===", "---"]):
                    break
        return items

    actions    = _bullets("Immediate Actions", 3)
    treatments = _bullets("Treatments", 2)

    parts = [
        "🌿 *AGRI DOCTOR – CROP HEALTH ADVISORY*",
        f"📅 {time.strftime('%d %b %Y, %I:%M %p')}",
        "",
    ]
    if disease:   parts += [f"🌱 *Disease:* {disease}"]
    if conf:      parts += [f"📊 *Confidence:* {conf}"]
    if severity:  parts += [f"⚠️ *Severity:* {severity}"]
    if summary:   parts += ["", f"📋 {summary[:200]}"]
    if actions:
        parts += ["", "🚨 *Immediate Actions:*"]
        parts += [f"  • {a}" for a in actions]
    if treatments:
        parts += ["", "💊 *Treatment:*"]
        parts += [f"  • {t}" for t in treatments]
    if recovery:  parts += ["", f"⏳ *Recovery:* {recovery}"]
    parts += [
        "",
        "⚠️ AI advisory — consult a qualified agricultural expert.",
        "— Agri Doctor AI 🌾",
    ]

    msg = "\n".join(parts)
    # Hard-trim if still too long
    if len(msg) > _PYWHATKIT_MAX_CHARS:
        msg = msg[:_PYWHATKIT_MAX_CHARS - 40] + "\n\n… [see full report in app]"
    return msg


# ─────────────────────────────────────────────────────────────────────────────
#  Method 1: Fully automatic send via pyautogui (reliable focus + Enter)
# ─────────────────────────────────────────────────────────────────────────────

def _send_via_auto_whatsapp_web(
    phone_number: str,
    message: str,
    wait_time: int = 20,
    progress_callback=None,
) -> tuple:
    """
    Fully automatic WhatsApp send:
      1. Build a compact advisory from the raw report.
      2. Open web.whatsapp.com/send?phone=...&text=... in the default browser.
         WhatsApp Web pre-fills the message box from the URL.
      3. Wait for the page to fully load (wait_time seconds).
      4. Click on the WhatsApp message input box area (bottom of screen)
         to ensure focus, then press Enter — message is sent automatically.

    Works on macOS and Linux desktop.  No Selenium or API key required.
    """
    ok, phone, _ = get_whatsapp_urls(phone_number, message)
    if not ok:
        return False, phone

    # Build a compact advisory from the raw report
    compact_msg = _build_compact_advisory(message)
    logger.info("[WA-auto] Compact advisory: %d chars → %s", len(compact_msg), phone)

    # Build the WhatsApp Web URL with pre-filled text
    phone_digits = phone.lstrip("+")
    wa_url = (
        f"https://web.whatsapp.com/send/?phone={phone_digits}"
        f"&text={urllib.parse.quote(compact_msg, safe='')}"
        f"&app_absent=0"
    )

    def _cb(msg_text: str):
        logger.info("[WA-auto] %s", msg_text)
        if progress_callback:
            try:
                progress_callback(msg_text)
            except Exception:
                pass

    # ── Step 1: Open browser ─────────────────────────────────────────────────
    _cb(f"Opening WhatsApp Web for {phone}…")
    try:
        webbrowser.open(wa_url)
    except Exception as exc:
        return False, f"Could not open browser: {exc}"

    if not PYAUTOGUI_AVAILABLE:
        return (
            True,
            f"✅ WhatsApp Web opened for {phone}. "
            "Message is pre-filled — tap Send in the browser.",
        )

    # ── Step 2: Wait for WhatsApp Web to fully load ──────────────────────────
    _cb(f"Waiting {wait_time}s for WhatsApp Web to load…")
    for i in range(wait_time):
        time.sleep(1)
        if i == wait_time // 2:
            _cb(f"Still loading… ({wait_time - i}s remaining)")

    # ── Step 3: Bring browser window to front and focus message box ──────────
    # Strategy: click near the bottom-centre of the screen where WhatsApp Web
    # always renders the message input box, then press Enter.
    _cb("Clicking message box and sending…")
    try:
        import platform
        screen_w, screen_h = pyautogui.size()

        # Click center of screen first to bring window to front
        pyautogui.click(screen_w // 2, screen_h // 2)
        time.sleep(0.5)

        # WhatsApp Web message input is always in the bottom portion of the page.
        # Click at approximately 92% of screen height, 50% width.
        input_x = screen_w // 2
        input_y = int(screen_h * 0.92)
        pyautogui.click(input_x, input_y)
        time.sleep(0.8)

        # Press Enter to send the pre-filled message
        pyautogui.press("enter")
        time.sleep(1.0)

        logger.info("[WA-auto] ✅ Enter pressed — message sent to %s", phone)
        _cb(f"✅ Message sent to {phone}!")
        return True, f"✅ Report sent automatically to {phone} via WhatsApp Web."

    except Exception as exc:
        logger.warning("[WA-auto] pyautogui failed: %s", exc)
        return (
            True,
            f"✅ WhatsApp Web opened for {phone}. "
            "Message is pre-filled — tap Send in the browser.",
        )


# ─────────────────────────────────────────────────────────────────────────────
#  Method 2: Manual WhatsApp Web (pre-fills only — user clicks Send)
# ─────────────────────────────────────────────────────────────────────────────

def _send_via_webbrowser(phone_number: str, message: str) -> tuple:
    """
    Open WhatsApp Web pre-filled with the message. User clicks Send.
    Labelled as 'Prepared' — not 'Sent'.
    """
    ok, phone, urls = get_whatsapp_urls(phone_number, message)
    if not ok:
        return False, phone

    web_url = urls["web_url"]
    try:
        webbrowser.open(web_url)
        return (
            True,
            f"✅ WhatsApp Web opened for {phone}. "
            "Review the pre-filled message in your browser and tap *Send*.",
        )
    except Exception as exc:
        logger.error("webbrowser.open failed: %s", exc)
        return False, f"Could not open browser: {exc}"


def _send_via_pywhatkit(phone_number: str, message: str) -> tuple:
    """Alias: auto WhatsApp Web sending via pyautogui."""
    return _send_via_auto_whatsapp_web(phone_number, message, wait_time=8)


# ─────────────────────────────────────────────────────────────────────────────
#  Method 3: Twilio WhatsApp API
# ─────────────────────────────────────────────────────────────────────────────

def _send_via_twilio(
    phone_number: str,
    message: str,
    account_sid: str,
    auth_token: str,
    from_number: str,
) -> tuple:
    if not account_sid or not auth_token:
        return False, "Twilio Account SID and Auth Token are required."
    if not from_number:
        return False, "Twilio From number is required (e.g. whatsapp:+14155238886)."

    ok, phone = _clean_phone(phone_number)
    if not ok:
        return False, phone

    to_wa   = phone      if phone.startswith("whatsapp:")      else f"whatsapp:{phone}"
    from_wa = from_number if from_number.startswith("whatsapp:") else f"whatsapp:{from_number}"
    text    = _truncate(message)
    url     = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"

    try:
        resp = requests.post(
            url,
            data={"From": from_wa, "To": to_wa, "Body": text},
            auth=(account_sid, auth_token),
            timeout=30,
        )
        if resp.status_code in (200, 201):
            return True, f"✅ Sent via Twilio. SID: {resp.json().get('sid', '?')}"
        detail = resp.json().get("message", resp.text[:200])
        return False, f"Twilio API error {resp.status_code}: {detail}"
    except requests.exceptions.ConnectionError:
        return False, "Network error — could not reach Twilio API."
    except requests.exceptions.Timeout:
        return False, "Twilio API timed out after 30 s."
    except Exception as exc:
        logger.error("Twilio error: %s", exc)
        return False, f"Unexpected error: {exc}"


# ─────────────────────────────────────────────────────────────────────────────
#  Method 4: WhatsApp Business Cloud API (Meta Graph API)
# ─────────────────────────────────────────────────────────────────────────────

META_GRAPH_VERSION = "v19.0"

def send_via_whatsapp_cloud_api(
    phone_number: str,
    message: str,
    access_token: str = "",
    phone_number_id: str = "",
) -> tuple:
    """
    Send a WhatsApp text message via the Meta WhatsApp Business Cloud API.

    Parameters
    ----------
    phone_number    : recipient number (E.164 or 10-digit Indian)
    message         : plain text message (≤ 4096 chars; split before calling)
    access_token    : META_WA_ACCESS_TOKEN env var
    phone_number_id : META_WA_PHONE_NUMBER_ID env var

    Returns
    -------
    (success: bool, message_id_or_error: str)
    """
    if not access_token:
        access_token = os.environ.get("WHATSAPP_ACCESS_TOKEN", "")
    if not phone_number_id:
        phone_number_id = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")

    if not access_token:
        return False, "WHATSAPP_ACCESS_TOKEN is not set."
    if not phone_number_id:
        return False, "WHATSAPP_PHONE_NUMBER_ID is not set."

    ok, phone = _clean_phone(phone_number)
    if not ok:
        return False, phone

    phone_e164 = phone.lstrip("+")  # Meta API expects digits only, no +

    url = f"https://graph.facebook.com/{META_GRAPH_VERSION}/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": phone_e164,
        "type": "text",
        "text": {
            "preview_url": False,
            "body": message[:4096],
        },
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=30)
        data = resp.json()
        if resp.status_code == 200 and "messages" in data:
            msg_id = data["messages"][0].get("id", "")
            logger.info("Meta Cloud API: sent to %s, msg_id=%s", phone, msg_id)
            return True, msg_id
        error_info = data.get("error", {})
        err_msg = error_info.get("message", resp.text[:200])
        err_code = error_info.get("code", resp.status_code)
        logger.error("Meta Cloud API error %s: %s", err_code, err_msg)
        return False, f"Meta API error {err_code}: {err_msg}"
    except requests.exceptions.ConnectionError:
        return False, "Network error — could not reach Meta Graph API."
    except requests.exceptions.Timeout:
        return False, "Meta Graph API timed out after 30 s."
    except Exception as exc:
        logger.error("Meta Cloud API unexpected error: %s", exc)
        return False, f"Unexpected error: {exc}"


def send_whatsapp_multi_part(
    phone_number: str,
    message_parts: list,
    access_token: str = "",
    phone_number_id: str = "",
    delay_between_parts: float = 1.5,
) -> tuple:
    """
    Send multiple message parts in order via the Cloud API.
    Returns (all_ok: bool, results: list[dict])
    where each dict has {part: int, total: int, ok: bool, msg_id: str, error: str}.
    """
    results = []
    all_ok = True
    for i, part in enumerate(message_parts, 1):
        ok, result = send_via_whatsapp_cloud_api(
            phone_number, part, access_token, phone_number_id,
        )
        results.append({
            "part": i,
            "total": len(message_parts),
            "ok": ok,
            "msg_id": result if ok else "",
            "error": "" if ok else result,
        })
        if not ok:
            all_ok = False
            logger.error("Part %d/%d failed: %s", i, len(message_parts), result)
            break  # Do not send further parts if one fails
        if i < len(message_parts):
            time.sleep(delay_between_parts)

    return all_ok, results


# ─────────────────────────────────────────────────────────────────────────────
#  Public entry-point
# ─────────────────────────────────────────────────────────────────────────────

def send_whatsapp_report(
    phone_number: str,
    report_text: str,
    method: str = "webbrowser",
    wait_time: int = 0,
    progress_callback=None,
    twilio_sid: str = "",
    twilio_token: str = "",
    twilio_from: str = "whatsapp:+14155238886",
    wa_access_token: str = "",
    wa_phone_number_id: str = "",
    report_id: str = "",
    report_title: str = "",
) -> tuple:
    """
    Send an Agri Doctor advisory report via WhatsApp.

    Parameters
    ----------
    phone_number        : str  e.g. +919876543210 or 9876543210
    report_text         : str  Full report text (formatted before sending)
    method              : str  "webbrowser" | "auto" | "twilio" | "meta"
    wait_time           : int  Used if method="auto"
    progress_callback   : func Optional callback(sec, total) for UI progress
    twilio_*            : str  Required only when method="twilio"
    wa_access_token     : str  Required when method="meta"
    wa_phone_number_id  : str  Required when method="meta"
    report_id           : str  Unique report ID for multi-part messages
    report_title        : str  Report title for the message header

    Returns
    -------
    (success: bool, message_or_id: str)
    """
    m = method.strip().lower()

    if m == "meta":
        # Format full report as WhatsApp text
        full_msg = format_report_as_whatsapp_text(
            report_text, report_title=report_title, report_id=report_id,
        )
        parts = split_message_into_parts(full_msg, report_id=report_id)
        if len(parts) == 1:
            return send_via_whatsapp_cloud_api(
                phone_number, parts[0], wa_access_token, wa_phone_number_id,
            )
        all_ok, results = send_whatsapp_multi_part(
            phone_number, parts, wa_access_token, wa_phone_number_id,
        )
        if all_ok:
            ids = ", ".join(r["msg_id"] for r in results if r["msg_id"])
            return True, f"✅ Sent {len(parts)} parts. Message IDs: {ids}"
        failed = [r for r in results if not r["ok"]]
        return False, f"Failed at part {failed[0]['part']}/{len(parts)}: {failed[0]['error']}"

    elif m == "twilio":
        # Format full report, then split and send
        full_msg = format_report_as_whatsapp_text(
            report_text, report_title=report_title, report_id=report_id,
        )
        return _send_via_twilio(
            phone_number, full_msg, twilio_sid, twilio_token, twilio_from,
        )

    elif m in ("auto", "auto-send") and wait_time > 0:
        return _send_via_auto_whatsapp_web(
            phone_number, report_text, wait_time, progress_callback,
        )

    else:
        # Default: open WhatsApp Web with pre-filled message (user clicks Send)
        return _send_via_webbrowser(phone_number, report_text)
