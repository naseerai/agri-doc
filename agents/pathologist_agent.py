"""
agents/pathologist_agent.py — Pathologist Agent for Agri Doctor.

Receives an uploaded crop image, applies input guardrails, calls the
vision LLM (Gemini primary, Groq fallback), validates the output,
logs metrics, and returns a structured diagnostic report.
"""

import time
import logging
import uuid
from typing import Tuple, Dict, Any, Optional

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from guardrails.input_guardrails import (
    validate_image, validate_image_content_is_crop, validate_text_input,
)
from guardrails.output_guardrails import (
    validate_pathologist_output, add_safety_disclaimer, sanitise_output,
)
from database import save_agent_execution, log_guardrail_event

logger = logging.getLogger(__name__)


class PathologistAgent:
    """
    Agent 1: Plant Pathologist.

    Vision backend priority
    -----------------------
    1. Google Gemini Flash (if GEMINI_API_KEY is set)
    2. Groq Vision LLM (if GROQ_API_KEY is set and vision model available)
    3. Error — no vision backend configured
    """

    AGENT_NAME = "pathologist"

    def __init__(
        self,
        # Gemini (primary)
        gemini_api_key: Optional[str] = None,
        gemini_model: Optional[str] = None,
        # Groq (fallback)
        groq_api_key: Optional[str] = None,
        groq_model: Optional[str] = None,
    ):
        self.gemini_api_key = gemini_api_key
        self.gemini_model   = gemini_model
        self.groq_api_key   = groq_api_key
        self.groq_model     = groq_model

    def _call_vision_llm(
        self,
        image_bytes: bytes,
        image_mime_type: str,
        farmer_notes: str,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """
        Try Gemini first; fall back to Groq if Gemini is unavailable.
        """
        gemini_key = self.gemini_api_key or os.getenv("GEMINI_API_KEY", "")
        groq_key   = self.groq_api_key   or os.getenv("GROQ_API_KEY", "")

        # ── Try Gemini ───────────────────────────────────────────────────────
        gemini_err = None
        if gemini_key:
            try:
                from services.gemini_service import analyse_crop_image_gemini
                return analyse_crop_image_gemini(
                    image_bytes=image_bytes,
                    image_mime_type=image_mime_type,
                    additional_context=farmer_notes,
                    api_key=gemini_key,
                    model_id=self.gemini_model,
                )
            except Exception as e:
                gemini_err = e
                logger.warning(f"[{self.AGENT_NAME}] Gemini failed: {gemini_err}. Trying Groq…")

        # ── Try Groq ─────────────────────────────────────────────────────────
        if groq_key:
            try:
                from services.groq_service import analyse_crop_image
                return analyse_crop_image(
                    image_bytes=image_bytes,
                    image_mime_type=image_mime_type,
                    additional_context=farmer_notes,
                    api_key_override=groq_key,
                    model_override=self.groq_model,
                )
            except Exception as groq_err:
                logger.warning(f"[{self.AGENT_NAME}] Groq failed: {groq_err}")
                gemini_reason = f"{gemini_err}" if gemini_err else "Check GEMINI_API_KEY in Settings."
                raise RuntimeError(
                    f"Both Gemini and Groq vision APIs failed.\n"
                    f"Gemini: {gemini_reason}\n"
                    f"Groq: {groq_err}"
                )

        # ── No backend configured ─────────────────────────────────────────────
        raise ValueError(
            "No vision API key is configured. "
            "Please add your GEMINI_API_KEY (or GROQ_API_KEY) in ⚙️ Settings."
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
        """
        Execute the Pathologist Agent pipeline.

        Returns
        -------
        Tuple[bool, Dict, Dict]
            (success, report_dict, execution_metadata)
        """
        session_id = session_id or str(uuid.uuid4())
        start_time = time.time()

        # ── Step 1: Validate Image ─────────────────────────────────────────
        logger.info(f"[{self.AGENT_NAME}] Validating image: {image_filename}")
        valid, err = validate_image(image_bytes, image_filename, image_mime_type)
        if not valid:
            log_guardrail_event(session_id, "input_blocked", self.AGENT_NAME, err, "high")
            return False, {"error": err, "agent": self.AGENT_NAME}, {}

        # Heuristic filename check (non-fatal)
        valid, err = validate_image_content_is_crop(image_filename)
        if not valid:
            log_guardrail_event(session_id, "input_blocked", self.AGENT_NAME, err, "low")
            logger.warning(f"[{self.AGENT_NAME}] Filename heuristic warning: {err}")

        # ── Step 2: Validate Farmer Notes ─────────────────────────────────
        if farmer_notes:
            valid_text, text_err = validate_text_input(farmer_notes, "Farmer notes")
            if not valid_text:
                log_guardrail_event(
                    session_id, "input_blocked", self.AGENT_NAME, text_err, "medium"
                )
                farmer_notes = ""  # Drop notes, continue with image only
                logger.warning(f"[{self.AGENT_NAME}] Farmer notes blocked: {text_err}")

        # ── Step 3: Call Vision LLM ────────────────────────────────────────
        logger.info(f"[{self.AGENT_NAME}] Calling vision LLM…")
        try:
            report, llm_metadata = self._call_vision_llm(
                image_bytes=image_bytes,
                image_mime_type=image_mime_type,
                farmer_notes=farmer_notes,
            )
        except Exception as exc:
            logger.error(f"[{self.AGENT_NAME}] Vision LLM error: {exc}")
            total_time = time.time() - start_time
            save_agent_execution(
                diagnosis_id=diagnosis_id,
                agent_name=self.AGENT_NAME,
                model_id="vision-llm",
                input_tokens=0, output_tokens=0,
                latency_seconds=total_time,
                api_status="error",
                error_message=str(exc),
            )
            return False, {"error": str(exc), "agent": self.AGENT_NAME}, {
                "latency_seconds": round(total_time, 3), "api_status": "error",
            }

        # ── Step 4: Validate Output ────────────────────────────────────────
        is_valid, validation_msg = validate_pathologist_output(report)
        if not is_valid:
            log_guardrail_event(
                session_id, "output_filtered", self.AGENT_NAME, validation_msg, "high"
            )
            logger.error(f"[{self.AGENT_NAME}] Output validation failed: {validation_msg}")
            return False, {"error": validation_msg, "agent": self.AGENT_NAME}, llm_metadata

        # ── Step 5: Enrich Report ──────────────────────────────────────────
        report["agent"]          = self.AGENT_NAME
        report["session_id"]     = session_id
        report["image_filename"] = image_filename
        report["image_size_kb"]  = round(len(image_bytes) / 1024, 2)
        report["vision_provider"] = llm_metadata.get("provider", "unknown")

        for key, value in report.items():
            if isinstance(value, str):
                report[key] = sanitise_output(value)

        if report.get("pathologist_notes"):
            report["pathologist_notes"] = add_safety_disclaimer(
                report["pathologist_notes"]
            )

        total_time = time.time() - start_time

        # ── Step 6: Log Metrics ────────────────────────────────────────────
        save_agent_execution(
            diagnosis_id=diagnosis_id,
            agent_name=self.AGENT_NAME,
            model_id=llm_metadata.get("model", ""),
            input_tokens=llm_metadata.get("input_tokens", 0),
            output_tokens=llm_metadata.get("output_tokens", 0),
            latency_seconds=llm_metadata.get("latency_seconds", total_time),
            api_status="success",
        )

        execution_metadata = {
            **llm_metadata,
            "total_agent_time": round(total_time, 3),
            "agent": self.AGENT_NAME,
            "api_status": "success",
        }

        logger.info(
            f"[{self.AGENT_NAME}] Done in {total_time:.2f}s. "
            f"Disease: {report.get('suspected_disease','N/A')} | "
            f"Provider: {report.get('vision_provider','?')}"
        )
        return True, report, execution_metadata
