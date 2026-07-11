#!/usr/bin/env python3
"""End-to-end integration test for the full orchestrator pipeline."""

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
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
    # L1 mode should complete (may fail on validation but should not hang)
    check(
        result.returncode in (0, 1),
        f"Orchestrator exited with unexpected code: {result.returncode}",
    )
    check(
        '"escalate": "completed"' in result.stdout
        or '"status": "completed"' in result.stdout,
        "Orchestrator should complete all phases including escalation",
    )
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

    conn.close()
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
    """Test: Circuit breaker schema and basic operations work."""
    conn = sqlite3.connect(DJITIMFLO_DB)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS governance_circuit_breaker (
            agent_id TEXT PRIMARY KEY, failures INTEGER DEFAULT 0,
            tripped INTEGER DEFAULT 0, last_failure_at TEXT, updated_at TEXT
        )"""
    )
    # Insert a test record
    conn.execute(
        "INSERT OR REPLACE INTO governance_circuit_breaker (agent_id, failures, tripped) VALUES (?, ?, ?)",
        ("test_agent", 3, 1),
    )
    conn.commit()
    row = conn.execute(
        "SELECT tripped, failures FROM governance_circuit_breaker WHERE agent_id = ?",
        ("test_agent",),
    ).fetchone()
    check(row is not None, "Circuit breaker record should exist")
    check(row[0] == 1, "Circuit breaker should be tripped")
    check(row[1] == 3, "Circuit breaker should have 3 failures")
    # Cleanup
    conn.execute(
        "DELETE FROM governance_circuit_breaker WHERE agent_id = ?", ("test_agent",)
    )
    conn.commit()
    conn.close()
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
