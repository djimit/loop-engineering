#!/usr/bin/env python3
"""Injection enforcement gate — detection with teeth.

detect_injection() (tests/prompt_injection/test_injection.py) only *reports*
matched patterns. This module couples every detection to a hard consequence:

  1. policy_violations row (status='open') — auditable, deduped via stable id
  2. governance_events row (risk_level='high', action_type='injection_blocked')
  3. circuit breaker for the source agent trips
  4. run escalation: loop run is forced to 'escalated' so no downstream
     phase can treat the run as green

Fail-closed: unknown patterns/paths raise rather than pass silently.
"""

import json
import sqlite3
import uuid
from datetime import datetime

from config import ensure_schema

_VIOLATION_NAMESPACE = uuid.UUID("9dc1f3a1-77b9-4a1e-9f6c-1ba0d9c47e21")
CB_AGENT_ID = "prompt_injection_gate"


def _stable_violation_id(source: str, pattern: str) -> str:
    return str(uuid.uuid5(_VIOLATION_NAMESPACE, f"enforce:{source}:{pattern}"))


def enforce_injection_gate(
    conn: sqlite3.Connection,
    pattern_name: str,
    source: str,
    run_id: str | None = None,
    correlation_id: str | None = None,
) -> dict:
    """Enforce consequences for one detected injection attempt.

    pattern_name must be a known INJECTION_PATTERNS key. source is free text
    (validated non-empty, length-capped). Returns the enforcement record.
    Raises ValueError on unknown pattern or empty source (fail-closed).
    """
    from injection_patterns import INJECTION_PATTERNS

    if pattern_name not in INJECTION_PATTERNS:
        raise ValueError(f"Unknown injection pattern: {pattern_name!r}")
    if not source or not isinstance(source, str):
        raise ValueError("source must be a non-empty string")
    source = source[:512]

    ensure_schema(conn)

    violation_id = _stable_violation_id(source, pattern_name)
    now = datetime.now().astimezone().isoformat()

    conn.execute(
        """INSERT INTO policy_violations
           (id, policy_id, action_type, risk_level, status,
            description, metadata)
           VALUES (?, 'no-secrets-in-prompts', 'injection_detected',
                   'high', 'open', ?, ?)
           ON CONFLICT(id) DO NOTHING""",
        (
            violation_id,
            f"Injection pattern {pattern_name!r} in {source}",
            json.dumps(
                {
                    "pattern": pattern_name,
                    "source": source,
                    "run_id": run_id,
                }
            ),
        ),
    )

    payload = {
        "pattern": pattern_name,
        "source": source,
        "violation_id": violation_id,
        "run_id": run_id,
        "correlation_id": correlation_id,
        "enforced_at": now,
        "enforcement": "deny_and_escalate",
    }

    conn.execute(
        """INSERT INTO governance_events
           (id, agent_id, session_id, action_type, risk_level, metadata_json)
           VALUES (?, 'prompt_injection_gate', ?, 'injection_blocked', 'high', ?)""",
        (str(uuid.uuid4()), run_id or "unbound", json.dumps(payload)),
    )

    # Circuit breaker trips for the gate agent; repeated attempts accumulate.
    conn.execute(
        """INSERT INTO governance_circuit_breaker
           (agent_id, failures, tripped, last_failure_at, updated_at)
           VALUES (?, 1, 1, ?, ?)
           ON CONFLICT(agent_id) DO UPDATE SET
             failures = failures + 1, tripped = 1,
             last_failure_at = excluded.last_failure_at,
             updated_at = excluded.updated_at""",
        (CB_AGENT_ID, now, now),
    )

    if run_id:
        conn.execute(
            """UPDATE loop_runs SET status='escalated', updated_at=?
               WHERE id=? AND status NOT IN ('completed','cancelled','interrupted')""",
            (now, run_id),
        )

    return payload


def scan_and_enforce(
    conn: sqlite3.Connection,
    text: str,
    source: str,
    run_id: str | None = None,
    correlation_id: str | None = None,
) -> list[dict]:
    """Scan text against all patterns; enforce for every match.

    Returns the list of enforcement records (empty when clean).
    """
    from injection_patterns import INJECTION_PATTERNS

    if not isinstance(text, str):
        raise ValueError("text must be a string")

    enforced = []
    for name, pattern in INJECTION_PATTERNS.items():
        if pattern.search(text):
            enforced.append(
                enforce_injection_gate(conn, name, source, run_id, correlation_id)
            )
    return enforced
