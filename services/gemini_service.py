"""
services/gemini_service.py — Google Gemini Vision service for Agri Doctor.

Uses google-generativeai to send crop images to Gemini Flash for
plant pathology analysis. Serves as the primary vision backend.
"""

import base64
import time
import logging
import re
import json
from typing import Tuple, Dict, Any, Optional

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import (
    MAX_OUTPUT_TOKENS,
    REQUEST_TIMEOUT_SECONDS,
    MAX_RETRIES,
    RETRY_DELAY_SECONDS,
)

logger = logging.getLogger(__name__)

# ── Default Gemini vision model (flash is free-tier friendly) ────────────────
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"

# Map deprecated or unavailable models to current stable models
DEPRECATED_GEMINI_MODELS = {
    "gemini-1.5-flash": "gemini-2.5-flash",
    "gemini-1.5-pro": "gemini-2.5-pro",
    "gemini-2.0-flash": "gemini-2.5-flash",
    "gemini-2.0-flash-exp": "gemini-2.5-flash",
    "gemini-2.5-flash-lite": "gemini-2.5-flash",
}

# ── System prompt (same as groq_service for consistency) ────────────────────
CROP_ANALYSIS_SYSTEM_PROMPT = """You are a professional plant pathologist AI assistant specialising in crop disease diagnosis. Your role is to:
1. Carefully analyse the crop image provided by the farmer.
2. Identify visible symptoms, discolouration, lesions, wilting, spots, or abnormalities.
3. Determine the most likely disease or health condition affecting the crop.
4. Provide a structured, factual diagnosis WITHOUT guessing when the image is unclear.
5. NEVER fabricate disease names or invent treatments.
6. If the image does not clearly show a crop or is too blurry/dark, say so clearly.
7. Always express uncertainty using confidence levels: High / Medium / Low / Unclear.
8. Focus only on plant pathology — do not provide medical or human health advice.

Respond ONLY with valid JSON in this exact structure (no markdown fences, no extra text):
{
  "suspected_disease": "<disease name or 'Unclear — better image required'>",
  "confidence_level": "<High|Medium|Low|Unclear>",
  "symptoms_observed": ["<symptom 1>", "<symptom 2>"],
  "possible_causes": ["<cause 1>", "<cause 2>"],
  "affected_plant_parts": ["<part 1>"],
  "disease_severity": "<Mild|Moderate|Severe|Unclear>",
  "alternative_diagnoses": ["<alt 1>"],
  "image_quality": "<Good|Fair|Poor>",
  "requires_lab_confirmation": true,
  "pathologist_notes": "<additional observations>"
}"""


def _get_gemini_client(api_key: str):
    """Initialise and return a Gemini GenerativeModel."""
    try:
        import google.generativeai as genai
        import warnings
        warnings.filterwarnings("ignore", category=FutureWarning)
        genai.configure(api_key=api_key)
        return genai
    except ImportError:
        raise ImportError(
            "google-generativeai is not installed. Run: pip install google-generativeai"
        )


def analyse_crop_image_gemini(
    image_bytes: bytes,
    image_mime_type: str = "image/jpeg",
    additional_context: str = "",
    api_key: Optional[str] = None,
    model_id: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Analyse a crop image using Google Gemini Vision.

    Returns
    -------
    Tuple[Dict, Dict]
        (parsed_report, execution_metadata)
    """
    effective_key   = api_key or os.getenv("GEMINI_API_KEY", "")
    effective_model = model_id or os.getenv("GEMINI_MODEL_ID", DEFAULT_GEMINI_MODEL)

    if effective_model in DEPRECATED_GEMINI_MODELS:
        target = DEPRECATED_GEMINI_MODELS[effective_model]
        logger.warning(
            f"Gemini model '{effective_model}' is deprecated. Auto-switching to '{target}'."
        )
        effective_model = target

    if not effective_key:
        raise ValueError(
            "GEMINI_API_KEY is not set. Add it to your .env file or Settings page."
        )

    genai = _get_gemini_client(effective_key)

    # Build user prompt
    user_prompt = (
        "Please analyse this crop image and provide a detailed pathology report "
        "as valid JSON only (no markdown fences)."
    )
    if additional_context.strip():
        user_prompt += f"\n\nFarmer's notes: {additional_context}"

    # Encode image for Gemini
    image_part = {
        "mime_type": image_mime_type,
        "data": base64.b64encode(image_bytes).decode("utf-8"),
    }

    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        start_time = time.time()
        try:
            try:
                model = genai.GenerativeModel(
                    model_name=effective_model,
                    system_instruction=CROP_ANALYSIS_SYSTEM_PROMPT,
                )
                prompt_content = [user_prompt, image_part]
            except TypeError:
                # Older google-generativeai SDK versions (< 0.5.0) do not accept system_instruction in __init__
                model = genai.GenerativeModel(model_name=effective_model)
                prompt_content = [f"{CROP_ANALYSIS_SYSTEM_PROMPT}\n\n{user_prompt}", image_part]

            response = model.generate_content(
                prompt_content,
                generation_config=genai.types.GenerationConfig(
                    max_output_tokens=MAX_OUTPUT_TOKENS,
                    temperature=0.2,
                ),
            )
            latency = time.time() - start_time
            raw_text = response.text or ""

            # Token counts (Gemini provides usage_metadata)
            usage = getattr(response, "usage_metadata", None)
            input_tokens  = getattr(usage, "prompt_token_count", 0) if usage else 0
            output_tokens = getattr(usage, "candidates_token_count", 0) if usage else 0

            report = _parse_json_response(raw_text)
            metadata = {
                "model": effective_model,
                "latency_seconds": round(latency, 3),
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "attempts": attempt,
                "raw_response": raw_text,
                "provider": "gemini",
            }
            logger.info(f"Gemini vision analysis completed in {latency:.2f}s (attempt {attempt})")
            return report, metadata

        except Exception as exc:
            last_error = exc
            logger.warning(f"Gemini API attempt {attempt} failed: {exc}")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY_SECONDS * attempt)

    # If a non-default model (e.g. preview gemini-3.8-flash) failed, try stable default model
    if effective_model != DEFAULT_GEMINI_MODEL:
        logger.warning(
            f"Gemini model '{effective_model}' failed ({last_error}). "
            f"Falling back to stable '{DEFAULT_GEMINI_MODEL}'…"
        )
        try:
            return analyse_crop_image_gemini(
                image_bytes=image_bytes,
                image_mime_type=image_mime_type,
                additional_context=additional_context,
                api_key=effective_key,
                model_id=DEFAULT_GEMINI_MODEL,
            )
        except Exception as fb_err:
            logger.warning(f"Fallback to {DEFAULT_GEMINI_MODEL} also failed: {fb_err}")

    raise RuntimeError(
        f"Gemini vision API failed after {MAX_RETRIES} attempts. Last error: {last_error}"
    )


def _parse_json_response(raw_text: str) -> Dict[str, Any]:
    """Extract and parse JSON from Gemini's text response."""
    # Strip markdown fences if present
    text = re.sub(r"```(?:json)?\s*", "", raw_text, flags=re.IGNORECASE)
    text = text.replace("```", "").strip()

    # Try full parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting first {...} block
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    logger.warning("Could not parse JSON from Gemini response; using fallback.")
    return {
        "suspected_disease": "Analysis completed — see pathologist notes",
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


def test_gemini_connection(api_key: str = "", model: str = "") -> Tuple[bool, str]:
    """Test Gemini connectivity with a simple text request (no image)."""
    try:
        import google.generativeai as genai
        import warnings
        warnings.filterwarnings("ignore", category=FutureWarning)
        key = api_key or os.getenv("GEMINI_API_KEY", "")
        if not key:
            return False, "GEMINI_API_KEY is not set."
        genai.configure(api_key=key)
        mdl = model or os.getenv("GEMINI_MODEL_ID", DEFAULT_GEMINI_MODEL)
        if mdl in DEPRECATED_GEMINI_MODELS:
            mdl = DEPRECATED_GEMINI_MODELS[mdl]
        m = genai.GenerativeModel(mdl)
        r = m.generate_content("Reply with exactly: OK")
        return True, f"Gemini connected. Model: {mdl}. Response: {r.text.strip()}"
    except Exception as exc:
        return False, f"Gemini connection failed: {exc}"
