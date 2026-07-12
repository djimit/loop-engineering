#!/usr/bin/env python3
"""End-to-end integration test for the full orchestrator pipeline."""

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

_fd, _tmp_db = tempfile.mkstemp(suffix=".sqlite", prefix="loop_test_")
os.close(_fd)
os.environ["LOOP_DB_PATH"] = _tmp_db
DJITIMFLO_DB = _tmp_db
REPO_ROOT = Path(__file__).parent.parent


def check(condition, msg):
    if not condition:
        raise AssertionError(msg)


def test_qa_gates_auto():
    """Test: QA gates run and produce structured verdicts."""
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "tools" / "qa_gates.py"), "auto"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    check(result.returncode == 0, f"QA gates should pass: {result.stdout}")
    data = json.loads(result.stdout)
    check(
        data["verdict"] in ("APPROVE", "CONCERNS"),
        f"Verdict should be APPROVE or CONCERNS, got {data['verdict']}",
    )
    check(
        len(data["gates"]) == 5, f"Expected 5 gate verdicts, got {len(data['gates'])}"
    )
    return True


def test_qa_gates_dispatch():
    """Test: QA gates generate dispatch manifest."""
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "tools" / "qa_gates.py"), "dispatch"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    check(result.returncode == 0, f"Dispatch should succeed: {result.stdout}")
    import json as _json

    data = _json.loads(result.stdout)
    check(data["verdict"] == "DISPATCH", "Dispatch mode should return DISPATCH verdict")
    check(data["roles"] == 5, f"Expected 5 roles, got {data['roles']}")
    check(
        os.path.exists(data["manifest"]),
        f"Manifest file should exist: {data['manifest']}",
    )
    return True


def test_autonomous_execution():
    """Test: Orchestrator runs phases 1-5 without user interaction."""
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "tools" / "loop_orchestrator.py"), "L1"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    check(result.returncode == 0, result.stderr or result.stdout)
    data = json.loads(result.stdout.split("\n\nDecision required", 1)[0])
    check(data["autonomous_status"] == "completed", data)
    check(data["status"] == "awaiting_human", data)
    check(data["phase_status"]["escalate"] == "awaiting_human", data)
    check(data["token_usage"] <= data["budget_cap"], data)
    check(data["escalation"]["decision"] == "pending", data)
    return True


def test_djitimflo_tables_populated():
    """Test: All required Djitimflo tables have data after orchestration."""
    conn = sqlite3.connect(DJITIMFLO_DB)

    policies = conn.execute("SELECT COUNT(*) FROM governance_policies").fetchone()[0]
    check(policies > 0, "governance_policies should have records")

    tokens = conn.execute("SELECT COUNT(*) FROM capability_tokens").fetchone()[0]
    check(tokens > 0, "capability_tokens should have records")

    runs = conn.execute("SELECT COUNT(*) FROM loop_runs").fetchone()[0]
    check(runs > 0, "loop_runs should have records")

    events = conn.execute("SELECT COUNT(*) FROM loop_events").fetchone()[0]
    check(events > 0, "loop_events should have records")

    gov_events = conn.execute("SELECT COUNT(*) FROM governance_events").fetchone()[0]
    check(gov_events > 0, "governance_events should have records")

    usage = conn.execute("SELECT SUM(total_tokens) FROM token_usage_log").fetchone()[0]
    check(usage == 8000, f"Expected 8000 logged tokens, got {usage}")

    escalation = conn.execute(
        "SELECT COUNT(*) FROM governance_events WHERE action_type='human_escalation_requested'"
    ).fetchone()[0]
    check(escalation == 1, f"Expected one escalation request, got {escalation}")

    conn.close()
    return True


def test_telemetry_import_is_idempotent():
    """Test: re-importing the same source creates no duplicate events."""
    sys.path.insert(0, str(REPO_ROOT / "tools"))
    from import_telemetry import import_telemetry

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "telemetry.jsonl"
        path.write_text(
            '{"event":"session_started","sessionId":"s1","agentName":"test"}\n'
            '{"event":"heartbeat","sessionId":"s1","agentName":"test"}\n'
        )
        conn = sqlite3.connect(DJITIMFLO_DB)
        first = import_telemetry(conn, path)
        second = import_telemetry(conn, path)
        with path.open("a") as telemetry:
            telemetry.write(
                '{"event":"agent_activated","sessionId":"s1","agentName":"test"}\n'
            )
        appended = import_telemetry(conn, path, first["next_offset"])
        conn.commit()
        conn.close()
    check(first["imported"] == 2, first)
    check(second["imported"] == 0, second)
    check(appended["imported"] == 1, appended)
    return True


def test_budget_enforcement():
    """Test: a phase cannot exceed the selected mode budget."""
    sys.path.insert(0, str(REPO_ROOT / "tools"))
    from loop_orchestrator import BudgetExceeded, Orchestrator

    orchestrator = Orchestrator("L1", DJITIMFLO_DB)
    orchestrator.token_usage = orchestrator.budget_cap
    try:
        try:
            orchestrator._consume_budget("validate")
        except BudgetExceeded:
            return True
        raise AssertionError("Budget overrun should be rejected")
    finally:
        orchestrator.close()


def test_final_human_decision():
    """Test: the final gateway reads the schema and records one human decision."""
    sys.path.insert(0, str(REPO_ROOT / "tools"))
    from escalation_gateway import generate_summary, record_decision

    conn = sqlite3.connect(DJITIMFLO_DB)
    run_id = conn.execute(
        "SELECT id FROM loop_runs WHERE status='escalated' ORDER BY created_at DESC"
    ).fetchone()[0]
    conn.close()
    summary = generate_summary(run_id)
    check(summary["escalation"]["decision"] == "pending", summary)
    check(summary["token_usage"] == 8000, summary)
    record_decision(run_id, "approve", "integration test")
    check(generate_summary(run_id)["status"] == "completed", "Decision not applied")
    try:
        record_decision(run_id, "reject", "second decision")
    except ValueError:
        return True
    raise AssertionError("A second decision should be rejected")


def test_escalation_timeout():
    """Test: an expired final decision is automatically rejected."""
    sys.path.insert(0, str(REPO_ROOT / "tools"))
    from escalation_gateway import expire_pending_decision, request_escalation

    conn = sqlite3.connect(DJITIMFLO_DB)
    run_id = "expired-run"
    conn.execute(
        """INSERT INTO loop_runs (id, loop_name, mode, status, created_at)
           VALUES (?, 'test', 'open', 'running', ?)""",
        (run_id, datetime.now().astimezone().isoformat()),
    )
    request = request_escalation(conn, run_id)
    conn.close()
    future = datetime.fromisoformat(request["expires_at"]) + timedelta(seconds=1)
    check(expire_pending_decision(run_id, future), "Expired request was not rejected")
    conn = sqlite3.connect(DJITIMFLO_DB)
    status = conn.execute("SELECT status FROM loop_runs WHERE id=?", (run_id,)).fetchone()[0]
    conn.close()
    check(status == "cancelled", status)
    return True


def test_prompt_injection_gate():
    """Test: Prompt injection gate correctly fails on adversarial input."""
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "tests" / "prompt_injection" / "test_injection.py"),
        ],
        capture_output=True,
        text=True,
    )
    check(
        result.returncode == 0, f"Prompt injection tests should pass: {result.stdout}"
    )
    check("5/5 passed" in result.stdout, "All 5 injection tests should pass")
    return True


def test_circuit_breaker():
    """Test: three phase failures skip unsafe work and reach the final gate."""
    sys.path.insert(0, str(REPO_ROOT / "tools"))
    import loop_orchestrator

    orchestrator = loop_orchestrator.Orchestrator("L1", DJITIMFLO_DB)
    calls = 0

    def fail_validation():
        nonlocal calls
        calls += 1
        return {"success": False, "findings": ["forced failure"]}

    original_sleep = loop_orchestrator.time.sleep
    loop_orchestrator.time.sleep = lambda _seconds: None
    orchestrator._phase_validate = fail_validation
    try:
        result = orchestrator.run()
    finally:
        orchestrator.close()
        loop_orchestrator.time.sleep = original_sleep

    check(calls == 3, f"Expected 3 attempts, got {calls}")
    check(result["autonomous_status"] == "failed", result)
    check(result["phase_status"]["validate"] == "failed", result)
    check(result["phase_status"]["seed"] == "skipped", result)
    check(result["phase_status"]["escalate"] == "awaiting_human", result)
    conn = sqlite3.connect(DJITIMFLO_DB)
    state = json.loads(
        conn.execute(
            "SELECT state_json FROM loop_checkpoints WHERE loop_run_id=?",
            (result["run_id"],),
        ).fetchone()[0]
    )
    conn.close()
    check(state["attempts"] == 3, state)
    return True


def test_security_module():
    """Test: Security module path traversal and validation works."""
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "tests" / "test_security.py")],
        capture_output=True,
        text=True,
    )
    check(result.returncode == 0, f"Security tests should pass: {result.stdout}")
    check(
        "/12 passed" in result.stdout
        or "/11 passed" in result.stdout
        or "/10 passed" in result.stdout,
        "Security tests should pass",
    )
    return True


def main():
    tests = [
        ("security_module", test_security_module),
        ("prompt_injection_gate", test_prompt_injection_gate),
        ("qa_gates_auto", test_qa_gates_auto),
        ("qa_gates_dispatch", test_qa_gates_dispatch),
        ("autonomous_execution", test_autonomous_execution),
        ("djitimflo_tables_populated", test_djitimflo_tables_populated),
        ("telemetry_import_is_idempotent", test_telemetry_import_is_idempotent),
        ("budget_enforcement", test_budget_enforcement),
        ("final_human_decision", test_final_human_decision),
        ("escalation_timeout", test_escalation_timeout),
        ("circuit_breaker", test_circuit_breaker),
    ]

    passed = 0
    failed = 0

    try:
        for name, test_fn in tests:
            try:
                test_fn()
                passed += 1
                print(f"  [PASS] {name}")
            except (AssertionError, Exception) as e:
                failed += 1
                print(f"  [FAIL] {name}: {e}")
    finally:
        if os.path.exists(_tmp_db):
            os.unlink(_tmp_db)

    print(f"\nIntegration tests: {passed}/{passed + failed} passed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
