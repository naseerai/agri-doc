"""
database.py — SQLite persistence layer for Agri Doctor.
Stores diagnosis history, agent execution metrics, API outcomes,
and guardrail events for evaluation and analytics.
"""

import sqlite3
import json
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from contextlib import contextmanager

from config import DATABASE_PATH

logger = logging.getLogger(__name__)


@contextmanager
def get_connection():
    """Context manager for safe SQLite connection handling."""
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def initialize_database() -> None:
    """Create all tables if they do not already exist."""
    with get_connection() as conn:
        cursor = conn.cursor()

        # ── Diagnosis History ──────────────────────────────────────────────
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS diagnosis_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                image_filename TEXT,
                image_size_kb REAL,
                pathologist_report TEXT,          -- JSON string
                extension_report TEXT,             -- JSON string
                combined_report TEXT,              -- plain text
                suspected_disease TEXT,
                confidence_level TEXT,
                processing_time_seconds REAL,
                status TEXT DEFAULT 'completed',   -- completed | failed | partial
                created_at TEXT DEFAULT (datetime('now')),
                user_verified INTEGER DEFAULT 0    -- 0=unverified, 1=verified
            )
        """)

        # ── Agent Execution Metrics ────────────────────────────────────────
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS agent_executions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                diagnosis_id INTEGER REFERENCES diagnosis_history(id),
                agent_name TEXT NOT NULL,          -- pathologist | extension_officer
                model_id TEXT,
                input_tokens INTEGER,
                output_tokens INTEGER,
                latency_seconds REAL,
                api_status TEXT,                   -- success | error | timeout
                error_message TEXT,
                estimated_cost_usd REAL,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)

        # ── Guardrail Events ───────────────────────────────────────────────
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS guardrail_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                event_type TEXT,                   -- input_blocked | output_filtered | injection_detected
                agent_name TEXT,
                details TEXT,
                severity TEXT DEFAULT 'medium',    -- low | medium | high
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)

        # ── API Call Log ───────────────────────────────────────────────────
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS api_call_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                service TEXT,                      -- ibm_watsonx | groq
                endpoint TEXT,
                http_status INTEGER,
                latency_seconds REAL,
                success INTEGER DEFAULT 1,
                error_message TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)

        # ── WhatsApp Delivery Tracking ─────────────────────────────────────────
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS wa_deliveries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                delivery_id TEXT UNIQUE NOT NULL,
                diagnosis_id INTEGER REFERENCES diagnosis_history(id),
                session_id TEXT,
                phone_raw TEXT,
                phone_normalized TEXT,
                report_title TEXT,
                pdf_path TEXT,
                message_text TEXT,
                wa_url TEXT,
                status TEXT DEFAULT 'idle',
                attempt_count INTEGER DEFAULT 0,
                max_attempts INTEGER DEFAULT 3,
                error_message TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)

        logger.info("Database initialized successfully.")


# ──────────────────────────────────────────────────────────────────────────────
# Diagnosis History CRUD
# ──────────────────────────────────────────────────────────────────────────────

def save_diagnosis(
    session_id: str,
    image_filename: str,
    image_size_kb: float,
    pathologist_report: Dict,
    extension_report: Dict,
    combined_report: str,
    suspected_disease: str,
    confidence_level: str,
    processing_time_seconds: float,
    status: str = "completed",
) -> int:
    """Persist a completed diagnosis. Returns the new row id."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO diagnosis_history (
                session_id, image_filename, image_size_kb,
                pathologist_report, extension_report, combined_report,
                suspected_disease, confidence_level,
                processing_time_seconds, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            session_id,
            image_filename,
            image_size_kb,
            json.dumps(pathologist_report),
            json.dumps(extension_report),
            combined_report,
            suspected_disease,
            confidence_level,
            processing_time_seconds,
            status,
        ))
        row_id = cursor.lastrowid
        logger.info(f"Diagnosis saved with id={row_id}")
        return row_id


def get_recent_diagnoses(limit: int = 20) -> List[Dict]:
    """Return the most recent diagnoses ordered by creation time."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM diagnosis_history
            ORDER BY created_at DESC LIMIT ?
        """, (limit,))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


def get_diagnosis_stats() -> Dict[str, Any]:
    """Aggregate statistics for the home dashboard."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as total FROM diagnosis_history")
        total = cursor.fetchone()["total"]

        cursor.execute("""
            SELECT COUNT(*) as healthy FROM diagnosis_history
            WHERE LOWER(suspected_disease) LIKE '%healthy%'
               OR LOWER(suspected_disease) LIKE '%no disease%'
               OR LOWER(suspected_disease) LIKE '%normal%'
        """)
        healthy = cursor.fetchone()["healthy"]

        cursor.execute("""
            SELECT COUNT(*) as diseased FROM diagnosis_history
            WHERE LOWER(suspected_disease) NOT LIKE '%healthy%'
              AND LOWER(suspected_disease) NOT LIKE '%no disease%'
              AND LOWER(suspected_disease) NOT LIKE '%normal%'
              AND status = 'completed'
        """)
        diseased = cursor.fetchone()["diseased"]

        cursor.execute("""
            SELECT AVG(processing_time_seconds) as avg_time FROM diagnosis_history
        """)
        avg_time = cursor.fetchone()["avg_time"] or 0.0

        return {
            "total_diagnoses": total,
            "healthy_crops": healthy,
            "detected_diseases": diseased,
            "avg_processing_time": round(avg_time, 2),
        }


# ──────────────────────────────────────────────────────────────────────────────
# Agent Execution Metrics CRUD
# ──────────────────────────────────────────────────────────────────────────────

def save_agent_execution(
    diagnosis_id: Optional[int],
    agent_name: str,
    model_id: str,
    input_tokens: int,
    output_tokens: int,
    latency_seconds: float,
    api_status: str,
    error_message: Optional[str] = None,
    estimated_cost_usd: float = 0.0,
) -> None:
    """Record individual agent execution metrics."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO agent_executions (
                diagnosis_id, agent_name, model_id,
                input_tokens, output_tokens, latency_seconds,
                api_status, error_message, estimated_cost_usd
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            diagnosis_id, agent_name, model_id,
            input_tokens, output_tokens, latency_seconds,
            api_status, error_message, estimated_cost_usd,
        ))


def get_agent_metrics(days: int = 30) -> List[Dict]:
    """Return agent execution metrics for the last N days."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM agent_executions
            WHERE created_at >= datetime('now', ?)
            ORDER BY created_at DESC
        """, (f"-{days} days",))
        return [dict(row) for row in cursor.fetchall()]


# ──────────────────────────────────────────────────────────────────────────────
# Guardrail Events CRUD
# ──────────────────────────────────────────────────────────────────────────────

def log_guardrail_event(
    session_id: str,
    event_type: str,
    agent_name: str,
    details: str,
    severity: str = "medium",
) -> None:
    """Record a guardrail intervention event."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO guardrail_events (session_id, event_type, agent_name, details, severity)
            VALUES (?, ?, ?, ?, ?)
        """, (session_id, event_type, agent_name, details, severity))


def get_guardrail_events(days: int = 30) -> List[Dict]:
    """Return guardrail events for the last N days."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM guardrail_events
            WHERE created_at >= datetime('now', ?)
            ORDER BY created_at DESC, id DESC
        """, (f"-{days} days",))
        return [dict(row) for row in cursor.fetchall()]


# ──────────────────────────────────────────────────────────────────────────────
# API Call Log CRUD
# ──────────────────────────────────────────────────────────────────────────────

def log_api_call(
    service: str,
    endpoint: str,
    http_status: int,
    latency_seconds: float,
    success: bool,
    error_message: Optional[str] = None,
) -> None:
    """Log every external API call for monitoring and error analysis."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO api_call_log (service, endpoint, http_status, latency_seconds, success, error_message)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (service, endpoint, http_status, latency_seconds, int(success), error_message))


# ──────────────────────────────────────────────────────────────────────────────
# WhatsApp Delivery Tracking CRUD
# ──────────────────────────────────────────────────────────────────────────────

def save_wa_delivery(
    delivery_id: str,
    session_id: str,
    phone_raw: str,
    phone_normalized: str,
    report_title: str,
    message_text: str,
    wa_url: str,
    diagnosis_id: Optional[int] = None,
    pdf_path: str = "",
    status: str = "processing",
) -> None:
    """Create a new WhatsApp delivery record."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR IGNORE INTO wa_deliveries (
                delivery_id, diagnosis_id, session_id,
                phone_raw, phone_normalized, report_title,
                pdf_path, message_text, wa_url, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            delivery_id, diagnosis_id, session_id,
            phone_raw, phone_normalized, report_title,
            pdf_path, message_text, wa_url, status,
        ))
        logger.info(f"WA delivery saved: {delivery_id}")


def update_wa_delivery_status(
    delivery_id: str,
    status: str,
    error_message: Optional[str] = None,
    pdf_path: Optional[str] = None,
    wa_url: Optional[str] = None,
) -> None:
    """Update status (and optionally error/pdf_path/wa_url) of a delivery record."""
    with get_connection() as conn:
        cursor = conn.cursor()
        # Build dynamic SET clause
        fields = ["status = ?", "attempt_count = attempt_count + 1",
                  "updated_at = datetime('now')"]
        params: list = [status]
        if error_message is not None:
            fields.append("error_message = ?")
            params.append(error_message)
        if pdf_path is not None:
            fields.append("pdf_path = ?")
            params.append(pdf_path)
        if wa_url is not None:
            fields.append("wa_url = ?")
            params.append(wa_url)
        params.append(delivery_id)
        cursor.execute(
            f"UPDATE wa_deliveries SET {', '.join(fields)} WHERE delivery_id = ?",
            params,
        )


def get_wa_delivery(delivery_id: str) -> Optional[Dict]:
    """Return a single delivery record by its unique delivery_id."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM wa_deliveries WHERE delivery_id = ?", (delivery_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def get_recent_wa_deliveries(limit: int = 10) -> List[Dict]:
    """Return the most recent WhatsApp delivery records."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM wa_deliveries
            ORDER BY created_at DESC LIMIT ?
        """, (limit,))
        return [dict(row) for row in cursor.fetchall()]
