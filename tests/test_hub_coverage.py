#!/usr/bin/env python3
"""Hub-coverage tests: direct semantic tests for high-degree hub functions.

The graph audit flagged generate_summary (degree 39), Orchestrator.run (34),
import_telemetry (34), record_decision (25), request_escalation (18) as
untested hotspots. These tests exercise their contracts directly with
temporary databases — no external services.
"""

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "tools"))

_owns_db = "LOOP_DB_PATH" not in os.environ
if _owns_db:
    _db_fd, _db_path = tempfile.mkstemp(suffix=".sqlite", prefix="hub_cov_")
    os.close(_db_fd)
    os.environ["LOOP_DB_PATH"] = _db_path

from config import ensure_schema  # noqa: E402

import escalation_gateway  # noqa: E402
from escalation_gateway import (  # noqa: E402
    expire_pending_decision,
    generate_summary,
    record_decision,
    request_escalation,
)
from import_telemetry import import_telemetry  # noqa: E402
from loop_orchestrator import Orchestrator  # noqa: E402
from seed_governance import (  # noqa: E402
    parse_constraints,
    seed_capability_tokens,
    seed_policies,
)

DB_PATH = os.environ["LOOP_DB_PATH"]


def _make_run(conn, run_id="hub-run-1", status="running"):
    conn.execute(
        """INSERT OR IGNORE INTO loop_runs
           (id, loop_name, mode, status, metadata, findings_json, created_at)
           VALUES (?, 'hub-test', 'open', ?, '{}', '[]', datetime('now'))""",
        (run_id, status),
    )
    conn.commit()


class HubCoverageTestCase(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(DB_PATH)
        ensure_schema(self.conn)

    def tearDown(self):
        self.conn.close()

    # ── request_escalation ────────────────────────────────────────────

    def test_request_escalation_is_idempotent(self):
        _make_run(self.conn, "esc-1")
        first = request_escalation(self.conn, "esc-1")
        second = request_escalation(self.conn, "esc-1")
        self.assertEqual(first["decision"], "pending")
        self.assertEqual(first, second)
        count = self.conn.execute(
            """SELECT COUNT(*) FROM governance_events
               WHERE session_id='esc-1' AND action_type='human_escalation_requested'"""
        ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_request_escalation_sets_deadline(self):
        _make_run(self.conn, "esc-2")
        payload = request_escalation(self.conn, "esc-2")
        expires = datetime.fromisoformat(payload["expires_at"])
        requested = datetime.fromisoformat(payload["requested_at"])
        self.assertGreaterEqual(expires - requested, timedelta(hours=71))

    def test_request_escalation_rejects_missing_run(self):
        with self.assertRaises(ValueError):
            request_escalation(self.conn, "no-such-run")

    # ── record_decision ───────────────────────────────────────────────

    def test_record_decision_exact_once(self):
        _make_run(self.conn, "dec-1")
        request_escalation(self.conn, "dec-1")
        payload = record_decision("dec-1", "approve", "looks good")
        self.assertEqual(payload["decision"], "approve")
        with self.assertRaises(ValueError):
            record_decision("dec-1", "approve", "double tap")
        status = self.conn.execute(
            "SELECT status FROM loop_runs WHERE id='dec-1'"
        ).fetchone()[0]
        self.assertEqual(status, "completed")

    def test_record_decision_reject_trips_breaker(self):
        _make_run(self.conn, "dec-2")
        record_decision("dec-2", "reject", "bad output")
        tripped = self.conn.execute(
            "SELECT tripped FROM governance_circuit_breaker WHERE agent_id LIKE 'run_dec-2%'"
        ).fetchone()[0]
        self.assertEqual(tripped, 1)

    def test_record_decision_invalid_choice(self):
        _make_run(self.conn, "dec-3")
        with self.assertRaises(ValueError):
            record_decision("dec-3", "maybe")

    def test_record_decision_unknown_run(self):
        with self.assertRaises(ValueError):
            record_decision("ghost", "approve")

    # ── expire_pending_decision ───────────────────────────────────────

    def test_expired_escalation_auto_rejects(self):
        _make_run(self.conn, "exp-1")
        request_escalation(self.conn, "exp-1")
        # force expiration by backdating request and deadline
        old = (datetime.now().astimezone() - timedelta(hours=73)).isoformat()
        self.conn.execute(
            """UPDATE governance_events
               SET created_at=?,
                   metadata_json=json_set(metadata_json,
                     '$.requested_at', ?, '$.expires_at', ?)
               WHERE session_id='exp-1'""",
            (old, old, old),
        )
        self.conn.commit()
        rejected = expire_pending_decision("exp-1")
        self.assertTrue(rejected)
        decision = self.conn.execute(
            """SELECT COUNT(*) FROM governance_events
               WHERE session_id='exp-1' AND action_type='human_decision'"""
        ).fetchone()[0]
        self.assertEqual(decision, 1)

    def test_live_escalation_not_expired(self):
        _make_run(self.conn, "exp-2")
        request_escalation(self.conn, "exp-2")
        self.assertFalse(expire_pending_decision("exp-2"))

    # ── generate_summary ──────────────────────────────────────────────

    def test_generate_summary_full_projection(self):
        _make_run(self.conn, "sum-1")
        request_escalation(self.conn, "sum-1")
        record_decision("sum-1", "approve", "ok")
        summary = generate_summary("sum-1")
        self.assertEqual(summary["run_id"], "sum-1")
        self.assertEqual(summary["status"], "completed")
        self.assertEqual(summary["decision"]["decision"], "approve")
        self.assertIsNotNone(summary["escalation"])

    def test_generate_summary_unknown_run(self):
        summary = generate_summary("niet-bestaand")
        self.assertIn("error", summary)

    # ── import_telemetry ──────────────────────────────────────────────

    def test_import_telemetry_full_and_incremental(self):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as tf:
            path = Path(tf.name)
            for i in range(5):
                tf.write(
                    json.dumps(
                        {
                            "timestamp": f"2026-08-29T2{i}:00:00Z",
                            "event": "heartbeat",
                            "sessionId": f"ses-{i % 2}",
                            "agentName": "tester",
                        }
                    )
                    + "\n"
                )
        try:
            stats1 = import_telemetry(self.conn, path)
            self.assertEqual(stats1["imported"], 5)
            self.assertEqual(stats1["runs_created"], 2)
            # idempotent full re-import
            stats2 = import_telemetry(self.conn, path)
            self.assertEqual(stats2["imported"], 0)
            # incremental: append two lines, import from offset
            with path.open("a") as f:
                f.write(
                    json.dumps(
                        {
                            "timestamp": "2026-08-29T23:00:00Z",
                            "event": "heartbeat",
                            "sessionId": "ses-0",
                            "agentName": "tester",
                        }
                    )
                    + "\n"
                )
                f.write(
                    json.dumps(
                        {
                            "timestamp": "2026-08-29T23:01:00Z",
                            "event": "heartbeat",
                            "sessionId": "ses-0",
                            "agentName": "tester",
                        }
                    )
                    + "\n"
                )
            stats2 = import_telemetry(self.conn, path, stats1["next_offset"])
            self.assertEqual(stats2["imported"], 2)
            # partial final line is NOT consumed (offset stays behind it)
            with path.open("a") as f:
                f.write('{"timestamp": "2026-08-29T23:')
            stats3 = import_telemetry(self.conn, path, stats2["next_offset"])
            self.assertEqual(stats3["imported"], 0)
            back = stats3["next_offset"]
            self.assertEqual(back, stats2["next_offset"])
        finally:
            path.unlink()

    def test_import_telemetry_skips_corrupt_line(self):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as tf:
            path = Path(tf.name)
            tf.write('{"timestamp": "ok", "event": "heartbeat"}\n')
            tf.write("THIS IS NOT JSON\n")
            tf.write('{"timestamp": "ok2", "event": "heartbeat"}\n')
        try:
            stats = import_telemetry(self.conn, path)
            self.assertEqual(stats["imported"], 2)
            self.assertEqual(stats["skipped"], 1)
        finally:
            path.unlink()

    # ── seed_governance ───────────────────────────────────────────────

    def test_parse_constraints_and_seed_policies(self):
        constraints = parse_constraints(_REPO / "loop-constraints.md")
        self.assertGreaterEqual(len(constraints), 5)
        ids = [c["id"] for c in constraints]
        self.assertIn("no-auto-merge-main", ids)
        self.assertIn("no-secrets-in-prompts", ids)
        n1 = seed_policies(self.conn, constraints)
        n2 = seed_policies(self.conn, constraints)
        self.assertEqual(n2, 0)  # second run: zero new (update path)
        total = self.conn.execute(
            "SELECT COUNT(*) FROM governance_policies"
        ).fetchone()[0]
        self.assertGreaterEqual(total, 8)

    def test_seed_capability_tokens_idempotent(self):
        n1 = seed_capability_tokens(self.conn)
        n2 = seed_capability_tokens(self.conn)
        self.assertEqual(n2, 0)  # second run: update path, zero new
        refs = [
            r[0]
            for r in self.conn.execute(
                "SELECT token_ref FROM capability_tokens"
            ).fetchall()
        ]
        self.assertIn("loop-L1-token", refs)

    # ── Orchestrator hub paths ────────────────────────────────────────

    def test_orchestrator_budget_cap_enforced(self):
        orch = Orchestrator("L1", db_path=DB_PATH)
        try:
            from loop_orchestrator import BudgetExceeded

            orch.token_usage = 9900  # L1 cap = 10000
            with self.assertRaises(BudgetExceeded):
                orch._consume_budget("secure")  # costs 2000
        finally:
            orch.close()

    def test_orchestrator_expired_token_fails_closed(self):
        orch = Orchestrator("L1", db_path=DB_PATH)
        try:
            past = (datetime.now() - timedelta(hours=48)).isoformat() + "Z"
            orch.conn.execute(
                "UPDATE capability_tokens SET expires_at=?, status='active'"
                " WHERE token_ref='loop-L1-token'",
                (past,),
            )
            orch.conn.commit()
            with self.assertRaises(PermissionError):
                orch._authorize("read")
        finally:
            orch.close()

    def test_orchestrator_unknown_mode_rejected(self):
        with self.assertRaises(ValueError):
            Orchestrator("L9", db_path=DB_PATH)

    def test_orchestrator_scope_gate_rejects_out_of_scope(self):
        """L1 grants only 'read'; requesting a mutually-exclusive scope
        outside the mode's scope list must raise (mutationcanary: scope gate)."""
        orch = Orchestrator("L1", db_path=DB_PATH)
        try:
            self.assertNotIn("merge", orch.mode_config["scopes"])
            with self.assertRaises(PermissionError):
                orch._authorize("merge")
        finally:
            orch.close()

    def test_orchestrator_run_reaches_awaiting_human(self):
        """Full happy-path run: 5 autonomous phases then escalation.

        Uses a private DB so the shared temp DB's token_usage totals
        (asserted by other suites) are not disturbed.
        """
        private_fd, private_db = tempfile.mkstemp(suffix=".sqlite", prefix="hub_orch_")
        os.close(private_fd)
        orch = Orchestrator("L1", db_path=private_db)
        try:
            result = orch.run()
            self.assertEqual(result["status"], "awaiting_human")
            self.assertEqual(result["autonomous_status"], "completed")
            self.assertLessEqual(result["token_usage"], result["budget_cap"])
            for phase, state in result["phase_status"].items():
                self.assertIn(state, ("completed", "awaiting_human"))
        finally:
            orch.close()
            os.unlink(private_db)


if __name__ == "__main__":
    unittest.main()
