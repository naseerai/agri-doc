"""
guardrails/input_guardrails.py — Input validation and sanitisation for Agri Doctor.

Checks user-supplied text and images before they reach any LLM agent.
All validation is purely rule-based; no network calls are made here.
"""

import re
import io
import logging
from typing import Tuple, Optional
from PIL import Image

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import (
    INJECTION_KEYWORDS,
    TOXICITY_KEYWORDS,
    PII_PATTERNS,
    ALLOWED_MIME_TYPES,
    MAX_IMAGE_SIZE_MB,
)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Text Input Guardrails
# ──────────────────────────────────────────────────────────────────────────────

def check_prompt_injection(text: str) -> Tuple[bool, str]:
    """
    Detect common prompt injection patterns.
    Returns (is_safe, reason). is_safe=True means no injection detected.
    """
    if not text or not isinstance(text, str):
        return True, "OK"

    lower = text.lower()
    for keyword in INJECTION_KEYWORDS:
        if keyword.lower() in lower:
            logger.warning(f"Prompt injection keyword detected: '{keyword}'")
            return False, f"Potentially unsafe instruction detected: '{keyword}'"

    return True, "OK"


def check_toxicity(text: str) -> Tuple[bool, str]:
    """
    Filter out harmful or abusive content.
    Returns (is_safe, reason).
    """
    if not text or not isinstance(text, str):
        return True, "OK"

    lower = text.lower()
    for keyword in TOXICITY_KEYWORDS:
        if keyword.lower() in lower:
            logger.warning(f"Toxic keyword detected: '{keyword}'")
            return False, f"Input contains potentially harmful content."

    return True, "OK"


def check_pii(text: str) -> Tuple[bool, str]:
    """
    Detect personally identifiable information in free-text fields.
    Returns (is_safe, reason). We warn but do not block (farm notes may
    include phone numbers legitimately).
    """
    if not text or not isinstance(text, str):
        return True, "OK"

    for pattern in PII_PATTERNS:
        if re.search(pattern, text):
            logger.info("PII pattern detected in input — logged for audit.")
            return False, "Input appears to contain personal information (phone/email/ID). Please avoid sharing personal details."

    return True, "OK"


def sanitise_text(text: str) -> str:
    """
    Strip HTML tags and control characters from free-text input.
    Does NOT alter agricultural crop descriptions.
    """
    if not text:
        return ""
    # Remove HTML tags
    text = re.sub(r"<[^>]+>", "", text)
    # Remove null bytes and other control characters (keep newlines)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    return text.strip()


def validate_text_input(text: str, field_name: str = "input") -> Tuple[bool, str]:
    """
    Run all text guardrails in sequence.
    Returns (is_valid, error_message). error_message is empty when valid.
    """
    if not text or not text.strip():
        return False, f"{field_name} cannot be empty."

    if len(text) > 2000:
        return False, f"{field_name} is too long (max 2000 characters)."

    clean = sanitise_text(text)

    safe, reason = check_prompt_injection(clean)
    if not safe:
        return False, reason

    safe, reason = check_toxicity(clean)
    if not safe:
        return False, reason

    # PII check — warn but allow
    _, pii_reason = check_pii(clean)
    if pii_reason != "OK":
        logger.info(f"PII advisory for field '{field_name}': {pii_reason}")

    return True, ""


# ──────────────────────────────────────────────────────────────────────────────
# Image Input Guardrails
# ──────────────────────────────────────────────────────────────────────────────

def validate_image(
    image_bytes: bytes,
    filename: str,
    mime_type: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    Validate an uploaded image for type, size, and basic integrity.
    Returns (is_valid, error_message).
    """
    # ── Size check ──────────────────────────────────────────────────────
    size_mb = len(image_bytes) / (1024 * 1024)
    if size_mb > MAX_IMAGE_SIZE_MB:
        return False, f"Image is too large ({size_mb:.1f} MB). Maximum allowed is {MAX_IMAGE_SIZE_MB} MB."

    if size_mb == 0:
        return False, "Image file appears to be empty."

    # ── Extension check ─────────────────────────────────────────────────
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ["jpg", "jpeg", "png"]:
        return False, f"Unsupported file type '.{ext}'. Please upload JPG or PNG images."

    # ── MIME type check ─────────────────────────────────────────────────
    if mime_type and mime_type not in ALLOWED_MIME_TYPES:
        return False, f"Unsupported MIME type '{mime_type}'. Expected image/jpeg or image/png."

    # ── PIL integrity check ─────────────────────────────────────────────
    try:
        img = Image.open(io.BytesIO(image_bytes))
        img.verify()  # Checks for truncation / corruption
    except Exception as exc:
        logger.warning(f"Image integrity check failed for '{filename}': {exc}")
        return False, "The uploaded image appears to be corrupted or invalid. Please try a different image."

    # ── Re-open to check dimensions (verify() closes the file) ──────────
    try:
        img = Image.open(io.BytesIO(image_bytes))
        width, height = img.size
        if width < 50 or height < 50:
            return False, "Image is too small (minimum 50×50 pixels). Please upload a clearer crop photo."
        if width > 8000 or height > 8000:
            return False, "Image dimensions are too large. Please resize to under 8000×8000 pixels."
    except Exception:
        pass  # Non-fatal dimension failure

    return True, ""


def validate_image_content_is_crop(filename: str) -> Tuple[bool, str]:
    """
    Lightweight heuristic: check the filename for obviously non-crop content.
    Full semantic validation is handled by the vision LLM itself.
    """
    non_crop_keywords = [
        "selfie", "passport", "id_card", "screenshot", "invoice",
        "receipt", "document", "text", "logo", "icon",
    ]
    lower_name = filename.lower()
    for kw in non_crop_keywords:
        if kw in lower_name:
            return False, f"The filename '{filename}' suggests this may not be a crop image. Please upload a photo of your crop."

    return True, ""
