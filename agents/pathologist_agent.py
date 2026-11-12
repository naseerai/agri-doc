
"""
agents/pathologist_agent.py — Pathologist Agent for Agri Doctor.

Receives an uploaded crop image, applies input guardrails, calls the
vision LLM (Gemini primary, Groq fallback), validates the output,
logs metrics, and returns a structured diagnostic report.
"""

import time
import logging
import uuid
import os
import sys

from typing import Tuple, Dict, Any, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from guardrails.input_guardrails import (
    validate_image,
    validate_image_content_is_crop,
    validate_text_input,
)

from guardrails.output_guardrails import (
    validate_pathologist_output,
    add_safety_disclaimer,
    sanitise_output,
)

from database import save_agent_execution, log_guardrail_event

logger = logging.getLogger(__name__)


def get_config(key: str, default: str = "") -> str:
    """
    Read configuration from Streamlit Secrets first,
    then fall back to environment variables.
    """

    try:
        import streamlit as st

        value = st.secrets.get(key, None)

        if value is not None and str(value).strip():
            return str(value).strip()

    except Exception as exc:
        logger.debug("Streamlit Secrets unavailable: %s", type(exc).__name__)

    return os.getenv(key, default).strip()


class PathologistAgent:

    AGENT_NAME = "pathologist"

    def __init__(
        self,
        gemini_api_key: Optional[str] = None,
        gemini_model: Optional[str] = None,
        groq_api_key: Optional[str] = None,
        groq_model: Optional[str] = None,
    ):

        self.gemini_api_key = gemini_api_key or get_config("GEMINI_API_KEY")
        self.gemini_model = gemini_model or get_config(
            "GEMINI_MODEL_ID", "gemini-2.5-flash"
        )

        self.groq_api_key = groq_api_key or get_config("GROQ_API_KEY")
        self.groq_model = groq_model or get_config(
            "GROQ_MODEL_ID", "qwen/qwen3.8-27b"
        )

    def _call_vision_llm(
        self,
        image_bytes: bytes,
        image_mime_type: str,
        farmer_notes: str,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:

        gemini_key = self.gemini_api_key or get_config("GEMINI_API_KEY")
        groq_key = self.groq_api_key or get_config("GROQ_API_KEY")

        gemini_err = None

        # PRIMARY: GEMINI
        if gemini_key:

            try:
                from services.gemini_service import analyse_crop_image_gemini

                logger.info("[%s] Attempting Gemini vision analysis", self.AGENT_NAME)

                return analyse_crop_image_gemini(
                    image_bytes=image_bytes,
                    image_mime_type=image_mime_type,
                    additional_context=farmer_notes,
                    api_key=gemini_key,
                    model_id=self.gemini_model,
                )

            except Exception as exc:
                gemini_err = exc

                logger.warning(
                    "[%s] Gemini failed. Trying Groq fallback. Error: %s",
                    self.AGENT_NAME,
                    exc,
                )

        # FALLBACK: GROQ
        if groq_key:

            try:
                from services.groq_service import analyse_crop_image

                logger.info("[%s] Attempting Groq vision analysis", self.AGENT_NAME)

                return analyse_crop_image(
                    image_bytes=image_bytes,
                    image_mime_type=image_mime_type,
                    additional_context=farmer_notes,
                    api_key_override=groq_key,
                    model_override=self.groq_model,
                )

            except Exception as groq_err:

                logger.error("[%s] Groq vision failed: %s", self.AGENT_NAME, groq_err)

                raise RuntimeError(
                    "Both Gemini and Groq vision APIs failed. "
                    f"Gemini error: {gemini_err}. "
                    f"Groq error: {groq_err}"
                ) from groq_err

        raise ValueError(
            "No vision API key configured. "
            "Please configure GEMINI_API_KEY or GROQ_API_KEY "
            "in Streamlit Cloud Secrets."
        )

    def run(
        self,
        image_bytes: bytes,
        image_filename: str,
        image_mime_type: str = "image/jpeg",
        farmer_notes: str = "",
        session_id: Optional[str] = None,
        diagnosis_id: Optional[int] = None,
    ) -> Tuple[bool, Dict[str, Any], Dict[str, Any]]:

        session_id = session_id or str(uuid.uuid4())
        start_time = time.time()

        # STEP 1: Validate image
        logger.info("[%s] Validating image: %s", self.AGENT_NAME, image_filename)

        valid, err = validate_image(
            image_bytes, image_filename, image_mime_type
        )

        if not valid:
            log_guardrail_event(
                session_id, "input_blocked", self.AGENT_NAME, err, "high"
            )

            return False, {"error": err, "agent": self.AGENT_NAME}, {}

        valid, err = validate_image_content_is_crop(image_filename)

        if not valid:
            log_guardrail_event(
                session_id, "input_blocked", self.AGENT_NAME, err, "low"
            )

            logger.warning(
                "[%s] Filename heuristic warning: %s",
                self.AGENT_NAME,
                err,
            )

        # STEP 2: Validate farmer notes
        if farmer_notes:

            valid_text, text_err = validate_text_input(
                farmer_notes, "Farmer notes"
            )

            if not valid_text:

                log_guardrail_event(
                    session_id,
                    "input_blocked",
                    self.AGENT_NAME,
                    text_err,
                    "medium",
                )

                farmer_notes = ""

                logger.warning(
                    "[%s] Farmer notes blocked: %s",
                    self.AGENT_NAME,
                    text_err,
                )

        # STEP 3: Call vision LLM
        logger.info("[%s] Calling vision LLM", self.AGENT_NAME)

        try:

            report, llm_metadata = self._call_vision_llm(
                image_bytes=image_bytes,
                image_mime_type=image_mime_type,
                farmer_notes=farmer_notes,
            )

        except Exception as exc:

            logger.error(
                "[%s] Vision LLM error: %s",
                self.AGENT_NAME,
                exc,
            )

            total_time = time.time() - start_time

            save_agent_execution(
                diagnosis_id=diagnosis_id,
                agent_name=self.AGENT_NAME,
                model_id="vision-llm",
                input_tokens=0,
                output_tokens=0,
                latency_seconds=total_time,
                api_status="error",
                error_message=str(exc),
            )

            return False, {
                "error": str(exc),
                "agent": self.AGENT_NAME,
            }, {
                "latency_seconds": round(total_time, 3),
                "api_status": "error",
            }

        # STEP 4: Validate output
        is_valid, validation_msg = validate_pathologist_output(report)

        if not is_valid:

            log_guardrail_event(
                session_id,
                "output_filtered",
                self.AGENT_NAME,
                validation_msg,
                "high",
            )

            logger.error(
                "[%s] Output validation failed: %s",
                self.AGENT_NAME,
                validation_msg,
            )

            return False, {
                "error": validation_msg,
                "agent": self.AGENT_NAME,
            }, llm_metadata

        # STEP 5: Enrich report
        report["agent"] = self.AGENT_NAME
        report["session_id"] = session_id
        report["image_filename"] = image_filename
        report["image_size_kb"] = round(len(image_bytes) / 1024, 2)
        report["vision_provider"] = llm_metadata.get("provider", "unknown")

        for key, value in report.items():

            if isinstance(value, str):
                report[key] = sanitise_output(value)

        if report.get("pathologist_notes"):

            report["pathologist_notes"] = add_safety_disclaimer(
                report["pathologist_notes"]
            )

        total_time = time.time() - start_time

        # STEP 6: Log metrics
        save_agent_execution(
            diagnosis_id=diagnosis_id,
            agent_name=self.AGENT_NAME,
            model_id=llm_metadata.get("model", ""),
            input_tokens=llm_metadata.get("input_tokens", 0),
            output_tokens=llm_metadata.get("output_tokens", 0),
            latency_seconds=llm_metadata.get(
                "latency_seconds", total_time
            ),
            api_status="success",
        )

        execution_metadata = {
            **llm_metadata,
            "total_agent_time": round(total_time, 3),
            "agent": self.AGENT_NAME,
            "api_status": "success",
        }

        logger.info(
            "[%s] Completed in %.2fs. Disease: %s | Provider: %s",
            self.AGENT_NAME,
            total_time,
            report.get("suspected_disease", "N/A"),
            report.get("vision_provider", "?"),
        )

        return True, report, execution_metadata
