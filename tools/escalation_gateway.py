#!/usr/bin/env python3
"""Final human decision gateway for autonomous loop runs."""

import argparse
import json
import os
import sqlite3
import sys
import uuid
from datetime import datetime, timedelta

from config import ensure_schema, get_db_path

DJITIMFLO_DB = get_db_path()
ESCALATION_TIMEOUT_HOURS = int(os.environ.get("ESCALATION_TIMEOUT_HOURS", 72))
DECISIONS = {"approve", "reject", "modify"}


def _now() -> datetime:
    return datetime.now().astimezone()


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.astimezone()


def request_escalation(conn: sqlite3.Connection, run_id: str) -> dict:
    """Create one pending final human decision with a fixed deadline."""
    row = conn.execute(
        """SELECT metadata_json FROM governance_events
           WHERE session_id=? AND action_type='human_escalation_requested'
           ORDER BY created_at DESC LIMIT 1""",
        (run_id,),
    ).fetchone()
    if row:
        return json.loads(row[0])

    requested_at = _now()
    payload = {
        "decision": "pending",
        "requested_at": requested_at.isoformat(),
        "expires_at": (
            requested_at + timedelta(hours=ESCALATION_TIMEOUT_HOURS)
        ).isoformat(),
        "options": sorted(DECISIONS),
    }
    conn.execute(
        """INSERT INTO governance_events
           (id, agent_id, session_id, action_type, risk_level, metadata_json, created_at)
           VALUES (?, 'orchestrator', ?, 'human_escalation_requested', 'high', ?, ?)""",
        (str(uuid.uuid4()), run_id, json.dumps(payload), requested_at.isoformat()),
    )
    conn.execute(
        "UPDATE loop_runs SET status='escalated', updated_at=? WHERE id=?",
        (requested_at.isoformat(), run_id),
    )
    conn.commit()
    return payload


def generate_summary(run_id: str) -> dict:
    """Return the persisted phase, finding, violation, and decision state."""
    conn = sqlite3.connect(DJITIMFLO_DB)
    ensure_schema(conn)
    run = conn.execute(
        """SELECT id, mode, status, created_at, completed_at, findings_json, metadata
           FROM loop_runs WHERE id=?""",
        (run_id,),
    ).fetchone()
    if not run:
        conn.close()
        return {"error": f"Run {run_id} not found"}

    checkpoints = conn.execute(
        """SELECT label, state_json, gates_json, findings_json
           FROM loop_checkpoints WHERE loop_run_id=? ORDER BY created_at""",
        (run_id,),
    ).fetchall()
    violations = conn.execute(
        """SELECT action_type, description, risk_level FROM policy_violations
           WHERE status != 'resolved' ORDER BY created_at"""
    ).fetchall()
    request = conn.execute(
        """SELECT metadata_json FROM governance_events
           WHERE session_id=? AND action_type='human_escalation_requested'
           ORDER BY created_at DESC LIMIT 1""",
        (run_id,),
    ).fetchone()
    decision = conn.execute(
        """SELECT metadata_json FROM governance_events
           WHERE session_id=? AND action_type='human_decision'
           ORDER BY created_at DESC LIMIT 1""",
        (run_id,),
    ).fetchone()
    usage_rows = conn.execute(
        "SELECT total_tokens, metadata FROM token_usage_log"
    ).fetchall()
    conn.close()

    phases = [
        {
            "phase": label.removesuffix("_complete"),
            "state": json.loads(state_json),
            "gates": json.loads(gates_json),
            "findings": json.loads(findings_json),
        }
        for label, state_json, gates_json, findings_json in checkpoints
    ]
    findings = []
    seen = set()
    for finding in json.loads(run[5] or "[]") + [
        item for phase in phases for item in phase["findings"]
    ]:
        key = finding if isinstance(finding, str) else json.dumps(finding, sort_keys=True)
        if key not in seen:
            seen.add(key)
            findings.append(finding)
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    findings.sort(
        key=lambda finding: severity_order.get(
            finding.get("severity", "medium") if isinstance(finding, dict) else "medium",
            2,
        )
    )
    token_usage = sum(
        tokens
        for tokens, metadata in usage_rows
        if json.loads(metadata or "{}").get("run_id") == run_id
    )

    return {
        "run_id": run[0],
        "mode": json.loads(run[6] or "{}").get("capability_mode", run[1]),
        "status": run[2],
        "created_at": run[3],
        "completed_at": run[4],
        "token_usage": token_usage,
        "phases": phases,
        "findings": findings,
        "open_violations": [
            {"type": kind, "details": details, "severity": severity}
            for kind, details, severity in violations
        ],
        "escalation": json.loads(request[0]) if request else None,
        "decision": json.loads(decision[0]) if decision else None,
    }


def record_decision(
    run_id: str, decision: str, reason: str = "", actor: str = "human"
) -> dict:
    """Validate and persist the final human decision exactly once."""
    decision = decision.lower()
    if decision not in DECISIONS:
        raise ValueError(f"decision must be one of: {', '.join(sorted(DECISIONS))}")

    conn = sqlite3.connect(DJITIMFLO_DB)
    ensure_schema(conn)
    if not conn.execute("SELECT 1 FROM loop_runs WHERE id=?", (run_id,)).fetchone():
        conn.close()
        raise ValueError(f"Run {run_id} not found")
    if conn.execute(
        """SELECT 1 FROM governance_events
           WHERE session_id=? AND action_type='human_decision'""",
        (run_id,),
    ).fetchone():
        conn.close()
        raise ValueError(f"Run {run_id} already has a human decision")

    decided_at = _now().isoformat()
    payload = {
        "decision": decision,
        "reason": reason,
        "actor": actor,
        "decided_at": decided_at,
    }
    conn.execute(
        """INSERT INTO governance_events
           (id, agent_id, session_id, action_type, risk_level, metadata_json, created_at)
           VALUES (?, ?, ?, 'human_decision', 'medium', ?, ?)""",
        (str(uuid.uuid4()), actor, run_id, json.dumps(payload), decided_at),
    )
    status = {
        "approve": "completed",
        "reject": "cancelled",
        "modify": "interrupted",
    }[decision]
    conn.execute(
        "UPDATE loop_runs SET status=?, updated_at=? WHERE id=?",
        (status, decided_at, run_id),
    )
    if decision == "reject":
        conn.execute(
            """INSERT INTO governance_circuit_breaker
               (agent_id, failures, tripped, last_failure_at, updated_at)
               VALUES (?, 1, 1, ?, ?)
               ON CONFLICT(agent_id) DO UPDATE SET
                 failures=failures+1, tripped=1,
                 last_failure_at=excluded.last_failure_at,
                 updated_at=excluded.updated_at""",
            (f"run_{run_id[:8]}", decided_at, decided_at),
        )
    conn.commit()
    conn.close()
    return payload


def expire_pending_decision(run_id: str, now: datetime | None = None) -> bool:
    """Auto-reject an expired pending escalation when the gateway is evaluated."""
    summary = generate_summary(run_id)
    if "error" in summary or summary["decision"] or not summary["escalation"]:
        return False
    if (now or _now()) < _parse_datetime(summary["escalation"]["expires_at"]):
        return False
    record_decision(run_id, "reject", "Escalation response timeout", "system")
    return True


def present_approval_interface(run_id: str) -> dict:
    """Print and return the final non-interactive approval handoff."""
    expire_pending_decision(run_id)
    summary = generate_summary(run_id)
    print(json.dumps(summary, indent=2, default=str))
    if "error" not in summary and not summary["decision"]:
        print("\nDecision required: APPROVE / REJECT / MODIFY")
        print(f"Deadline: {summary['escalation']['expires_at']}")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_id", nargs="?")
    parser.add_argument("--decision", choices=sorted(DECISIONS))
    parser.add_argument("--reason", default="")
    args = parser.parse_args()

    run_id = args.run_id
    if not run_id:
        conn = sqlite3.connect(DJITIMFLO_DB)
        ensure_schema(conn)
        row = conn.execute(
            "SELECT id FROM loop_runs ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        conn.close()
        if not row:
            print("No loop runs found")
            return 1
        run_id = row[0]

    if args.decision:
        print(json.dumps(record_decision(run_id, args.decision, args.reason), indent=2))
    else:
        present_approval_interface(run_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
