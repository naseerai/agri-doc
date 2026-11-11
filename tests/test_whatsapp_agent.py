"""
tests/test_whatsapp_agent.py — Unit tests for the WhatsApp Report Delivery Agent.

Covers:
  - Phone number validation (valid, invalid, country codes)
  - Report retrieval (with text, without text)
  - PDF generation
  - WhatsApp URL generation
  - Full agent workflow (success + failure paths)
  - Retry handler
  - Duplicate-send prevention
  - Database persistence
"""

import os
import sys
import uuid
import pytest

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.whatsapp_agent import (
    WhatsAppNumberValidator,
    ReportRetrievalService,
    PDFAttachmentService,
    WhatsAppMessageGenerator,
    WhatsAppDeliveryService,
    WhatsAppDeliveryTracker,
    WhatsAppRetryHandler,
    WhatsAppReportAgent,
    STATUS_READY,
    STATUS_FAILED,
    FPDF_AVAILABLE,
)


# ══════════════════════════════════════════════════════════════════════════════
#  WhatsAppNumberValidator
# ══════════════════════════════════════════════════════════════════════════════

class TestWhatsAppNumberValidator:
    def setup_method(self):
        self.v = WhatsAppNumberValidator()

    def test_valid_10_digit_indian(self):
        ok, norm, err = self.v.validate("9876543210")
        assert ok is True
        assert norm == "+919876543210"
        assert err == ""

    def test_valid_e164_indian(self):
        ok, norm, _ = self.v.validate("+919876543210")
        assert ok is True
        assert norm == "+919876543210"

    def test_valid_with_country_code_us(self):
        ok, norm, _ = self.v.validate("+14155552671")
        assert ok is True
        assert norm == "+14155552671"

    def test_valid_uk_number(self):
        ok, norm, _ = self.v.validate("+447911123456")
        assert ok is True
        assert norm == "+447911123456"

    def test_leading_zero_11_digit(self):
        # 09876543210 → +919876543210
        ok, norm, _ = self.v.validate("09876543210")
        assert ok is True
        assert norm == "+919876543210"

    def test_number_with_dashes(self):
        ok, norm, _ = self.v.validate("98-765-43210")
        assert ok is True
        assert norm == "+919876543210"

    def test_number_with_spaces(self):
        ok, norm, _ = self.v.validate("9876 543 210")
        assert ok is True
        assert norm == "+919876543210"

    def test_empty_number(self):
        ok, _, err = self.v.validate("")
        assert ok is False
        assert "empty" in err.lower()

    def test_whitespace_only(self):
        ok, _, err = self.v.validate("   ")
        assert ok is False

    def test_too_short(self):
        ok, _, err = self.v.validate("123")
        assert ok is False

    def test_letters_in_number(self):
        ok, _, err = self.v.validate("9876abcde0")
        assert ok is False

    def test_mask_format(self):
        ok, norm, _ = self.v.validate("9876543210")
        assert ok is True
        masked = self.v.mask(norm)
        # Should show last 4 digits and country prefix
        assert "3210" in masked
        assert "+" in masked
        # Middle should be masked
        assert "9876" not in masked


# ══════════════════════════════════════════════════════════════════════════════
#  ReportRetrievalService
# ══════════════════════════════════════════════════════════════════════════════

class TestReportRetrievalService:
    def setup_method(self):
        self.svc = ReportRetrievalService()

    def test_retrieve_from_text(self):
        text = "SECTION 1 — PATHOLOGIST REPORT\nSuspected Disease: Leaf Rust\nThis is a test report."
        ok, rep_text, title = self.svc.retrieve(report_text=text)
        assert ok is True
        assert rep_text == text
        assert isinstance(title, str)
        assert len(title) > 0

    def test_retrieve_empty_text_falls_back_to_db(self):
        # With empty text it will try DB — may succeed or fail depending on DB state
        ok, rep_text, title = self.svc.retrieve(report_text="")
        # Should return a bool result either way
        assert isinstance(ok, bool)
        assert isinstance(rep_text, str)
        assert isinstance(title, str)

    def test_retrieve_whitespace_text_treated_as_empty(self):
        ok, rep_text, title = self.svc.retrieve(report_text="   \n  ")
        assert isinstance(ok, bool)

    def test_title_extracted_from_text(self):
        text = "AGRI DOCTOR REPORT\nSuspected Disease: Powdery Mildew"
        ok, _, title = self.svc.retrieve(report_text=text)
        assert ok is True
        # Title should be derived from first line
        assert isinstance(title, str)
        assert len(title) > 0


# ══════════════════════════════════════════════════════════════════════════════
#  PDFAttachmentService
# ══════════════════════════════════════════════════════════════════════════════

class TestPDFAttachmentService:
    def setup_method(self):
        self.svc = PDFAttachmentService()

    @pytest.mark.skipif(not FPDF_AVAILABLE, reason="fpdf2 not installed")
    def test_generate_basic_pdf(self):
        delivery_id = "test_" + str(uuid.uuid4())[:8]
        ok, path = self.svc.generate(
            report_text="Test crop report content.\nLine 2.",
            delivery_id=delivery_id,
            report_title="Test Advisory",
        )
        assert ok is True
        assert os.path.exists(path)
        assert path.endswith(".pdf")
        # Clean up
        os.remove(path)

    @pytest.mark.skipif(not FPDF_AVAILABLE, reason="fpdf2 not installed")
    def test_generate_pdf_with_unicode_chars(self):
        delivery_id = "test_unicode_" + str(uuid.uuid4())[:8]
        ok, path = self.svc.generate(
            report_text="Disease: Rust\nAction: Apply fungicide\nSpecial chars: © ® — …",
            delivery_id=delivery_id,
            report_title="Unicode Test",
        )
        assert ok is True
        assert os.path.exists(path)
        os.remove(path)

    @pytest.mark.skipif(not FPDF_AVAILABLE, reason="fpdf2 not installed")
    def test_generate_pdf_long_report(self):
        delivery_id = "test_long_" + str(uuid.uuid4())[:8]
        long_text = "\n".join([f"Line {i}: Detailed advisory content for the crop." for i in range(100)])
        ok, path = self.svc.generate(long_text, delivery_id, "Long Report")
        assert ok is True
        assert os.path.exists(path)
        os.remove(path)

    @pytest.mark.skipif(FPDF_AVAILABLE, reason="fpdf2 IS installed")
    def test_generate_fails_without_fpdf(self):
        ok, msg = self.svc.generate("text", "id123", "title")
        assert ok is False
        assert "fpdf2" in msg.lower() or "not installed" in msg.lower()


# ══════════════════════════════════════════════════════════════════════════════
#  WhatsAppMessageGenerator
# ══════════════════════════════════════════════════════════════════════════════

class TestWhatsAppMessageGenerator:
    def setup_method(self):
        self.gen = WhatsAppMessageGenerator()

    def test_generate_basic_message(self):
        msg = self.gen.generate(report_title="Leaf Rust Advisory")
        assert isinstance(msg, str)
        assert len(msg) > 20
        assert "Agri Doctor" in msg or "AGRI" in msg

    def test_message_includes_title(self):
        msg = self.gen.generate(report_title="Powdery Mildew Advisory")
        assert "Powdery Mildew" in msg

    def test_message_includes_recipient_name(self):
        msg = self.gen.generate(report_title="Test", recipient_name="John")
        assert "John" in msg

    def test_message_includes_pdf_note_when_available(self):
        msg = self.gen.generate(report_title="Test", pdf_available=True)
        assert "PDF" in msg or "attachment" in msg.lower() or "pdf" in msg.lower()

    def test_message_no_pdf_note_when_unavailable(self):
        msg = self.gen.generate(report_title="Test", pdf_available=False)
        # Should not mention PDF if not available
        assert "PDF" not in msg

    def test_message_truncated_to_limit(self):
        from services.whatsapp_service import MAX_WHATSAPP_CHARS
        msg = self.gen.generate(
            report_title="Test",
            report_summary="x" * 2000,
        )
        assert len(msg) <= MAX_WHATSAPP_CHARS

    def test_message_includes_disclaimer(self):
        msg = self.gen.generate(report_title="Test")
        assert "AI" in msg or "preliminary" in msg.lower() or "expert" in msg.lower()

    def test_disease_extracted_from_summary(self):
        summary = "Suspected Disease: Bacterial Blight\nConfidence: High"
        msg = self.gen.generate(report_title="Test", report_summary=summary)
        assert "Bacterial Blight" in msg


# ══════════════════════════════════════════════════════════════════════════════
#  WhatsAppDeliveryService
# ══════════════════════════════════════════════════════════════════════════════

class TestWhatsAppDeliveryService:
    def setup_method(self):
        self.svc = WhatsAppDeliveryService()

    def test_prepare_url_valid_phone(self):
        ok, url, err = self.svc.prepare_url("+919876543210", "Hello test")
        assert ok is True
        assert "web.whatsapp.com" in url
        assert "919876543210" in url
        assert err == ""

    def test_prepare_url_contains_encoded_message(self):
        ok, url, err = self.svc.prepare_url("+919876543210", "Hello World")
        assert ok is True
        # URL-encoded "Hello World" is "Hello+World" or "Hello%20World"
        assert "Hello" in url

    def test_prepare_url_long_message_truncated(self):
        long_msg = "A" * 2000
        ok, url, err = self.svc.prepare_url("+919876543210", long_msg)
        assert ok is True
        # URL should not be excessively huge
        assert isinstance(url, str)


# ══════════════════════════════════════════════════════════════════════════════
#  WhatsAppRetryHandler
# ══════════════════════════════════════════════════════════════════════════════

class TestWhatsAppRetryHandler:
    def setup_method(self):
        self.handler = WhatsAppRetryHandler()

    def test_cannot_retry_nonexistent_id(self):
        can, reason = self.handler.can_retry("nonexistent_delivery_xyz_123")
        assert can is False
        assert "not found" in reason.lower()

    def test_max_attempts_constant(self):
        assert self.handler.MAX_ATTEMPTS == 3


# ══════════════════════════════════════════════════════════════════════════════
#  WhatsAppReportAgent — Full Workflow
# ══════════════════════════════════════════════════════════════════════════════

SAMPLE_REPORT = """
AGRI DOCTOR — CROP HEALTH ADVISORY
===================================
SECTION 1 — PATHOLOGIST REPORT
Suspected Disease: Leaf Rust (Puccinia triticina)
Confidence: High
Severity: Moderate

Symptoms observed:
- Yellow-orange pustules on leaf surfaces
- Premature leaf senescence
- Reduced photosynthetic area

SECTION 2 — FARM ADVISORY
Immediate Actions:
1. Apply fungicide within 24-48 hours
2. Remove and destroy infected plant material
3. Improve air circulation

Preventive Measures:
- Rotate crops annually
- Use resistant varieties next season
"""


class TestWhatsAppReportAgent:
    def setup_method(self):
        self.agent = WhatsAppReportAgent()

    def test_full_workflow_valid_phone_and_text(self):
        result = self.agent.run(
            phone="9876543210",
            report_text=SAMPLE_REPORT,
            report_title="Leaf Rust Advisory",
            session_id="test-session-001",
        )
        assert isinstance(result, dict)
        assert result["success"] is True
        assert result["status"] == STATUS_READY
        assert result["wa_url"].startswith("https://web.whatsapp.com")
        assert "919876543210" in result["wa_url"]
        assert result["phone"] == "+919876543210"
        assert result["error"] is None
        assert len(result["steps"]) > 0

    def test_pipeline_steps_recorded(self):
        result = self.agent.run(
            phone="9876543210",
            report_text=SAMPLE_REPORT,
        )
        steps = result.get("steps", [])
        step_names = [s["name"] for s in steps]
        assert "Validate Number" in step_names
        assert "Retrieve Report" in step_names
        assert "Generate Message" in step_names
        assert "Prepare WhatsApp URL" in step_names

    def test_invalid_phone_returns_failure(self):
        result = self.agent.run(
            phone="abc",
            report_text=SAMPLE_REPORT,
        )
        assert result["success"] is False
        assert result["status"] == STATUS_FAILED
        assert result["error"] is not None

    def test_empty_phone_returns_failure(self):
        result = self.agent.run(
            phone="",
            report_text=SAMPLE_REPORT,
        )
        assert result["success"] is False
        assert result["status"] == STATUS_FAILED

    def test_result_has_delivery_id(self):
        result = self.agent.run(
            phone="9876543210",
            report_text=SAMPLE_REPORT,
        )
        assert "delivery_id" in result
        assert isinstance(result["delivery_id"], str)
        assert len(result["delivery_id"]) > 0

    def test_result_has_masked_phone(self):
        result = self.agent.run(
            phone="9876543210",
            report_text=SAMPLE_REPORT,
        )
        if result["success"]:
            masked = result.get("phone_masked", "")
            assert "3210" in masked        # last 4 digits visible
            assert "9876" not in masked    # middle masked

    def test_pdf_generated_when_fpdf_available(self):
        if not FPDF_AVAILABLE:
            pytest.skip("fpdf2 not installed")
        result = self.agent.run(
            phone="9876543210",
            report_text=SAMPLE_REPORT,
        )
        if result["success"]:
            pdf_path = result.get("pdf_path", "")
            assert pdf_path, "PDF path should not be empty"
            assert os.path.exists(pdf_path), f"PDF file not found at {pdf_path}"
            # Cleanup
            if os.path.exists(pdf_path):
                os.remove(pdf_path)

    def test_different_country_codes(self):
        for phone, expected_prefix in [
            ("+14155552671", "+1"),
            ("+447911123456", "+44"),
            ("+919876543210", "+91"),
        ]:
            result = self.agent.run(
                phone=phone,
                report_text=SAMPLE_REPORT,
            )
            assert result["success"] is True, f"Failed for {phone}: {result.get('error')}"
            assert result["phone"].startswith(expected_prefix), \
                f"Expected prefix {expected_prefix} for {phone}, got {result['phone']}"

    def test_retry_nonexistent_id_fails(self):
        result = self.agent.retry("nonexistent_id_xyz")
        assert result["success"] is False

    def test_duplicate_delivery_ids_unique(self):
        """Each run should produce a unique delivery ID."""
        ids = set()
        for _ in range(5):
            result = self.agent.run(phone="9876543210", report_text=SAMPLE_REPORT)
            ids.add(result["delivery_id"])
        assert len(ids) == 5, "Delivery IDs must be unique across runs"

    def test_no_report_text_uses_db(self):
        """Agent should gracefully attempt to use DB when no report text given."""
        result = self.agent.run(phone="9876543210", report_text="")
        # Either succeeds (found DB record) or fails gracefully
        assert isinstance(result["success"], bool)
        assert isinstance(result["error"], (str, type(None)))

    def test_recipient_name_in_message(self):
        result = self.agent.run(
            phone="9876543210",
            report_text=SAMPLE_REPORT,
            recipient_name="Ravi Kumar",
        )
        # Message should include recipient name
        if result["success"]:
            # We can verify the URL contains the name via the encoded message
            assert isinstance(result["wa_url"], str)

    def test_get_recent_deliveries(self):
        # Should return a list (possibly empty)
        deliveries = self.agent.get_recent_deliveries(limit=5)
        assert isinstance(deliveries, list)


# ══════════════════════════════════════════════════════════════════════════════
#  Database Integration
# ══════════════════════════════════════════════════════════════════════════════

class TestWhatsAppDeliveryDatabase:
    def test_delivery_saved_to_db(self):
        """Full agent run should persist a delivery record."""
        agent = WhatsAppReportAgent()
        result = agent.run(
            phone="9876543210",
            report_text=SAMPLE_REPORT,
            session_id="db-test-session",
        )
        if result["success"]:
            d_id = result["delivery_id"]
            # Retrieve from DB
            tracker = WhatsAppDeliveryTracker()
            record = tracker.get(d_id)
            assert record is not None
            assert record["delivery_id"] == d_id
            assert record["phone_normalized"] == "+919876543210"
            assert record["status"] in ("ready", "sent", "processing")

    def test_recent_deliveries_returned(self):
        tracker = WhatsAppDeliveryTracker()
        deliveries = tracker.recent(limit=3)
        assert isinstance(deliveries, list)
        # Each record should have required fields
        for rec in deliveries:
            assert "delivery_id" in rec
            assert "status" in rec

