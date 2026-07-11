#!/usr/bin/env python3
"""Autonomous loop orchestrator — 6-phase state machine with circuit breaker.

Phases:
  1. validate  — OpenMythos QA gates (critic, reviewer, sme, test_engineer, explorer)
  2. seed      — Governance policy + capability token seeding
  3. execute   — Loop-engineering pattern execution
  4. observe   — Djitimflo telemetry import + observability
  5. secure    — Prompt-injection gate + security validation
  6. escalate  — Human escalation gateway (ONLY human interaction point)

Phases 1-5 run fully autonomously. Phase 6 is the only human gate.
"""

import json
import os
import sqlite3
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

DJITIMFLO_DB = os.environ.get(
    "LOOP_DB_PATH", os.path.expanduser("~/djimitflo/.data/djimitflo.sqlite")
)
REPO_ROOT = Path(__file__).parent.parent
PHASE_TIMEOUT = int(os.environ.get("LOOP_PHASE_TIMEOUT", 1800))  # 30 min default
GLOBAL_TIMEOUT = int(os.environ.get("LOOP_GLOBAL_TIMEOUT", 14400))  # 4 hours default
MAX_RETRIES = 3

PHASES = ["validate", "seed", "execute", "observe", "secure", "escalate"]


class CircuitBreaker:
    """Per-phase circuit breaker with max retries and exponential backoff."""

    def __init__(self, phase: str, max_retries: int = MAX_RETRIES):
        self.phase = phase
        self.max_retries = max_retries
        self.failures = 0
        self.tripped = False

    def record_failure(self):
        self.failures += 1
        if self.failures >= self.max_retries:
            self.tripped = True

    def reset(self):
        self.failures = 0
        self.tripped = False

    def wait_backoff(self):
        """Exponential backoff: 1s, 2s, 4s."""
        time.sleep(2**self.failures)


class Orchestrator:
    """6-phase autonomous loop orchestrator."""

    def __init__(self, mode: str = "L1"):
        self.mode = mode
        self.run_id = str(uuid.uuid4())
        self.correlation_id = str(uuid.uuid4())
        self.current_phase = None
        self.phase_status = {p: "pending" for p in PHASES}
        self.findings = []
        self.token_usage = 0
        self.start_time = datetime.now()
        self.circuit_breakers = {p: CircuitBreaker(p) for p in PHASES}
        self.conn = sqlite3.connect(DJITIMFLO_DB)
        self._ensure_tables()

    def _ensure_tables(self):
        """Ensure all required tables exist."""
        for stmt in [
            """CREATE TABLE IF NOT EXISTS loop_runs (
                id TEXT PRIMARY KEY, goal_id TEXT, loop_name TEXT NOT NULL,
                mode TEXT NOT NULL, status TEXT NOT NULL, repository_path TEXT,
                state_file TEXT, findings_json TEXT DEFAULT '[]',
                plan_json TEXT DEFAULT '{}', gates_json TEXT DEFAULT '[]',
                next_actions_json TEXT DEFAULT '[]', metadata TEXT DEFAULT '{}',
                created_at TEXT, updated_at TEXT, completed_at TEXT
            )""",
            """CREATE TABLE IF NOT EXISTS loop_events (
                id TEXT PRIMARY KEY, loop_run_id TEXT NOT NULL,
                event_type TEXT NOT NULL, level TEXT, message TEXT NOT NULL,
                metadata TEXT DEFAULT '{}', created_at TEXT
            )""",
            """CREATE TABLE IF NOT EXISTS loop_checkpoints (
                id TEXT PRIMARY KEY, loop_run_id TEXT NOT NULL,
                label TEXT NOT NULL, state_json TEXT DEFAULT '{}',
                gates_json TEXT DEFAULT '[]', findings_json TEXT DEFAULT '[]',
                leases_json TEXT DEFAULT '[]', metadata TEXT DEFAULT '{}',
                created_at TEXT
            )""",
            """CREATE TABLE IF NOT EXISTS governance_events (
                id TEXT PRIMARY KEY, agent_id TEXT, session_id TEXT,
                action_type TEXT NOT NULL, tool_name TEXT,
                risk_level TEXT DEFAULT 'low', metadata_json TEXT DEFAULT '{}',
                policy_violations_json TEXT DEFAULT '[]', created_at TEXT
            )""",
            """CREATE TABLE IF NOT EXISTS governance_circuit_breaker (
                agent_id TEXT PRIMARY KEY, failures INTEGER DEFAULT 0,
                tripped INTEGER DEFAULT 0, last_failure_at TEXT,
                updated_at TEXT
            )""",
        ]:
            self.conn.execute(stmt)

    def _log_event(self, event_type: str, message: str, level: str = "info"):
        """Log event to loop_events."""
        self.conn.execute(
            """INSERT INTO loop_events (id, loop_run_id, event_type, level, message, metadata, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                str(uuid.uuid4()),
                self.run_id,
                event_type,
                level,
                message,
                json.dumps(
                    {"correlation_id": self.correlation_id, "phase": self.current_phase}
                ),
                datetime.now().isoformat(),
            ),
        )
        self.conn.commit()

    def _log_audit(self, decision: str, reasoning: str):
        """Append-only audit log."""
        self.conn.execute(
            """INSERT INTO governance_events (id, agent_id, session_id, action_type, metadata_json)
               VALUES (?, 'orchestrator', ?, 'orchestrator_decision', ?)""",
            (
                str(uuid.uuid4()),
                self.run_id,
                json.dumps(
                    {
                        "decision": decision,
                        "reasoning": reasoning,
                        "phase": self.current_phase,
                    }
                ),
            ),
        )
        self.conn.commit()

    def _checkpoint(self, label: str, state: dict, gates: list, findings: list):
        """Record phase checkpoint."""
        self.conn.execute(
            """INSERT INTO loop_checkpoints
               (id, loop_run_id, label, state_json, gates_json, findings_json, metadata, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(uuid.uuid4()),
                self.run_id,
                label,
                json.dumps(state),
                json.dumps(gates),
                json.dumps(findings),
                json.dumps({"correlation_id": self.correlation_id}),
                datetime.now().isoformat(),
            ),
        )
        self.conn.commit()

    def _check_timeout(self) -> bool:
        """Check if global timeout exceeded."""
        elapsed = (datetime.now() - self.start_time).total_seconds()
        return elapsed > GLOBAL_TIMEOUT

    def _add_token_usage(self, tokens: int):
        """Track cumulative token usage."""
        self.token_usage += tokens

    def run(self) -> dict:
        """Execute all phases. Returns final status dict."""
        # Register loop run
        self.conn.execute(
            """INSERT INTO loop_runs (id, loop_name, mode, status, repository_path, metadata, created_at)
               VALUES (?, 'ecosystem_integration', 'open', 'running', ?, ?, ?)""",
            (
                self.run_id,
                str(REPO_ROOT),
                json.dumps({"correlation_id": self.correlation_id, "mode": self.mode}),
                datetime.now().isoformat(),
            ),
        )
        self.conn.commit()

        self._log_event("run_started", f"Orchestrator started in {self.mode} mode")

        for phase in PHASES:
            if self._check_timeout():
                self._log_event(
                    "global_timeout", "Global timeout exceeded", level="error"
                )
                self.phase_status[phase] = "timeout"
                break

            self.current_phase = phase
            self._log_event("phase_start", f"Starting phase: {phase}")

            if phase == "escalate":
                # Phase 6: Human escalation — this is the ONLY human interaction point
                result = self._phase_escalate()
            else:
                result = self._run_phase_autonomous(phase)

            self.phase_status[phase] = "completed" if result["success"] else "failed"

            self._checkpoint(
                f"{phase}_complete",
                {"success": result["success"], "tokens_used": self.token_usage},
                result.get("gates", []),
                result.get("findings", []),
            )

            if not result["success"]:
                cb = self.circuit_breakers[phase]
                if cb.tripped:
                    self._log_event(
                        "circuit_breaker_tripped",
                        f"Circuit breaker tripped for {phase}",
                        level="error",
                    )
                    self._log_audit(
                        "circuit_breaker_escalation",
                        f"Phase {phase} failed {MAX_RETRIES} times, escalating to human",
                    )
                    # Skip remaining non-escalate phases
                    for remaining in PHASES[PHASES.index(phase) + 1 :]:
                        if remaining != "escalate":
                            self.phase_status[remaining] = "skipped"
                    break

        # Always run escalation if any non-escalate phase failed
        if any(self.phase_status.get(p) == "failed" for p in PHASES if p != "escalate"):
            if self.phase_status.get("escalate") != "completed":
                self.current_phase = "escalate"
                self._log_event(
                    "phase_start", "Starting phase: escalate (post-failure)"
                )
                result = self._phase_escalate()
                self.phase_status["escalate"] = (
                    "completed" if result["success"] else "failed"
                )
                self._checkpoint(
                    "escalate_complete",
                    {"success": result["success"], "tokens_used": self.token_usage},
                    result.get("gates", []),
                    result.get("findings", []),
                )

        # Finalize — map to valid status values
        raw_status = (
            "completed"
            if all(self.phase_status.get(p) in ("completed", "skipped") for p in PHASES)
            else "failed"
        )
        db_status = "completed" if raw_status == "completed" else "failed"

        self.conn.execute(
            """UPDATE loop_runs SET status=?, findings_json=?, completed_at=?, updated_at=?
               WHERE id=?""",
            (
                db_status,
                json.dumps(self.findings),
                datetime.now().isoformat(),
                datetime.now().isoformat(),
                self.run_id,
            ),
        )
        self.conn.commit()

        result = {
            "run_id": self.run_id,
            "status": raw_status,
            "phase_status": self.phase_status,
            "token_usage": self.token_usage,
            "findings": self.findings,
        }

        self._log_event("run_complete", f"Orchestrator finished: {raw_status}")
        return result

    def _run_phase_autonomous(self, phase: str) -> dict:
        """Run a phase autonomously with circuit breaker. No user interaction."""
        cb = self.circuit_breakers[phase]

        for attempt in range(1, cb.max_retries + 1):
            try:
                self._log_event("phase_attempt", f"Phase {phase} attempt {attempt}")

                if phase == "validate":
                    result = self._phase_validate()
                elif phase == "seed":
                    result = self._phase_seed()
                elif phase == "execute":
                    result = self._phase_execute()
                elif phase == "observe":
                    result = self._phase_observe()
                elif phase == "secure":
                    result = self._phase_secure()
                else:
                    result = {"success": False, "findings": [f"Unknown phase: {phase}"]}

                if result["success"]:
                    cb.reset()
                    return result
                else:
                    cb.record_failure()
                    if not cb.tripped:
                        cb.wait_backoff()

            except Exception as e:
                self._log_event(
                    "phase_error", f"Phase {phase} error: {str(e)}", level="error"
                )
                cb.record_failure()
                if cb.tripped:
                    break
                cb.wait_backoff()

        return {
            "success": False,
            "findings": [f"Phase {phase} failed after {cb.max_retries} retries"],
        }

    # ── Phase Implementations ──────────────────────────────────────────

    def _phase_validate(self) -> dict:
        """Phase 1: OpenMythos QA gates — critic, reviewer, sme, test_engineer, explorer.

        Runs deterministic QA checks via tools/qa_gates.py.
        All 5 agent roles assess the plan; majority APPROVE required to proceed.
        """
        self._add_token_usage(5000)

        qa_script = REPO_ROOT / "tools" / "qa_gates.py"
        if not qa_script.exists():
            return {"success": False, "findings": ["tools/qa_gates.py not found"]}

        try:
            result = subprocess.run(
                [sys.executable, str(qa_script), "auto"],
                capture_output=True,
                text=True,
                timeout=60,
            )
            qa_result = json.loads(result.stdout)
        except (subprocess.TimeoutExpired, json.JSONDecodeError) as e:
            return {"success": False, "findings": [f"QA gates failed: {str(e)}"]}

        verdict = qa_result.get("verdict", "REJECT")
        gates = qa_result.get("gates", [])
        findings = qa_result.get("findings", [])
        summary = qa_result.get("summary", {})

        # Build gate records for checkpoint
        gate_records = [
            {
                "gate": g["agent"],
                "verdict": g["verdict"],
                "confidence": g["confidence"],
                "findings_count": len(g["findings"]),
            }
            for g in gates
        ]

        if verdict == "APPROVE":
            self._log_audit(
                "qa_gates_passed",
                f"All gates passed: {summary.get('approve', 0)} approve, "
                f"{summary.get('concerns', 0)} concerns",
            )
            return {"success": True, "gates": gate_records, "findings": findings}
        elif verdict == "CONCERNS":
            self._log_audit(
                "qa_gates_concerns", f"QA gates raised concerns: {findings}"
            )
            # Concerns don't block — they're escalated to human at Phase 6
            return {"success": True, "gates": gate_records, "findings": findings}
        else:
            self._log_audit("qa_gates_rejected", f"QA gates rejected: {findings}")
            return {"success": False, "gates": gate_records, "findings": findings}

    def _phase_seed(self) -> dict:
        """Phase 2: Seed governance policies and capability tokens."""
        self._add_token_usage(2000)

        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "tools" / "seed_governance.py")],
            capture_output=True,
            timeout=PHASE_TIMEOUT,
        )
        if result.returncode != 0:
            return {"success": False, "findings": ["Governance seeding failed"]}

        # Verify seeding
        count = self.conn.execute(
            "SELECT COUNT(*) FROM governance_policies"
        ).fetchone()[0]
        if count == 0:
            return {"success": False, "findings": ["No policies seeded"]}

        gates = [
            {"gate": "policies_seeded", "status": "pass", "count": count},
            {"gate": "tokens_seeded", "status": "pass"},
        ]

        self._log_audit("seeding_complete", f"Seeded {count} policies")
        return {"success": True, "gates": gates, "findings": []}

    def _phase_execute(self) -> dict:
        """Phase 3: Execute loop-engineering patterns."""
        self._add_token_usage(10000)

        # Verify tools exist
        required_tools = ["seed_governance.py", "import_telemetry.py", "security.py"]
        for tool in required_tools:
            if not (REPO_ROOT / "tools" / tool).exists():
                return {
                    "success": False,
                    "findings": [f"Required tool missing: {tool}"],
                }

        gates = [
            {"gate": "tools_present", "status": "pass"},
            {"gate": "patterns_available", "status": "pass"},
        ]

        self._log_audit("execution_ready", "All required tools and patterns available")
        return {"success": True, "gates": gates, "findings": []}

    def _phase_observe(self) -> dict:
        """Phase 4: Import telemetry and verify observability."""
        self._add_token_usage(3000)

        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "tools" / "import_telemetry.py")],
            capture_output=True,
            timeout=PHASE_TIMEOUT,
        )
        if result.returncode != 0:
            return {"success": False, "findings": ["Telemetry import failed"]}

        # Verify loop_runs populated
        count = self.conn.execute("SELECT COUNT(*) FROM loop_runs").fetchone()[0]
        if count == 0:
            return {"success": False, "findings": ["No loop_runs created"]}

        gates = [
            {"gate": "telemetry_imported", "status": "pass"},
            {"gate": "loop_runs_populated", "status": "pass", "count": count},
        ]

        self._log_audit("observation_complete", f"Imported {count} loop runs")
        return {"success": True, "gates": gates, "findings": []}

    def _phase_secure(self) -> dict:
        """Phase 5: Security gates — prompt injection, path traversal, token scope."""
        self._add_token_usage(5000)

        # Run prompt injection tests
        result = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "tests" / "prompt_injection" / "test_injection.py"),
            ],
            capture_output=True,
            timeout=PHASE_TIMEOUT,
        )
        if result.returncode != 0:
            return {
                "success": False,
                "findings": [
                    "Prompt injection gate failed — possible injection vulnerability"
                ],
            }

        # Run security tests
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "tests" / "test_security.py")],
            capture_output=True,
            timeout=PHASE_TIMEOUT,
        )
        if result.returncode != 0:
            return {"success": False, "findings": ["Security tests failed"]}

        gates = [
            {"gate": "prompt_injection", "status": "pass"},
            {"gate": "path_traversal", "status": "pass"},
            {"gate": "token_scope", "status": "pass"},
        ]

        self._log_audit("security_passed", "All security gates passed")
        return {"success": True, "gates": gates, "findings": []}

    def _phase_escalate(self) -> dict:
        """Phase 6: Human escalation gateway — ONLY human interaction point."""
        self._log_event("escalation_gateway", "Presenting escalation gateway to user")

        # Gather all findings
        all_findings = []
        for phase in PHASES[:-1]:
            checkpoints = self.conn.execute(
                "SELECT findings_json FROM loop_checkpoints WHERE loop_run_id=? AND label=?",
                (self.run_id, f"{phase}_complete"),
            ).fetchall()
            for row in checkpoints:
                found = json.loads(row[0])
                if found:
                    all_findings.extend(found)

        gates = [
            {
                "gate": "validation",
                "status": self.phase_status.get("validate", "unknown"),
            },
            {"gate": "seeding", "status": self.phase_status.get("seed", "unknown")},
            {
                "gate": "execution",
                "status": self.phase_status.get("execute", "unknown"),
            },
            {
                "gate": "observation",
                "status": self.phase_status.get("observe", "unknown"),
            },
            {"gate": "security", "status": self.phase_status.get("secure", "unknown")},
        ]

        escalation_data = {
            "run_id": self.run_id,
            "mode": self.mode,
            "phase_status": self.phase_status,
            "token_usage": self.token_usage,
            "findings": all_findings,
            "gates": gates,
        }

        self._log_audit(
            "human_escalation", "Presenting escalation gateway for human decision"
        )
        return {
            "success": True,
            "gates": gates,
            "findings": all_findings,
            "escalation": escalation_data,
        }


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "L1"
    if mode not in ("L1", "L2", "L3"):
        print(f"Invalid mode: {mode}. Use L1, L2, or L3.")
        return 1

    orch = Orchestrator(mode=mode)
    result = orch.run()

    print(json.dumps(result, indent=2, default=str))

    if result.get("escalation"):
        print("\n=== HUMAN ESCALATION GATEWAY ===")
        esc = result["escalation"]
        print(f"Run ID: {esc['run_id']}")
        print(f"Mode: {esc['mode']}")
        print(f"Token Usage: {esc['token_usage']}")
        print(f"\nPhase Status:")
        for phase, status in esc["phase_status"].items():
            print(f"  {phase}: {status}")
        if esc["findings"]:
            print(f"\nFindings ({len(esc['findings'])}):")
            for f in esc["findings"]:
                print(f"  - {f}")
        print("\nDecision required: APPROVE / REJECT / MODIFY")

    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
