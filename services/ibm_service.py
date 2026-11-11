"""
services/ibm_service.py — IBM watsonx.ai client for Agri Doctor.

Wraps the IBM watsonx.ai text generation API to power the Extension
Officer Agent (IBM Granite 4 H Small). Handles IAM token exchange,
retries, token counting, and graceful error reporting.
"""

import time
import logging
import json
from typing import Tuple, Dict, Any, Optional

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import (
    WATSONX_API_KEY,
    WATSONX_PROJECT_ID,
    WATSONX_URL,
    WATSONX_MODEL_ID,
    WATSONX_MAX_TOKENS,
    WATSONX_TEMPERATURE,
    WATSONX_TOP_P,
    REQUEST_TIMEOUT_SECONDS,
    MAX_RETRIES,
    RETRY_DELAY_SECONDS,
)

logger = logging.getLogger(__name__)

# IBM IAM token endpoint
IBM_IAM_URL = "https://iam.cloud.ibm.com/identity/token"

# Approximate cost per 1000 tokens (USD) for Granite models — indicative only
COST_PER_1K_INPUT_TOKENS = 0.0006
COST_PER_1K_OUTPUT_TOKENS = 0.0006


# ──────────────────────────────────────────────────────────────────────────────
# IAM Token Management
# ──────────────────────────────────────────────────────────────────────────────

_token_cache: Dict[str, Any] = {"token": None, "expires_at": 0}


def _get_iam_token(api_key: str) -> str:
    """
    Retrieve (or reuse cached) IBM IAM bearer token.
    Tokens are valid for ~3600 s; we refresh 5 minutes early.
    """
    import requests

    now = time.time()
    if _token_cache["token"] and now < _token_cache["expires_at"]:
        return _token_cache["token"]

    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {
        "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
        "apikey": api_key,
    }
    response = requests.post(
        IBM_IAM_URL, headers=headers, data=data, timeout=30
    )
    response.raise_for_status()
    payload = response.json()
    token = payload["access_token"]
    expires_in = payload.get("expires_in", 3600)

    _token_cache["token"] = token
    _token_cache["expires_at"] = now + expires_in - 300  # refresh 5 min early

    logger.info("IBM IAM token refreshed successfully.")
    return token


# ──────────────────────────────────────────────────────────────────────────────
# Text Generation
# ──────────────────────────────────────────────────────────────────────────────

EXTENSION_OFFICER_SYSTEM_PROMPT = """You are a certified agricultural extension officer AI assistant. Your role is to:
1. Read the plant pathologist's diagnostic report carefully.
2. Provide clear, farmer-friendly recommendations in simple language.
3. Cover: immediate remedial actions, preventive measures, crop care practices, and safe treatment options.
4. NEVER invent pesticide dosages, chemical names, or unsupported treatments.
5. ALWAYS recommend PPE (Personal Protective Equipment) when pesticides are mentioned.
6. Include environmental safety precautions.
7. Recommend consulting a local agricultural expert when confidence is low.
8. Keep advice practical, affordable, and suited to smallholder farmers.
9. If the diagnosis is unclear, say so explicitly and recommend a lab test.

Respond in this JSON format:
{
  "crop_condition_summary": "<one-sentence summary for the farmer>",
  "immediate_actions": ["<action 1>", "<action 2>", ...],
  "preventive_measures": ["<measure 1>", "<measure 2>", ...],
  "crop_care_tips": ["<tip 1>", "<tip 2>", ...],
  "treatment_options": [
    {
      "type": "<Biological|Chemical|Cultural>",
      "name": "<treatment name>",
      "instructions": "<how to apply — reference pesticide label>",
      "ppe_required": "<PPE details>",
      "environmental_notes": "<precautions>"
    }
  ],
  "when_to_seek_expert_help": "<conditions that require expert intervention>",
  "estimated_recovery_time": "<e.g., 2–3 weeks with proper treatment>",
  "advisory_confidence": "<High|Medium|Low>",
  "disclaimer": "This advice is AI-generated and should be verified by a qualified agricultural extension officer."
}"""


def generate_farm_advisory(
    pathologist_report: Dict[str, Any],
    crop_type: str = "",
    location: str = "",
    api_key_override: Optional[str] = None,
    project_id_override: Optional[str] = None,
    url_override: Optional[str] = None,
    model_override: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Call IBM watsonx.ai (IBM Granite) to generate farm advisory from a
    pathologist diagnostic report.

    Parameters
    ----------
    pathologist_report : dict
        Structured output from the Pathologist Agent.
    crop_type : str, optional
        Crop name provided by the farmer (e.g., 'Tomato').
    location : str, optional
        Farmer's region for context.
    api_key_override : str, optional
        Override from UI Settings.
    project_id_override : str, optional
        Override from UI Settings.
    url_override : str, optional
        Override from UI Settings.
    model_override : str, optional
        Override default model ID.

    Returns
    -------
    Tuple[Dict, Dict]
        (advisory_report, execution_metadata)
    """
    import requests

    effective_key = api_key_override or WATSONX_API_KEY
    effective_project = project_id_override or WATSONX_PROJECT_ID
    effective_url = (url_override or WATSONX_URL).rstrip("/")
    effective_model = model_override or WATSONX_MODEL_ID

    if not effective_key:
        raise ValueError(
            "WATSONX_API_KEY is missing. Add it in Settings or your .env file."
        )
    if not effective_project:
        raise ValueError(
            "WATSONX_PROJECT_ID is missing. Add it in Settings or your .env file."
        )

    # Build the user message
    report_text = json.dumps(pathologist_report, indent=2)
    user_message = f"""A plant pathologist has analysed a crop image and produced the following diagnostic report:

{report_text}

"""
    if crop_type:
        user_message += f"Crop type: {crop_type}\n"
    if location:
        user_message += f"Farm location: {location}\n"

    user_message += (
        "\nAs the agricultural extension officer, please provide detailed, "
        "farmer-friendly recommendations in the specified JSON format."
    )

    # Combine system + user into a single text prompt for the IBM text API
    full_prompt = (
        f"<|system|>\n{EXTENSION_OFFICER_SYSTEM_PROMPT}\n<|user|>\n{user_message}\n<|assistant|>\n"
    )

    # Get IAM token
    iam_token = _get_iam_token(effective_key)

    endpoint = f"{effective_url}/ml/v1/text/generation?version=2023-05-29"
    headers = {
        "Authorization": f"Bearer {iam_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload = {
        "model_id": effective_model,
        "input": full_prompt,
        "parameters": {
            "decoding_method": "greedy",
            "max_new_tokens": WATSONX_MAX_TOKENS,
            "temperature": WATSONX_TEMPERATURE,
            "top_p": WATSONX_TOP_P,
            "stop_sequences": ["<|user|>", "<|system|>"],
        },
        "project_id": effective_project,
    }

    # ── Retry loop ────────────────────────────────────────────────────────
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        start_time = time.time()
        try:
            resp = requests.post(
                endpoint,
                headers=headers,
                json=payload,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            latency = time.time() - start_time

            if resp.status_code == 401:
                # Force token refresh on 401
                _token_cache["expires_at"] = 0
                raise ValueError("IBM IAM authentication failed (401). Check your API key.")

            resp.raise_for_status()
            data = resp.json()

            # Extract generated text
            generated_text = ""
            if "results" in data and data["results"]:
                generated_text = data["results"][0].get("generated_text", "")
            elif "choices" in data:
                generated_text = data["choices"][0].get("text", "")

            # Token usage
            input_tokens = data.get("results", [{}])[0].get("input_token_count", 0)
            output_tokens = data.get("results", [{}])[0].get("generated_token_count", 0)

            # Estimate cost
            cost = (
                (input_tokens / 1000) * COST_PER_1K_INPUT_TOKENS +
                (output_tokens / 1000) * COST_PER_1K_OUTPUT_TOKENS
            )

            advisory = _parse_advisory_json(generated_text)

            metadata = {
                "model": effective_model,
                "latency_seconds": round(latency, 3),
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "attempts": attempt,
                "estimated_cost_usd": round(cost, 6),
                "raw_response": generated_text,
            }
            logger.info(f"IBM watsonx advisory generated in {latency:.2f}s (attempt {attempt})")
            return advisory, metadata

        except Exception as exc:
            last_error = exc
            logger.warning(f"IBM watsonx attempt {attempt} failed: {exc}")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY_SECONDS * attempt)

    raise RuntimeError(
        f"IBM watsonx API failed after {MAX_RETRIES} attempts. "
        f"Last error: {last_error}"
    )


def _parse_advisory_json(raw_text: str) -> Dict[str, Any]:
    """Parse JSON from the IBM Granite text response with fallback."""
    import re

    match = re.search(r'\{.*\}', raw_text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    logger.warning("Could not parse JSON from IBM watsonx response; using fallback.")
    return {
        "crop_condition_summary": "Advisory generated — please read notes below.",
        "immediate_actions": ["Please review the full response below for guidance."],
        "preventive_measures": [],
        "crop_care_tips": [],
        "treatment_options": [],
        "when_to_seek_expert_help": "Consult a local agricultural expert if symptoms persist.",
        "estimated_recovery_time": "Unknown",
        "advisory_confidence": "Low",
        "disclaimer": "This advice is AI-generated and should be verified by a qualified agricultural extension officer.",
        "_raw_advisory": raw_text,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Connection Test
# ──────────────────────────────────────────────────────────────────────────────

def test_watsonx_connection(
    api_key: str = "",
    project_id: str = "",
    url: str = "",
    model: str = "",
) -> Tuple[bool, str]:
    """
    Validate IBM watsonx.ai credentials by sending a minimal text request.
    Returns (success, message).
    """
    import requests

    key = api_key or WATSONX_API_KEY
    project = project_id or WATSONX_PROJECT_ID
    base_url = (url or WATSONX_URL).rstrip("/")
    mdl = model or WATSONX_MODEL_ID

    if not key:
        return False, "WATSONX_API_KEY is not set."
    if not project:
        return False, "WATSONX_PROJECT_ID is not set."

    try:
        token = _get_iam_token(key)
    except Exception as exc:
        return False, f"IAM authentication failed: {exc}"

    endpoint = f"{base_url}/ml/v1/text/generation?version=2023-05-29"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "model_id": mdl,
        "input": "Reply with: OK",
        "parameters": {"max_new_tokens": 5},
        "project_id": project,
    }

    try:
        resp = requests.post(endpoint, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        text = data.get("results", [{}])[0].get("generated_text", "").strip()
        return True, f"IBM watsonx connected. Model: {mdl}. Response: '{text}'"
    except Exception as exc:
        return False, f"IBM watsonx connection failed: {exc}"
