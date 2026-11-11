"""
agents/whatsapp_agent.py — WhatsApp Report Delivery Agent for Agri Doctor.

Orchestrates the full workflow:
  Receive Request → Validate Number → Retrieve Report → Format Full Report
  → Send via WhatsApp Web (Selenium) / Meta Cloud API / Twilio → Track Status

Sending priority (auto mode)
----------------------------
1. WhatsApp Web (Selenium) — always available, uses Chrome, zero API cost
2. Meta WhatsApp Business Cloud API — if WHATSAPP_ACCESS_TOKEN is set
3. Twilio WhatsApp API — if TWILIO_ACCOUNT_SID is set
4. WhatsApp Web URL (manual) — fallback, user clicks Send in browser

Architecture
------------
WhatsAppNumberValidator      validates/normalises phone numbers
ReportRetrievalService       fetches the latest diagnosis report from DB
WhatsAppMessageFormatter     converts full report to structured WhatsApp text
WhatsAppSender               sends via Selenium Web / Meta API / Twilio / URL
WhatsAppDeliveryTracker      persists delivery state in SQLite
WhatsAppRetryHandler         safe retry with limits
WhatsAppReportAgent          orchestrator — main entry point
"""

import logging
import os
import re
import sys
import uuid
from datetime import datetime
from typing import Optional, Dict, Tuple, Any, List

logger = logging.getLogger(__name__)

# ── Ensure venv site-packages are on path ─────────────────────────────────────
_venv_site = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "venv", "lib", "python3.9", "site-packages",
)
if os.path.isdir(_venv_site) and _venv_site not in sys.path:
    sys.path.insert(0, _venv_site)

from database import (
    get_recent_diagnoses,
    save_wa_delivery,
    update_wa_delivery_status,
    get_wa_delivery,
    get_recent_wa_deliveries,
)
from services.whatsapp_service import (
    _clean_phone,
    get_whatsapp_urls,
    format_report_as_whatsapp_text,
    split_message_into_parts,
    send_via_whatsapp_cloud_api,
    send_whatsapp_multi_part,
    _send_via_twilio,
    _truncate,
    PREFERRED_PART_SIZE,
)

# WhatsApp Web automation via Selenium (primary automatic method)
try:
    from services.whatsapp_web_sender import (
        push_report_to_whatsapp_web,
        SELENIUM_AVAILABLE,
    )
except ImportError:
    SELENIUM_AVAILABLE = False
    def push_report_to_whatsapp_web(*a, **kw):
        return False, "whatsapp_web_sender module not found."


# ══════════════════════════════════════════════════════════════════════════════
#  Status constants
# ══════════════════════════════════════════════════════════════════════════════

AGENT_NAME         = "WhatsApp Report Delivery Agent"

STATUS_IDLE        = "idle"
STATUS_PROCESSING  = "processing"
STATUS_VALIDATING  = "validating"
STATUS_PREPARING   = "preparing"
STATUS_READY       = "ready"       # URL prepared — user must click Send
STATUS_PREPARED    = "prepared"    # Alias for ready
STATUS_CONNECTING  = "connecting"
STATUS_SENDING     = "sending"
STATUS_SENT        = "sent"        # API confirmed send
STATUS_DELIVERED   = "delivered"   # Delivery receipt received
STATUS_READ        = "read"        # Read receipt received
STATUS_FAILED      = "failed"


# ══════════════════════════════════════════════════════════════════════════════
#  WhatsAppNumberValidator
# ══════════════════════════════════════════════════════════════════════════════

class WhatsAppNumberValidator:
    """Validates and normalises WhatsApp phone numbers."""

    def validate(self, phone: str) -> Tuple[bool, str, str]:
        """
        Returns (valid: bool, normalised: str, error_message: str).
        """
        if not phone or not phone.strip():
            return False, "", "Phone number is empty."
        ok, normalised = _clean_phone(phone)
        if not ok:
            return False, "", normalised
        return True, normalised, ""

    def mask(self, normalised: str) -> str:
        """Return a masked version: +91 ****3210"""
        if len(normalised) < 5:
            return "***"
        visible = normalised[-4:]
        prefix  = normalised[:3]
        return f"{prefix} ****{visible}"


# ══════════════════════════════════════════════════════════════════════════════
#  ReportRetrievalService
# ══════════════════════════════════════════════════════════════════════════════

class ReportRetrievalService:
    """
    Retrieves the latest completed diagnosis report.
    Accepts an explicit report_text, or falls back to the most recent DB record.
    """

    def retrieve(
        self,
        report_text: Optional[str] = None,
        diagnosis_id: Optional[int] = None,
        session_id: Optional[str] = None,
    ) -> Tuple[bool, str, str]:
        """Returns (success: bool, report_text: str, report_title: str)."""
        if report_text and report_text.strip():
            lines = [l.strip() for l in report_text.split("\n") if l.strip()]
            title = lines[0][:80] if lines else "Crop Health Advisory"
            title = re.sub(r"^[*#🌿🔬=\-\s]+", "", title).strip() or "Crop Health Advisory"
            return True, report_text, title

        try:
            records = get_recent_diagnoses(limit=5)
            if not records:
                return False, "", "No diagnosis records found in database."

            target = None
            if diagnosis_id:
                target = next((r for r in records if r.get("id") == diagnosis_id), None)
            if not target and session_id:
                target = next((r for r in records if r.get("session_id") == session_id), None)
            if not target:
                target = records[0]

            combined = target.get("combined_report", "")
            if not combined:
                return False, "", "Report text is empty in the database record."

            disease = target.get("suspected_disease", "Crop Health")
            created = target.get("created_at", "")[:10]
            title   = f"{disease} Advisory — {created}"
            return True, combined, title
        except Exception as exc:
            logger.error("ReportRetrievalService error: %s", exc)
            return False, "", f"Database error: {exc}"


# ══════════════════════════════════════════════════════════════════════════════
#  WhatsAppMessageFormatter
# ══════════════════════════════════════════════════════════════════════════════

class WhatsAppMessageFormatter:
    """
    Converts the full Agri Doctor report into structured WhatsApp text.
    Uses the centralised format_report_as_whatsapp_text function.
    Never invents content for missing sections.
    """

    def format(
        self,
        report_text: str,
        report_title: str = "",
        delivery_id: str = "",
    ) -> Tuple[str, List[str]]:
        """
        Returns (full_message: str, parts: list[str]).
        Parts will be a list of one item when the message fits in a single send.
        """
        full_msg = format_report_as_whatsapp_text(
            report_text,
            report_title=report_title,
            report_id=delivery_id,
        )
        parts = split_message_into_parts(full_msg, report_id=delivery_id)
        return full_msg, parts


# ══════════════════════════════════════════════════════════════════════════════
#  WhatsAppSender
# ══════════════════════════════════════════════════════════════════════════════

class WhatsAppSender:
    """
    Sends WhatsApp messages using the best available method:

      Priority (auto mode):
        1. WhatsApp Web via Selenium  — Chrome automation, zero API cost
        2. Meta WhatsApp Business Cloud API — if WHATSAPP_ACCESS_TOKEN is set
        3. Twilio WhatsApp API — if TWILIO_ACCOUNT_SID is set
        4. WhatsApp Web URL — fallback, opens browser, user must click Send

    Only methods 1–3 are labelled Sent.
    Method 4 is labelled Prepared.
    """

    def detect_best_method(self) -> str:
        """
        Auto-detect best sending method.
        Priority: selenium > meta > twilio > webbrowser
        """
        if SELENIUM_AVAILABLE:
            return "selenium"
        if os.environ.get("WHATSAPP_ACCESS_TOKEN") and os.environ.get("WHATSAPP_PHONE_NUMBER_ID"):
            return "meta"
        if os.environ.get("TWILIO_ACCOUNT_SID") and os.environ.get("TWILIO_AUTH_TOKEN"):
            return "twilio"
        return "webbrowser"

    def send(
        self,
        phone_normalised: str,
        message_parts: List[str],
        full_message: str,
        method: str = "auto",
        twilio_sid: str = "",
        twilio_token: str = "",
        twilio_from: str = "",
        wa_access_token: str = "",
        wa_phone_number_id: str = "",
        chrome_profile: str = "",
        progress_callback=None,
    ) -> Dict[str, Any]:
        """
        Send message(s) to the given phone number.

        Returns
        -------
        {
          "method":      str,    # which method was actually used
          "status":      str,    # STATUS_* constant
          "sent":        bool,   # True only if actually sent (selenium/meta/twilio)
          "prepared":    bool,   # True if URL was prepared (webbrowser fallback)
          "wa_url":      str,    # WhatsApp Web URL (webbrowser fallback)
          "msg_ids":     list,   # message IDs from API, if available
          "parts_sent":  int,
          "parts_total": int,
          "error":       str,
        }
        """
        if method == "auto":
            method = self.detect_best_method()

        result_base = {
            "method":      method,
            "status":      STATUS_FAILED,
            "sent":        False,
            "prepared":    False,
            "wa_url":      "",
            "msg_ids":     [],
            "parts_sent":  0,
            "parts_total": len(message_parts),
            "error":       "",
        }

        # ── 1. WhatsApp Web via Selenium (primary automatic method) ───────────
        if method in ("selenium", "whatsapp-web", "wa-web"):
            if not SELENIUM_AVAILABLE:
                result_base["error"] = (
                    "Selenium is not installed. "
                    "Run: pip install selenium"
                )
                return result_base

            ok, detail = push_report_to_whatsapp_web(
                phone_number=phone_normalised,
                message_parts=message_parts,
                chrome_profile=chrome_profile,
                progress_callback=progress_callback,
            )
            if ok:
                return {**result_base,
                        "method":     "selenium",
                        "status":     STATUS_SENT,
                        "sent":       True,
                        "parts_sent": len(message_parts)}
            # If selenium failed, build the wa.me URL as fallback
            _, _, urls = get_whatsapp_urls(phone_normalised, full_message)
            wa_url = urls.get("wa_me", urls.get("web_url", "")) if urls else ""
            return {**result_base,
                    "method":   "selenium",
                    "status":   STATUS_FAILED,
                    "wa_url":   wa_url,
                    "error":    detail}

        # ── 2. Meta Cloud API ──────────────────────────────────────────────────
        elif method == "meta":
            token = wa_access_token or os.environ.get("WHATSAPP_ACCESS_TOKEN", "")
            ph_id = wa_phone_number_id or os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")

            if not token or not ph_id:
                result_base["error"] = (
                    "WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID must be set. "
                    "Configure them in ⚙️ Settings → WhatsApp."
                )
                return result_base

            if len(message_parts) == 1:
                ok, msg_id = send_via_whatsapp_cloud_api(
                    phone_normalised, message_parts[0], token, ph_id,
                )
                if ok:
                    return {**result_base,
                            "status": STATUS_SENT, "sent": True,
                            "msg_ids": [msg_id], "parts_sent": 1}
                return {**result_base, "error": msg_id}
            else:
                all_ok, results = send_whatsapp_multi_part(
                    phone_normalised, message_parts, token, ph_id,
                )
                sent_count = sum(1 for r in results if r["ok"])
                ids = [r["msg_id"] for r in results if r["ok"]]
                if all_ok:
                    return {**result_base,
                            "status": STATUS_SENT, "sent": True,
                            "msg_ids": ids, "parts_sent": sent_count}
                failed = [r for r in results if not r["ok"]]
                return {**result_base,
                        "parts_sent": sent_count, "msg_ids": ids,
                        "error": f"Part {failed[0]['part']}/{len(message_parts)}: {failed[0]['error']}"}

        # ── 3. Twilio ──────────────────────────────────────────────────────────
        elif method == "twilio":
            sid    = twilio_sid   or os.environ.get("TWILIO_ACCOUNT_SID", "")
            token_ = twilio_token or os.environ.get("TWILIO_AUTH_TOKEN", "")
            from_  = twilio_from  or os.environ.get("TWILIO_FROM_NUMBER", "whatsapp:+14155238886")
            ok, msg = _send_via_twilio(
                phone_normalised, message_parts[0], sid, token_, from_,
            )
            if ok:
                return {**result_base,
                        "status": STATUS_SENT, "sent": True,
                        "msg_ids": [msg], "parts_sent": 1}
            return {**result_base, "error": msg}

        # ── 4. WhatsApp Web URL (manual fallback — user clicks Send) ──────────
        else:
            ok, _, urls = get_whatsapp_urls(phone_normalised, full_message)
            if not ok:
                return {**result_base, "error": f"Could not build WhatsApp URL: {urls}"}
            # Use the official wa.me click-to-chat URL as the primary link
            return {**result_base,
                    "status":   STATUS_PREPARED,
                    "prepared": True,
                    "wa_url":   urls["wa_me"]}


# ══════════════════════════════════════════════════════════════════════════════
#  WhatsAppDeliveryTracker
# ══════════════════════════════════════════════════════════════════════════════

class WhatsAppDeliveryTracker:
    """Persists and retrieves WhatsApp delivery records from SQLite."""

    def create(
        self,
        delivery_id: str,
        session_id: str,
        phone_raw: str,
        phone_normalised: str,
        report_title: str,
        message_text: str,
        wa_url: str,
        diagnosis_id: Optional[int] = None,
    ) -> None:
        save_wa_delivery(
            delivery_id=delivery_id,
            session_id=session_id,
            phone_raw=phone_raw,
            phone_normalized=phone_normalised,
            report_title=report_title,
            message_text=message_text,
            wa_url=wa_url,
            diagnosis_id=diagnosis_id,
            pdf_path="",
            status="processing",
        )

    def update(
        self,
        delivery_id: str,
        status: str,
        error_message: Optional[str] = None,
        wa_url: Optional[str] = None,
    ) -> None:
        update_wa_delivery_status(
            delivery_id=delivery_id,
            status=status,
            error_message=error_message,
            wa_url=wa_url,
        )

    def get(self, delivery_id: str) -> Optional[Dict]:
        return get_wa_delivery(delivery_id)

    def recent(self, limit: int = 10) -> list:
        return get_recent_wa_deliveries(limit=limit)


# ══════════════════════════════════════════════════════════════════════════════
#  WhatsAppRetryHandler
# ══════════════════════════════════════════════════════════════════════════════

class WhatsAppRetryHandler:
    """Checks whether a delivery is eligible for retry."""

    MAX_ATTEMPTS = 3

    def can_retry(self, delivery_id: str) -> Tuple[bool, str]:
        record = get_wa_delivery(delivery_id)
        if not record:
            return False, "Delivery record not found."
        status   = record.get("status", "")
        attempts = record.get("attempt_count", 0)
        if status in ("sent", "delivered", "read"):
            return False, f"Already {status} — will not retry."
        if attempts >= self.MAX_ATTEMPTS:
            return False, f"Max retry attempts ({self.MAX_ATTEMPTS}) reached."
        return True, f"Attempt {attempts + 1} of {self.MAX_ATTEMPTS} allowed."


# ══════════════════════════════════════════════════════════════════════════════
#  WhatsAppReportAgent — Main Orchestrator
# ══════════════════════════════════════════════════════════════════════════════

class WhatsAppReportAgent:
    """
    Orchestrates the full WhatsApp report delivery workflow.

    Workflow
    --------
    1. Validate Number
    2. Retrieve Report from DB or session
    3. Format Report → structured WhatsApp text (full report, not truncated)
    4. Split into parts if needed
    5. Send via best available method (Meta API → Twilio → WhatsApp Web URL)
    6. Persist delivery record and return result
    """

    def __init__(self):
        self.validator  = WhatsAppNumberValidator()
        self.retrieval  = ReportRetrievalService()
        self.formatter  = WhatsAppMessageFormatter()
        self.sender     = WhatsAppSender()
        self.tracker    = WhatsAppDeliveryTracker()
        self.retry_handler = WhatsAppRetryHandler()

    # ── Public entry point ────────────────────────────────────────────────────

    def run(
        self,
        phone: str,
        report_text: str = "",
        report_title: str = "",
        session_id: str = "",
        diagnosis_id: Optional[int] = None,
        recipient_name: str = "",
        method: str = "auto",
        twilio_sid: str = "",
        twilio_token: str = "",
        twilio_from: str = "",
        wa_access_token: str = "",
        wa_phone_number_id: str = "",
        chrome_profile: str = "",
        progress_callback=None,
    ) -> Dict[str, Any]:
        """
        Execute the full delivery workflow.

        Returns
        -------
        {
          "success":      bool,
          "delivery_id":  str,
          "status":       str,
          "wa_url":       str,
          "phone":        str,
          "phone_masked": str,
          "report_title": str,
          "msg_ids":      list[str],
          "parts_total":  int,
          "parts_sent":   int,
          "method_used":  str,
          "sent":         bool,
          "prepared":     bool,
          "error":        str | None,
          "steps":        list[dict],
        }
        """
        delivery_id = str(uuid.uuid4())[:12]
        steps: list = []
        session_id  = session_id or str(uuid.uuid4())

        def _step(name: str, ok: bool, detail: str = ""):
            steps.append({
                "name": name, "ok": ok, "detail": detail,
                "time": datetime.now().strftime("%H:%M:%S"),
            })
            logger.info("[%s] %s: %s%s", delivery_id, name,
                        "✅" if ok else "❌", f" — {detail}" if detail else "")

        def _fail(msg: str, error_msg: str = "") -> Dict[str, Any]:
            try:
                self.tracker.update(delivery_id, STATUS_FAILED, error_message=error_msg or msg)
            except Exception:
                pass
            return {
                "success": False, "delivery_id": delivery_id,
                "status": STATUS_FAILED, "wa_url": "", "phone": "",
                "phone_masked": "", "report_title": report_title,
                "msg_ids": [], "parts_total": 0, "parts_sent": 0,
                "method_used": "", "sent": False, "prepared": False,
                "error": msg, "steps": steps,
            }

        # ── Step 1: Validate Number ───────────────────────────────────────────
        valid, phone_norm, err = self.validator.validate(phone)
        _step("Validate Number", valid, err or phone_norm)
        if not valid:
            try:
                self.tracker.create(
                    delivery_id, session_id, phone, "", report_title or "Advisory",
                    "", "", diagnosis_id=diagnosis_id,
                )
                self.tracker.update(delivery_id, STATUS_FAILED, error_message=err)
            except Exception:
                pass
            return _fail(f"Invalid phone number: {err}")

        phone_masked = self.validator.mask(phone_norm)

        # ── Step 2: Retrieve Report ───────────────────────────────────────────
        rep_ok, rep_text, rep_title = self.retrieval.retrieve(
            report_text=report_text,
            diagnosis_id=diagnosis_id,
            session_id=session_id,
        )
        _step("Retrieve Report", rep_ok, rep_title)
        if not rep_ok:
            try:
                self.tracker.create(
                    delivery_id, session_id, phone, phone_norm,
                    report_title or "Advisory", "", "", diagnosis_id=diagnosis_id,
                )
                self.tracker.update(delivery_id, STATUS_FAILED, error_message=rep_title)
            except Exception:
                pass
            return _fail(f"Could not retrieve report: {rep_title}")

        final_title = report_title or rep_title

        # ── Step 3: Format Report → WhatsApp Text ────────────────────────────
        full_msg, msg_parts = self.formatter.format(
            rep_text, report_title=final_title, delivery_id=delivery_id,
        )
        _step(
            "Format Report",
            True,
            f"{len(full_msg)} chars → {len(msg_parts)} part(s)",
        )

        # ── Step 4: Persist Delivery Record ──────────────────────────────────
        try:
            self.tracker.create(
                delivery_id=delivery_id,
                session_id=session_id,
                phone_raw=phone,
                phone_normalised=phone_norm,
                report_title=final_title,
                message_text=full_msg[:2000],  # Store preview; don't store 16KB in DB
                wa_url="",
                diagnosis_id=diagnosis_id,
            )
            _step("Create Delivery Record", True, delivery_id)
        except Exception as db_exc:
            logger.warning("Tracker DB error (non-fatal): %s", db_exc)
            _step("Create Delivery Record", False, str(db_exc))

        # ── Step 5: Send ──────────────────────────────────────────────────────
        _step("Connecting", True, f"Method: {method}")
        send_result = self.sender.send(
            phone_normalised=phone_norm,
            message_parts=msg_parts,
            full_message=full_msg,
            method=method,
            twilio_sid=twilio_sid,
            twilio_token=twilio_token,
            twilio_from=twilio_from,
            wa_access_token=wa_access_token,
            wa_phone_number_id=wa_phone_number_id,
            chrome_profile=chrome_profile,
            progress_callback=progress_callback,
        )

        final_status = send_result["status"]
        wa_url       = send_result.get("wa_url", "")
        method_used  = send_result.get("method", method)
        send_ok      = send_result.get("sent", False) or send_result.get("prepared", False)
        send_err     = send_result.get("error", "")
        msg_ids      = send_result.get("msg_ids", [])
        parts_sent   = send_result.get("parts_sent", 0)
        parts_total  = send_result.get("parts_total", len(msg_parts))

        if send_result.get("sent"):
            detail = f"Sent {parts_sent}/{parts_total} part(s) · IDs: {', '.join(msg_ids) or '—'}"
            _step("Send Message", True, detail)
        elif send_result.get("prepared"):
            _step("Prepare WhatsApp URL", True, wa_url[:60] + "…" if wa_url else "")
        else:
            _step("Send Message", False, send_err)

        # ── Step 6: Update Delivery Record ────────────────────────────────────
        try:
            self.tracker.update(
                delivery_id,
                final_status,
                error_message=send_err or None,
                wa_url=wa_url or None,
            )
        except Exception as db_exc:
            logger.warning("Tracker update error (non-fatal): %s", db_exc)

        return {
            "success":      send_ok,
            "delivery_id":  delivery_id,
            "status":       final_status,
            "wa_url":       wa_url,
            "phone":        phone_norm,
            "phone_masked": phone_masked,
            "report_title": final_title,
            "msg_ids":      msg_ids,
            "parts_total":  parts_total,
            "parts_sent":   parts_sent,
            "method_used":  method_used,
            "sent":         send_result.get("sent", False),
            "prepared":     send_result.get("prepared", False),
            "error":        send_err or None,
            "steps":        steps,
        }

    # ── Retry ─────────────────────────────────────────────────────────────────

    def retry(self, delivery_id: str) -> Dict[str, Any]:
        """Re-trigger delivery for a failed record using stored data."""
        can, reason = self.retry_handler.can_retry(delivery_id)
        if not can:
            return {
                "success": False, "error": reason, "delivery_id": delivery_id,
                "status": STATUS_FAILED, "wa_url": "", "steps": [],
                "msg_ids": [], "parts_total": 0, "parts_sent": 0,
                "method_used": "", "sent": False, "prepared": False,
            }

        record = self.tracker.get(delivery_id)
        if not record:
            return {
                "success": False, "error": "Record not found.",
                "delivery_id": delivery_id, "status": STATUS_FAILED,
                "wa_url": "", "steps": [], "msg_ids": [], "parts_total": 0,
                "parts_sent": 0, "method_used": "", "sent": False, "prepared": False,
            }

        return self.run(
            phone=record.get("phone_raw", ""),
            report_text=record.get("message_text", ""),
            report_title=record.get("report_title", ""),
            session_id=record.get("session_id", ""),
        )

    # ── History ───────────────────────────────────────────────────────────────

    def get_recent_deliveries(self, limit: int = 10) -> list:
        """Return recent delivery records for the dashboard."""
        return self.tracker.recent(limit=limit)
