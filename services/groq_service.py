"""
services/groq_service.py — Groq vision LLM client for Agri Doctor.

Wraps the Groq API to send crop images for analysis by a multimodal
vision model. Handles authentication, retries, token tracking, and
graceful error reporting.
"""

import base64
import time
import logging
from typing import Tuple, Dict, Any, Optional

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import (
    GROQ_API_KEY,
    GROQ_MODEL_ID,
    MAX_OUTPUT_TOKENS,
    REQUEST_TIMEOUT_SECONDS,
    MAX_RETRIES,
    RETRY_DELAY_SECONDS,
)

logger = logging.getLogger(__name__)

# Map decommissioned models to currently supported vision models
DECOMMISSIONED_GROQ_MODELS = {
    "llama-3.2-11b-vision-preview": "qwen/qwen3.8-27b",
    "llama-3.2-90b-vision-preview": "qwen/qwen3.8-27b",
    "meta-llama/llama-4-scout-17b-16e-instruct": "qwen/qwen3.8-27b",
}

# ──────────────────────────────────────────────────────────────────────────────
# Client Initialisation
# ──────────────────────────────────────────────────────────────────────────────

def _get_groq_client():
    """Lazily initialise the Groq client. Raises ValueError if key is missing."""
    if not GROQ_API_KEY:
        raise ValueError(
            "GROQ_API_KEY is not set. Please add it to your .env file or "
            "enter it in the Settings page."
        )
    try:
        from groq import Groq
        return Groq(api_key=GROQ_API_KEY)
    except ImportError:
        raise ImportError("The 'groq' package is not installed. Run: pip install groq")


# ──────────────────────────────────────────────────────────────────────────────
# Image Encoding
# ──────────────────────────────────────────────────────────────────────────────

def encode_image_to_base64(image_bytes: bytes) -> str:
    """Return a base64-encoded string from raw image bytes."""
    return base64.b64encode(image_bytes).decode("utf-8")


# ──────────────────────────────────────────────────────────────────────────────
# Core Analysis Function
# ──────────────────────────────────────────────────────────────────────────────

CROP_ANALYSIS_SYSTEM_PROMPT = """You are a professional plant pathologist AI assistant specialising in crop disease diagnosis. Your role is to:
1. Carefully analyse the crop image provided by the farmer.
2. Identify visible symptoms, discolouration, lesions, wilting, spots, or abnormalities.
3. Determine the most likely disease or health condition affecting the crop.
4. Provide a structured, factual diagnosis WITHOUT guessing when the image is unclear.
5. NEVER fabricate disease names or invent treatments.
6. If the image does not clearly show a crop or is too blurry/dark, ask for a better image.
7. Always express uncertainty where appropriate using confidence levels: High / Medium / Low.
8. Focus only on plant pathology — do not provide medical or human health advice.

Output format (respond in this exact JSON-compatible structure):
{
  "suspected_disease": "<disease name or 'Unclear — better image required'>",
  "confidence_level": "<High|Medium|Low|Unclear>",
  "symptoms_observed": ["<symptom 1>", "<symptom 2>", ...],
  "possible_causes": ["<cause 1>", "<cause 2>", ...],
  "affected_plant_parts": ["<part 1>", ...],
  "disease_severity": "<Mild|Moderate|Severe|Unclear>",
  "alternative_diagnoses": ["<alt diagnosis 1>", ...],
  "image_quality": "<Good|Fair|Poor>",
  "requires_lab_confirmation": <true|false>,
  "pathologist_notes": "<additional observations or caveats>"
}"""


def analyse_crop_image(
    image_bytes: bytes,
    image_mime_type: str = "image/jpeg",
    additional_context: str = "",
    api_key_override: Optional[str] = None,
    model_override: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Send a crop image to the Groq vision model for pathology analysis.

    Parameters
    ----------
    image_bytes : bytes
        Raw bytes of the uploaded image.
    image_mime_type : str
        MIME type of the image.
    additional_context : str
        Optional farmer notes to include with the prompt.
    api_key_override : str, optional
        Override the environment API key (from Settings UI).
    model_override : str, optional
        Override the default Groq model.

    Returns
    -------
    Tuple[Dict, Dict]
        (parsed_report, execution_metadata)
    """
    import json

    # Allow runtime key override from settings
    global GROQ_API_KEY
    effective_key = api_key_override or GROQ_API_KEY
    effective_model = model_override or GROQ_MODEL_ID
    if effective_model in DECOMMISSIONED_GROQ_MODELS:
        logger.warning(
            f"Groq model '{effective_model}' is decommissioned. "
            f"Auto-switching to '{DECOMMISSIONED_GROQ_MODELS[effective_model]}'."
        )
        effective_model = DECOMMISSIONED_GROQ_MODELS[effective_model]

    if not effective_key:
        raise ValueError(
            "GROQ_API_KEY is missing. Add it in Settings or your .env file."
        )

    try:
        from groq import Groq
        client = Groq(api_key=effective_key)
    except ImportError:
        raise ImportError("The 'groq' package is not installed. Run: pip install groq")

    b64_image = encode_image_to_base64(image_bytes)
    data_url = f"data:{image_mime_type};base64,{b64_image}"

    user_prompt = "Please analyse this crop image and provide a detailed pathology report in the specified JSON format."
    if additional_context.strip():
        user_prompt += f"\n\nFarmer's notes: {additional_context}"

    messages = [
        {"role": "system", "content": CROP_ANALYSIS_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": user_prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": data_url},
                },
            ],
        },
    ]

    # ── Retry loop ────────────────────────────────────────────────────────
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        start_time = time.time()
        try:
            response = client.chat.completions.create(
                model=effective_model,
                messages=messages,
                max_tokens=MAX_OUTPUT_TOKENS,
                temperature=0.2,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            latency = time.time() - start_time
            raw_text = response.choices[0].message.content or ""

            # Token usage
            usage = response.usage
            input_tokens = usage.prompt_tokens if usage else 0
            output_tokens = usage.completion_tokens if usage else 0

            # Parse JSON from the response
            report = _parse_json_response(raw_text)

            metadata = {
                "model": effective_model,
                "latency_seconds": round(latency, 3),
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "attempts": attempt,
                "raw_response": raw_text,
                "provider": "groq",
            }
            logger.info(f"Groq vision analysis completed in {latency:.2f}s (attempt {attempt})")
            return report, metadata

        except Exception as exc:
            last_error = exc
            logger.warning(f"Groq API attempt {attempt} failed: {exc}")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY_SECONDS * attempt)

    # All retries exhausted
    raise RuntimeError(
        f"Groq vision API failed after {MAX_RETRIES} attempts. "
        f"Last error: {last_error}"
    )


def _parse_json_response(raw_text: str) -> Dict[str, Any]:
    """
    Extract and parse the JSON block from the model's text response.
    Falls back to a structured error dict if parsing fails.
    """
    import json

    # Try to extract JSON between curly braces
    match = re.search(r'\{.*\}', raw_text, re.DOTALL)
    if match:
        json_str = match.group(0)
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            pass

    # If JSON parsing fails, build a fallback structure from the raw text
    logger.warning("Could not parse JSON from Groq response; using raw text fallback.")
    return {
        "suspected_disease": "Analysis completed — see notes",
        "confidence_level": "Low",
        "symptoms_observed": ["See pathologist notes below"],
        "possible_causes": ["See pathologist notes below"],
        "affected_plant_parts": [],
        "disease_severity": "Unclear",
        "alternative_diagnoses": [],
        "image_quality": "Unknown",
        "requires_lab_confirmation": True,
        "pathologist_notes": raw_text,
    }


import re  # imported at module level below — kept here for _parse_json_response


def test_groq_connection(api_key: str = "", model: str = "") -> Tuple[bool, str]:
    """
    Lightweight connectivity test — sends a tiny text-only request.
    Returns (success, message).
    """
    try:
        from groq import Groq
        key = api_key or GROQ_API_KEY
        if not key:
            return False, "GROQ_API_KEY is not set."
        client = Groq(api_key=key)
        mdl = model or GROQ_MODEL_ID
        if mdl in DECOMMISSIONED_GROQ_MODELS:
            mdl = DECOMMISSIONED_GROQ_MODELS[mdl]
        response = client.chat.completions.create(
            model=mdl,
            messages=[{"role": "user", "content": "Reply with: OK"}],
            max_tokens=5,
            timeout=15,
        )
        reply = response.choices[0].message.content or ""
        return True, f"Connected successfully. Model: {mdl}. Response: {reply.strip()}"
    except Exception as exc:
        return False, f"Connection failed: {exc}"
