"""
guardrails/output_guardrails.py — Output validation and safety filtering for Agri Doctor.

Validates LLM-generated text before it is displayed to the farmer or
passed to the next agent in the pipeline.
"""

import re
import logging
from typing import Tuple, Dict, Any

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import UNSAFE_CHEMICAL_KEYWORDS, TOXICITY_KEYWORDS

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Hallucination / Confidence Checks
# ──────────────────────────────────────────────────────────────────────────────

# Phrases that signal over-confident or fabricated claims
OVERCONFIDENCE_PATTERNS = [
    r"\b100\s*%\s*certain\b",
    r"\bguaranteed\s*cure\b",
    r"\bwill\s*definitely\s*cure\b",
    r"\bno\s*doubt\b",
    r"\bI\s*am\s*sure\b",
    r"\bperfect\s*diagnosis\b",
]

# Phrases that indicate the model is confused or making things up
HALLUCINATION_SIGNALS = [
    "as a language model i cannot",
    "i don't have access to the image",
    "i cannot see",
    "no image was provided",
    "the image appears blank",
]


def check_output_toxicity(text: str) -> Tuple[bool, str]:
    """Ensure LLM output contains no harmful language."""
    lower = text.lower()
    for kw in TOXICITY_KEYWORDS:
        if kw in lower:
            logger.warning(f"Toxic keyword in LLM output: '{kw}'")
            return False, f"Output contained potentially harmful content and was blocked."
    return True, ""


def check_unsafe_chemical_advice(text: str) -> Tuple[bool, str]:
    """Flag unsafe pesticide / chemical advice in the output."""
    lower = text.lower()
    for kw in UNSAFE_CHEMICAL_KEYWORDS:
        if kw in lower:
            logger.warning(f"Unsafe chemical keyword in output: '{kw}'")
            return False, "Output contained potentially unsafe chemical instructions and was filtered."
    return True, ""


def check_hallucination_signals(text: str) -> Tuple[bool, str]:
    """Detect phrases that suggest the model did not actually process the image."""
    lower = text.lower()
    for signal in HALLUCINATION_SIGNALS:
        if signal in lower:
            logger.warning(f"Hallucination signal detected: '{signal}'")
            return False, "The model indicated it could not process the image. Please try uploading a clearer photo."
    return True, ""


def check_overconfidence(text: str) -> bool:
    """Return True if the output contains overconfident language."""
    for pattern in OVERCONFIDENCE_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def validate_pathologist_output(report: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Validate the Pathologist Agent's structured output.
    Returns (is_valid, warning_message).
    """
    required_keys = ["suspected_disease", "symptoms_observed", "possible_causes"]
    for key in required_keys:
        if key not in report or report[key] is None:
            return False, f"Pathologist report is missing required field: '{key}'."
        if isinstance(report[key], str) and not report[key].strip():
            return False, f"Pathologist report is missing required field: '{key}'."
        if isinstance(report[key], list) and not report[key]:
            report[key] = ["None clearly observed"]

    # Check raw text fields for toxicity and hallucinations
    full_text = " ".join(str(v) for v in report.values())

    safe, reason = check_output_toxicity(full_text)
    if not safe:
        return False, reason

    safe, reason = check_hallucination_signals(full_text)
    if not safe:
        return False, reason

    if check_overconfidence(full_text):
        # Don't block, but add a disclaimer
        report["_confidence_warning"] = (
            "Note: The model expressed high certainty. "
            "Please consult a local agricultural expert to confirm this diagnosis."
        )

    return True, ""


def validate_extension_output(report: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Validate the Extension Officer Agent's structured output.
    Returns (is_valid, warning_message).
    """
    required_keys = ["immediate_actions", "preventive_measures"]
    for key in required_keys:
        if key not in report or report[key] is None:
            return False, f"Extension report is missing required field: '{key}'."
        if isinstance(report[key], str) and not report[key].strip():
            return False, f"Extension report is missing required field: '{key}'."
        if isinstance(report[key], list) and not report[key]:
            report[key] = ["Monitor crop closely"]

    full_text = " ".join(str(v) for v in report.values())

    safe, reason = check_output_toxicity(full_text)
    if not safe:
        return False, reason

    safe, reason = check_unsafe_chemical_advice(full_text)
    if not safe:
        return False, reason

    return True, ""


def add_safety_disclaimer(text: str) -> str:
    """
    Append a mandatory AI disclaimer to any output shown to the farmer.
    """
    disclaimer = (
        "\n\n---\n"
        "⚠️ **Important Disclaimer:** This is an AI-generated preliminary assessment "
        "and is NOT a confirmed laboratory diagnosis. Always consult a qualified "
        "agricultural extension officer or plant pathologist before applying any "
        "treatment. Follow all pesticide label instructions and local regulations."
    )
    if "AI-generated preliminary assessment" not in text:
        return text + disclaimer
    return text


def sanitise_output(text: str) -> str:
    """Remove any accidentally injected formatting or control characters from output."""
    if not text:
        return ""
    # Remove any <script> or HTML tags the model might generate
    text = re.sub(r"<script[\s\S]*?</script>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()
