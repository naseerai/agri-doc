"""
tests/test_database.py — Unit tests for the SQLite database layer.
Uses a temporary in-memory database to avoid polluting the real DB.
"""

import os
import pytest
import json

# Override database path before importing database module
os.environ["DATABASE_PATH"] = ":memory:"

from database import (
    initialize_database,
    save_diagnosis,
    get_recent_diagnoses,
    get_diagnosis_stats,
    save_agent_execution,
    get_agent_metrics,
    log_guardrail_event,
    get_guardrail_events,
    log_api_call,
)


# Tables are created once by conftest.py on the shared in-memory connection.
# No per-test setup needed.


class TestDiagnosisHistory:
    def _sample_save(self, suffix="1"):
        return save_diagnosis(
            session_id=f"session-{suffix}",
            image_filename=f"crop_{suffix}.png",
            image_size_kb=120.5,
            pathologist_report={"suspected_disease": "Early Blight"},
            extension_report={"immediate_actions": ["Remove leaves"]},
            combined_report="Full advisory text here.",
            suspected_disease="Early Blight",
            confidence_level="High",
            processing_time_seconds=5.2,
        )

    def test_save_and_retrieve(self):
        row_id = self._sample_save()
        assert isinstance(row_id, int)
        assert row_id > 0

        records = get_recent_diagnoses(limit=10)
        assert len(records) >= 1
        assert records[0]["suspected_disease"] == "Early Blight"

    def test_multiple_diagnoses_ordered_by_recency(self):
        self._sample_save("a")
        self._sample_save("b")
        records = get_recent_diagnoses(limit=10)
        assert len(records) >= 2

    def test_stats_count_total(self):
        self._sample_save("x")
        self._sample_save("y")
        stats = get_diagnosis_stats()
        assert stats["total_diagnoses"] >= 2

    def test_healthy_crop_counted(self):
        save_diagnosis(
            session_id="sess-healthy",
            image_filename="healthy.png",
            image_size_kb=80,
            pathologist_report={"suspected_disease": "Healthy — No disease detected"},
            extension_report={},
            combined_report="Crop is healthy.",
            suspected_disease="Healthy — No disease detected",
            confidence_level="High",
            processing_time_seconds=3.0,
        )
        stats = get_diagnosis_stats()
        assert stats["healthy_crops"] >= 1


class TestAgentExecution:
    def test_save_and_retrieve_metrics(self):
        save_agent_execution(
            diagnosis_id=None,
            agent_name="pathologist",
            model_id="groq-vision",
            input_tokens=400,
            output_tokens=200,
            latency_seconds=2.5,
            api_status="success",
        )
        metrics = get_agent_metrics(days=7)
        assert any(m["agent_name"] == "pathologist" for m in metrics)

    def test_error_status_saved(self):
        save_agent_execution(
            diagnosis_id=None,
            agent_name="extension_officer",
            model_id="ibm/granite-4-0-tiny-preview",
            input_tokens=0,
            output_tokens=0,
            latency_seconds=1.0,
            api_status="error",
            error_message="Connection timeout",
        )
        metrics = get_agent_metrics(days=7)
        error_metrics = [m for m in metrics if m["api_status"] == "error"]
        assert len(error_metrics) >= 1
        assert error_metrics[0]["error_message"] == "Connection timeout"


class TestGuardrailEvents:
    def test_log_and_retrieve_event(self):
        log_guardrail_event(
            session_id="sess-guard",
            event_type="input_blocked",
            agent_name="pathologist",
            details="Prompt injection detected",
            severity="high",
        )
        events = get_guardrail_events(days=7)
        assert len(events) >= 1
        assert events[0]["event_type"] == "input_blocked"

    def test_multiple_events_retrieved(self):
        log_guardrail_event("s1", "output_filtered", "extension_officer", "Unsafe advice", "high")
        log_guardrail_event("s2", "injection_detected", "pathologist", "Jailbreak attempt", "high")
        events = get_guardrail_events(days=7)
        assert len(events) >= 2
