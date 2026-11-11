"""
agents/extension_officer_agent.py — Extension Officer Agent for Agri Doctor.

Receives the Pathologist Agent's diagnostic report, applies cross-agent
verification, calls IBM watsonx.ai (IBM Granite), validates the advisory
output, and returns farmer-friendly recommendations.
"""

import time
import logging
import uuid
from typing import Tuple, Dict, Any, Optional

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.ibm_service import generate_farm_advisory
from guardrails.output_guardrails import (
    validate_extension_output,
    add_safety_disclaimer,
    sanitise_output,
)
from database import save_agent_execution, log_guardrail_event

logger = logging.getLogger(__name__)


class ExtensionOfficerAgent:
    """
    Agent 2: Agricultural Extension Officer.

    Responsibilities
    ----------------
    - Receive and verify the Pathologist Agent's report (cross-agent check).
    - Call IBM watsonx.ai (IBM Granite) for farmer-friendly advisory.
    - Validate and sanitise the advisory output.
    - Return a structured advisory ready for display and download.
    - Log all execution metrics and guardrail events.
    """

    AGENT_NAME = "extension_officer"

    def __init__(
        self,
        watsonx_api_key: Optional[str] = None,
        watsonx_project_id: Optional[str] = None,
        watsonx_url: Optional[str] = None,
        watsonx_model: Optional[str] = None,
    ):
        self.watsonx_api_key = watsonx_api_key
        self.watsonx_project_id = watsonx_project_id
        self.watsonx_url = watsonx_url
        self.watsonx_model = watsonx_model

    def _verify_pathologist_handoff(
        self, pathologist_report: Dict[str, Any]
    ) -> Tuple[bool, str]:
        """
        Cross-agent verification: ensure the incoming report is usable
        before calling the IBM API.
        """
        if not pathologist_report:
            return False, "No pathologist report received for handoff."

        if "error" in pathologist_report:
            return False, f"Pathologist report contains an error: {pathologist_report['error']}"

        # Minimum required fields from the pathologist
        required = ["suspected_disease"]
        for field in required:
            if field not in pathologist_report:
                return False, f"Pathologist report is missing '{field}' — cannot generate advisory."

        # Reject if the vision model said it couldn't process the image
        disease = pathologist_report.get("suspected_disease", "").lower()
        if "unclear" in disease and pathologist_report.get("image_quality", "") == "Poor":
            return False, (
                "The pathologist report indicates an unclear image. "
                "Please upload a better quality crop photo before proceeding."
            )

        return True, "OK"

    def run(
        self,
        pathologist_report: Dict[str, Any],
        crop_type: str = "",
        location: str = "",
        session_id: Optional[str] = None,
        diagnosis_id: Optional[int] = None,
    ) -> Tuple[bool, Dict[str, Any], Dict[str, Any]]:
        """
        Execute the Extension Officer Agent pipeline.

        Parameters
        ----------
        pathologist_report : dict
            Structured output from the Pathologist Agent.
        crop_type : str
            Optional crop name for context (e.g., 'Tomato').
        location : str
            Optional farm location for localised advice.
        session_id : str, optional
            Session identifier for audit logging.
        diagnosis_id : int, optional
            Related diagnosis row ID.

        Returns
        -------
        Tuple[bool, Dict, Dict]
            (success, advisory_dict, execution_metadata)
        """
        session_id = session_id or str(uuid.uuid4())
        start_time = time.time()

        # ── Step 1: Cross-Agent Handoff Verification ───────────────────────
        logger.info(f"[{self.AGENT_NAME}] Verifying pathologist handoff...")
        valid, reason = self._verify_pathologist_handoff(pathologist_report)
        if not valid:
            log_guardrail_event(
                session_id, "handoff_rejected", self.AGENT_NAME, reason, severity="high"
            )
            logger.error(f"[{self.AGENT_NAME}] Handoff rejected: {reason}")
            return False, {"error": reason, "agent": self.AGENT_NAME}, {}

        # ── Step 2: Call IBM watsonx.ai ────────────────────────────────────
        logger.info(f"[{self.AGENT_NAME}] Calling IBM watsonx.ai for farm advisory...")
        try:
            advisory, llm_metadata = generate_farm_advisory(
                pathologist_report=pathologist_report,
                crop_type=crop_type,
                location=location,
                api_key_override=self.watsonx_api_key,
                project_id_override=self.watsonx_project_id,
                url_override=self.watsonx_url,
                model_override=self.watsonx_model,
            )
        except Exception as exc:
            logger.error(f"[{self.AGENT_NAME}] IBM watsonx API error: {exc}")
            total_time = time.time() - start_time
            save_agent_execution(
                diagnosis_id=diagnosis_id,
                agent_name=self.AGENT_NAME,
                model_id=self.watsonx_model or "ibm-granite",
                input_tokens=0,
                output_tokens=0,
                latency_seconds=total_time,
                api_status="error",
                error_message=str(exc),
            )
            return False, {"error": str(exc), "agent": self.AGENT_NAME}, {
                "latency_seconds": round(total_time, 3),
                "api_status": "error",
            }

        # ── Step 3: Validate Output ────────────────────────────────────────
        logger.info(f"[{self.AGENT_NAME}] Validating advisory output...")
        is_valid, validation_msg = validate_extension_output(advisory)
        if not is_valid:
            log_guardrail_event(
                session_id, "output_filtered", self.AGENT_NAME,
                validation_msg, severity="high"
            )
            logger.error(f"[{self.AGENT_NAME}] Output validation failed: {validation_msg}")
            return False, {"error": validation_msg, "agent": self.AGENT_NAME}, llm_metadata

        # ── Step 4: Enrich and Finalise Advisory ──────────────────────────
        advisory["agent"] = self.AGENT_NAME
        advisory["session_id"] = session_id
        advisory["pathologist_disease"] = pathologist_report.get("suspected_disease", "")
        advisory["pathologist_confidence"] = pathologist_report.get("confidence_level", "")

        # Sanitise string fields
        for key, value in advisory.items():
            if isinstance(value, str):
                advisory[key] = sanitise_output(value)

        # Ensure disclaimer is present
        if "disclaimer" in advisory:
            advisory["disclaimer"] = add_safety_disclaimer(advisory["disclaimer"])
        else:
            advisory["disclaimer"] = add_safety_disclaimer(
                "AI-generated farm advisory — verify with a qualified extension officer."
            )

        total_time = time.time() - start_time

        # ── Step 5: Log Execution Metrics ─────────────────────────────────
        save_agent_execution(
            diagnosis_id=diagnosis_id,
            agent_name=self.AGENT_NAME,
            model_id=llm_metadata.get("model", ""),
            input_tokens=llm_metadata.get("input_tokens", 0),
            output_tokens=llm_metadata.get("output_tokens", 0),
            latency_seconds=llm_metadata.get("latency_seconds", total_time),
            api_status="success",
            estimated_cost_usd=llm_metadata.get("estimated_cost_usd", 0.0),
        )

        execution_metadata = {
            **llm_metadata,
            "total_agent_time": round(total_time, 3),
            "agent": self.AGENT_NAME,
            "api_status": "success",
        }

        logger.info(
            f"[{self.AGENT_NAME}] Advisory generated in {total_time:.2f}s. "
            f"Confidence: {advisory.get('advisory_confidence', 'N/A')}"
        )
        return True, advisory, execution_metadata
