#!/usr/bin/env python3
"""Human escalation gateway — concentrated human interaction at end of pipeline.

Generates structured phase summary, aggregates findings, and presents
approval interface with approve/reject/modify options.
"""

import json
import os
import sqlite3
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

DJITIMFLO_DB = os.environ.get(
    "LOOP_DB_PATH", os.path.expanduser("~/djimitflo/.data/djimitflo.sqlite")
)
ESCALATION_TIMEOUT_HOURS = int(os.environ.get("ESCALATION_TIMEOUT_HOURS", 72))


def generate_summary(run_id: str) -> dict:
    """Generate structured phase summary for a loop run."""
    conn = sqlite3.connect(DJITIMFLO_DB)

    run = conn.execute(
        "SELECT id, mode, status, created_at, completed_at FROM loop_runs WHERE id = ?",
        (run_id,),
    ).fetchone()

    if not run:
        return {"error": f"Run {run_id} not found"}

    events = conn.execute(
        "SELECT event_type, level, message, created_at FROM loop_events WHERE loop_run_id = ? ORDER BY created_at",
        (run_id,),
    ).fetchall()

    checkpoints = conn.execute(
        "SELECT label, state_json, gates_json, findings_json FROM loop_checkpoints WHERE loop_run_id = ? ORDER BY created_at",
        (run_id,),
    ).fetchall()

    violations = conn.execute(
        "SELECT action_type, description, risk_level FROM policy_violations WHERE status != 'resolved'",
    ).fetchall()

    conn.close()

    phase_summaries = []
    for label, state_json, gates_json, findings_json in checkpoints:
        phase_summaries.append(
            {
                "phase": label.replace("_complete", ""),
                "state": json.loads(state_json),
                "gates": json.loads(gates_json),
                "findings": json.loads(findings_json),
            }
        )

    return {
        "run_id": run[0],
        "mode": run[1],
        "status": run[2],
        "created_at": run[3],
        "completed_at": run[4],
        "total_events": len(events),
        "phases": phase_summaries,
        "open_violations": [
            {"type": v[0], "details": v[1], "severity": v[2]} for v in violations
        ],
    }


def aggregate_findings(run_id: str) -> list[dict]:
    """Aggregate and deduplicate findings from all phases, sorted by severity."""
    conn = sqlite3.connect(DJITIMFLO_DB)

    checkpoints = conn.execute(
        "SELECT findings_json FROM loop_checkpoints WHERE loop_run_id = ?",
        (run_id,),
    ).fetchall()

    events = conn.execute(
        "SELECT message, level FROM loop_events WHERE loop_run_id = ? AND level IN ('error', 'warning')",
        (run_id,),
    ).fetchall()

    conn.close()

    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    findings = []

    for row in checkpoints:
        for f in json.loads(row[0]):
            if isinstance(f, str):
                findings.append(
                    {"detail": f, "severity": "medium", "source": "checkpoint"}
                )
            elif isinstance(f, dict):
                findings.append(f)

    for msg, level in events:
        findings.append({"detail": msg, "severity": level, "source": "event"})

    # Deduplicate
    seen = set()
    unique = []
    for f in findings:
        key = f.get("detail", str(f))
        if key not in seen:
            seen.add(key)
            unique.append(f)

    unique.sort(key=lambda x: severity_order.get(x.get("severity", "medium"), 2))
    return unique


def present_approval_interface(run_id: str) -> dict:
    """Present approval interface and return user decision."""
    summary = generate_summary(run_id)
    findings = aggregate_findings(run_id)

    print("=" * 60)
    print("  HUMAN ESCALATION GATEWAY")
    print("=" * 60)

    if "error" in summary:
        print(f"ERROR: {summary['error']}")
        return {"decision": "error", "reason": summary["error"]}

    print(f"\nRun ID: {summary['run_id']}")
    print(f"Mode: {summary['mode']}")
    print(f"Status: {summary['status']}")
    print(f"Started: {summary['created_at']}")
    print(f"Completed: {summary['completed_at']}")

    print(f"\n{'─' * 40}")
    print("PHASE SUMMARY:")
    print(f"{'─' * 40}")
    for phase in summary["phases"]:
        gates_status = ", ".join(
            f"{g.get('gate', '?')}:{g.get('status', '?')}" for g in phase["gates"]
        )
        print(f"  {phase['phase']}: [{gates_status}]")

    if findings:
        print(f"\n{'─' * 40}")
        print(f"FINDINGS ({len(findings)}):")
        print(f"{'─' * 40}")
        for f in findings:
            severity = f.get("severity", "medium").upper()
            detail = f.get("detail", str(f))
            print(f"  [{severity}] {detail}")

    if summary["open_violations"]:
        print(f"\n{'─' * 40}")
        print(f"OPEN POLICY VIOLATIONS ({len(summary['open_violations'])}):")
        print(f"{'─' * 40}")
        for v in summary["open_violations"]:
            print(f"  [{v['severity'].upper()}] {v['type']}: {v['details']}")

    print(f"\n{'─' * 40}")
    print("DECISION OPTIONS:")
    print(f"{'─' * 40}")
    print("  1. APPROVE  — Accept all changes and proceed")
    print("  2. REJECT   — Reject changes with reason")
    print("  3. MODIFY   — Request modifications and re-run")
    print(f"\nTimeout: {ESCALATION_TIMEOUT_HOURS} hours (default: reject)")

    return {
        "decision": "pending",
        "summary": summary,
        "findings": findings,
    }


def record_decision(run_id: str, decision: str, reason: str = "", actor: str = "human"):
    """Record human decision to governance_events."""
    conn = sqlite3.connect(DJITIMFLO_DB)
    conn.execute(
        """INSERT INTO governance_events (id, agent_id, session_id, action_type, risk_level, metadata_json)
           VALUES (?, ?, ?, 'human_decision', 'medium', ?)""",
        (
            str(uuid.uuid4()),
            actor,
            run_id,
            json.dumps({"decision": decision, "reason": reason}),
        ),
    )

    if decision == "reject":
        # Trip circuit breaker for this run
        existing = conn.execute(
            "SELECT agent_id FROM governance_circuit_breaker WHERE agent_id = ?",
            (f"run_{run_id[:8]}",),
        ).fetchone()
        if existing:
            conn.execute(
                """UPDATE governance_circuit_breaker
                   SET tripped = 1, failures = failures + 1, last_failure_at = datetime('now')
                   WHERE agent_id = ?""",
                (f"run_{run_id[:8]}",),
            )
        else:
            conn.execute(
                """INSERT INTO governance_circuit_breaker (agent_id, failures, tripped)
                   VALUES (?, 1, 1)""",
                (f"run_{run_id[:8]}",),
            )

    conn.commit()
    conn.close()


def main():
    run_id = sys.argv[1] if len(sys.argv) > 1 else None
    if not run_id:
        # Find latest run
        conn = sqlite3.connect(DJITIMFLO_DB)
        row = conn.execute(
            "SELECT id FROM loop_runs ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        conn.close()
        if row:
            run_id = row[0]
        else:
            print("No loop runs found")
            return 1

    result = present_approval_interface(run_id)

    if result["decision"] == "pending":
        print("\nWaiting for decision... (use record_decision() to submit)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
