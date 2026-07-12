#!/usr/bin/env python3
"""Autonomous governance pipeline with one final human decision gate."""

import json
import os
import sqlite3
import subprocess
import sys
import time
import uuid
from datetime import datetime

from config import REPO_ROOT, ensure_schema, get_db_path
from escalation_gateway import request_escalation
from import_telemetry import TELEMETRY_FILE, import_telemetry
from qa_gates import run_qa_gates
from seed_governance import (
    CONSTRAINTS_FILE,
    detect_drift,
    parse_constraints,
    seed_capability_tokens,
    seed_policies,
)

DJITIMFLO_DB = get_db_path()
PHASE_TIMEOUT = int(os.environ.get("LOOP_PHASE_TIMEOUT", 1800))
GLOBAL_TIMEOUT = int(os.environ.get("LOOP_GLOBAL_TIMEOUT", 14400))
MAX_RETRIES = 3
PHASES = ["validate", "seed", "execute", "observe", "secure", "escalate"]
PHASE_COSTS = {
    "validate": 2000,
    "seed": 1000,
    "execute": 2000,
    "observe": 1000,
    "secure": 2000,
}


class BudgetExceeded(RuntimeError):
    pass


class CircuitBreaker:
    def __init__(self, max_retries: int = MAX_RETRIES):
        self.max_retries = max_retries
        self.failures = 0

    @property
    def tripped(self) -> bool:
        return self.failures >= self.max_retries

    def fail(self) -> None:
        self.failures += 1


class Orchestrator:
    """Run phases 1-5 without input and persist a phase-6 decision request."""

    def __init__(self, mode: str = "L1", db_path: str | None = None):
        config = json.loads(
            (REPO_ROOT / "tools" / "capability_config.json").read_text()
        )
        if mode not in config:
            raise ValueError(f"Invalid mode: {mode}")

        self.mode = mode
        self.mode_config = config[mode]
        self.budget_cap = int(self.mode_config["max_budget"])
        self.run_id = str(uuid.uuid4())
        self.correlation_id = str(uuid.uuid4())
        self.current_phase: str | None = None
        self.phase_status = {phase: "pending" for phase in PHASES}
        self.findings: list = []
        self.token_usage = 0
        self.pending_usage: list[tuple[str, int]] = []
        self.start_time = time.monotonic()
        self.circuit_breakers = {phase: CircuitBreaker() for phase in PHASES[:-1]}
        self.conn = sqlite3.connect(db_path or DJITIMFLO_DB)
        ensure_schema(self.conn)

    def close(self) -> None:
        self.conn.close()

    def _log_event(self, event_type: str, message: str, level: str = "info") -> None:
        self.conn.execute(
            """INSERT INTO loop_events
               (id, loop_run_id, event_type, level, message, metadata, created_at)
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
                datetime.now().astimezone().isoformat(),
            ),
        )
        self.conn.commit()

    def _log_audit(self, decision: str, reasoning: str) -> None:
        self.conn.execute(
            """INSERT INTO governance_events
               (id, agent_id, session_id, action_type, metadata_json, created_at)
               VALUES (?, 'orchestrator', ?, 'orchestrator_decision', ?, ?)""",
            (
                str(uuid.uuid4()),
                self.run_id,
                json.dumps(
                    {
                        "decision": decision,
                        "reasoning": reasoning,
                        "phase": self.current_phase,
                        "correlation_id": self.correlation_id,
                    }
                ),
                datetime.now().astimezone().isoformat(),
            ),
        )
        self.conn.commit()

    def _checkpoint(self, result: dict) -> None:
        self.conn.execute(
            """INSERT INTO loop_checkpoints
               (id, loop_run_id, label, state_json, gates_json,
                findings_json, metadata, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(uuid.uuid4()),
                self.run_id,
                f"{self.current_phase}_complete",
                json.dumps(
                    {
                        "success": result["success"],
                        "tokens_used": self.token_usage,
                        "budget_cap": self.budget_cap,
                        "attempts": min(
                            self.circuit_breakers[self.current_phase].failures + 1,
                            self.circuit_breakers[self.current_phase].max_retries,
                        ),
                    }
                ),
                json.dumps(result.get("gates", [])),
                json.dumps(result.get("findings", [])),
                json.dumps({"correlation_id": self.correlation_id}),
                datetime.now().astimezone().isoformat(),
            ),
        )
        self.conn.commit()

    def _token(self) -> tuple | None:
        return self.conn.execute(
            """SELECT id, scopes_json, status, expires_at, metadata
               FROM capability_tokens WHERE token_ref=?""",
            (f"loop-{self.mode}-token",),
        ).fetchone()

    def _authorize(self, scope: str = "read") -> None:
        if scope not in self.mode_config["scopes"]:
            raise PermissionError(f"Mode {self.mode} does not grant scope {scope}")
        token = self._token()
        if not token:
            return
        expires_at = datetime.fromisoformat(token[3].replace("Z", "+00:00"))
        if token[2] != "active" or expires_at <= datetime.now().astimezone():
            raise PermissionError(f"Capability token for {self.mode} is inactive or expired")
        if scope not in json.loads(token[1]):
            raise PermissionError(f"Capability token does not grant scope {scope}")

    def _write_usage(self, phase: str, tokens: int) -> None:
        token = self._token()
        if not token:
            self.pending_usage.append((phase, tokens))
            return
        self.conn.execute(
            """INSERT INTO token_usage_log
               (id, provider, model, task_type, total_tokens, metadata,
                timestamp, created_at, updated_at)
               VALUES (?, 'loop-engineering', ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(uuid.uuid4()),
                self.mode,
                f"phase_{phase}",
                tokens,
                json.dumps(
                    {
                        "run_id": self.run_id,
                        "correlation_id": self.correlation_id,
                        "capability_token_id": token[0],
                    }
                ),
                *(datetime.now().astimezone().isoformat(),) * 3,
            ),
        )
        self.conn.commit()

    def _consume_budget(self, phase: str) -> None:
        tokens = PHASE_COSTS[phase]
        if self.token_usage + tokens > self.budget_cap:
            raise BudgetExceeded(
                f"{self.mode} budget exceeded: "
                f"{self.token_usage + tokens}>{self.budget_cap}"
            )
        self._authorize("read")
        self.token_usage += tokens
        self._write_usage(phase, tokens)

    def _flush_pending_usage(self) -> None:
        pending, self.pending_usage = self.pending_usage, []
        for phase, tokens in pending:
            self._write_usage(phase, tokens)

    def _run_script(self, *parts: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, *parts],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=PHASE_TIMEOUT,
        )

    def _run_phase(self, phase: str) -> dict:
        breaker = self.circuit_breakers[phase]
        for attempt in range(1, breaker.max_retries + 1):
            started = time.monotonic()
            try:
                self._log_event("phase_attempt", f"Phase {phase} attempt {attempt}")
                result = getattr(self, f"_phase_{phase}")()
                if time.monotonic() - started > PHASE_TIMEOUT:
                    result = {
                        "success": False,
                        "findings": [f"Phase {phase} exceeded {PHASE_TIMEOUT}s timeout"],
                    }
                if result["success"]:
                    return result
                breaker.fail()
            except BudgetExceeded as error:
                breaker.failures = breaker.max_retries
                return {"success": False, "findings": [str(error)]}
            except (Exception, subprocess.TimeoutExpired) as error:
                breaker.fail()
                self._log_event("phase_error", str(error), "error")
            if not breaker.tripped:
                time.sleep(2 ** (attempt - 1))
        return {
            "success": False,
            "findings": [f"Phase {phase} failed after {breaker.max_retries} attempts"],
        }

    def run(self) -> dict:
        created_at = datetime.now().astimezone().isoformat()
        self.conn.execute(
            """INSERT INTO loop_runs
               (id, loop_name, mode, status, repository_path, metadata, created_at)
               VALUES (?, 'ecosystem_integration', 'open', 'running', ?, ?, ?)""",
            (
                self.run_id,
                str(REPO_ROOT),
                json.dumps(
                    {
                        "correlation_id": self.correlation_id,
                        "budget": self.budget_cap,
                        "capability_mode": self.mode,
                    }
                ),
                created_at,
            ),
        )
        self.conn.commit()
        self._log_event("run_started", f"Orchestrator started in {self.mode} mode")
        seed_capability_tokens(self.conn)
        self.conn.commit()
        self._log_audit(
            "capability_preflight", "Refreshed expiring capability tokens"
        )

        escalation_only = False
        escalation = None
        autonomous_status = "completed"
        for phase in PHASES:
            if phase != "escalate" and (
                escalation_only or time.monotonic() - self.start_time > GLOBAL_TIMEOUT
            ):
                if not escalation_only:
                    self.findings.append("Global timeout exceeded")
                    autonomous_status = "failed"
                    escalation_only = True
                self.phase_status[phase] = "skipped"
                continue

            self.current_phase = phase
            self._log_event("phase_start", f"Starting phase: {phase}")
            if phase == "escalate":
                if self.pending_usage:
                    seed_capability_tokens(self.conn)
                    self.conn.commit()
                    self._flush_pending_usage()
                escalation = request_escalation(self.conn, self.run_id)
                self.phase_status[phase] = "awaiting_human"
                self._log_audit("human_escalation", "Final human decision requested")
                continue

            result = self._run_phase(phase)
            self.phase_status[phase] = "completed" if result["success"] else "failed"
            self.findings.extend(result.get("findings", []))
            self._checkpoint(result)
            if not result["success"]:
                autonomous_status = "failed"
                escalation_only = True
                self._log_audit(
                    "circuit_breaker_escalation", f"Phase {phase} failed; escalating"
                )

        completed_at = datetime.now().astimezone().isoformat()
        self.conn.execute(
            """UPDATE loop_runs
               SET status='escalated', findings_json=?, completed_at=?, updated_at=?
               WHERE id=?""",
            (json.dumps(self.findings), completed_at, completed_at, self.run_id),
        )
        self.conn.commit()
        self._log_event("autonomous_run_complete", autonomous_status)
        return {
            "run_id": self.run_id,
            "status": "awaiting_human",
            "autonomous_status": autonomous_status,
            "phase_status": self.phase_status,
            "token_usage": self.token_usage,
            "budget_cap": self.budget_cap,
            "findings": self.findings,
            "escalation": escalation,
        }

    def _phase_validate(self) -> dict:
        self._consume_budget("validate")
        qa = run_qa_gates("auto")
        gates = [
            {
                "gate": item["agent"],
                "verdict": item["verdict"],
                "confidence": item["confidence"],
            }
            for item in qa.get("gates", [])
        ]
        return {
            "success": qa.get("verdict") in {"APPROVE", "CONCERNS"},
            "gates": gates,
            "findings": qa.get("findings", []),
        }

    def _phase_seed(self) -> dict:
        self._consume_budget("seed")
        constraints = parse_constraints(CONSTRAINTS_FILE)
        policy_count = seed_policies(self.conn, constraints)
        token_count = seed_capability_tokens(self.conn)
        drift = detect_drift(self.conn, REPO_ROOT / ".github" / "workflows")
        self.conn.commit()
        self._flush_pending_usage()
        token = self._token()
        return {
            "success": bool(constraints and token and not drift),
            "gates": [
                {"gate": "policies", "status": "pass", "created": policy_count},
                {"gate": "capability_token", "status": "pass", "created": token_count},
                {"gate": "constraint_drift", "status": "pass" if not drift else "fail"},
            ],
            "findings": drift,
        }

    def _phase_execute(self) -> dict:
        self._consume_budget("execute")
        token = self._token()
        self._log_audit("capability_authorized", f"{self.mode} read scope authorized")
        return {
            "success": token is not None,
            "gates": [
                {"gate": "capability_authorized", "status": "pass"},
                {
                    "gate": "budget",
                    "status": "pass",
                    "used": self.token_usage,
                    "cap": self.budget_cap,
                },
            ],
            "findings": [],
        }

    def _phase_observe(self) -> dict:
        self._consume_budget("observe")
        stats = import_telemetry(self.conn, TELEMETRY_FILE)
        self.conn.commit()
        return {
            "success": stats["skipped"] == 0,
            "gates": [
                {"gate": "telemetry_parse", "status": "pass", **stats},
                {"gate": "orchestrator_events", "status": "pass"},
            ],
            "findings": [],
        }

    def _phase_secure(self) -> dict:
        self._consume_budget("secure")
        scripts = [
            str(REPO_ROOT / "tests" / "test_security.py"),
            str(REPO_ROOT / "tests" / "prompt_injection" / "test_injection.py"),
        ]
        failures = []
        for script in scripts:
            result = self._run_script(script)
            if result.returncode:
                failures.append(result.stderr or result.stdout)
        self._authorize("read")
        return {
            "success": not failures,
            "gates": [
                {"gate": "prompt_injection", "status": "pass" if not failures else "fail"},
                {"gate": "path_validation", "status": "pass" if not failures else "fail"},
                {"gate": "token_scope", "status": "pass"},
            ],
            "findings": failures,
        }


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "L1"
    try:
        orchestrator = Orchestrator(mode)
    except ValueError as error:
        print(error)
        return 1
    try:
        result = orchestrator.run()
    finally:
        orchestrator.close()
    print(json.dumps(result, indent=2, default=str))
    print("\nDecision required at final gate: APPROVE / REJECT / MODIFY")
    return 0 if result["autonomous_status"] == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
