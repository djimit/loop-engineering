#!/usr/bin/env python3
"""Shared configuration for loop-engineering tools."""

import logging
import os
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent


def get_db_path() -> str:
    """Return database path from LOOP_DB_PATH env var or default."""
    return os.environ.get(
        "LOOP_DB_PATH", os.path.expanduser("~/djimitflo/.data/djimitflo.sqlite")
    )


def configure_logging(level: str = "INFO") -> None:
    """Configure structured logging for loop-engineering tools."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )


@contextmanager
def db_connection():
    """Context manager for database connections with auto-commit/rollback."""
    conn = sqlite3.connect(get_db_path())
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


DDL_STATEMENTS = [
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
        tripped INTEGER DEFAULT 0, last_failure_at TEXT, updated_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS governance_policies (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT DEFAULT '',
        rules_json TEXT DEFAULT '[]', enabled INTEGER DEFAULT 1,
        created_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS capability_tokens (
        id TEXT PRIMARY KEY, token_ref TEXT NOT NULL,
        subject_agent_id TEXT, scopes_json TEXT DEFAULT '[]',
        allowed_actions_json TEXT DEFAULT '[]',
        denied_actions_json TEXT DEFAULT '[]', risk_class TEXT,
        status TEXT DEFAULT 'active', approved_by TEXT,
        expires_at TEXT, metadata TEXT DEFAULT '{}',
        created_at TEXT, updated_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS token_usage_log (
        id TEXT PRIMARY KEY, token_id TEXT NOT NULL,
        action_type TEXT NOT NULL, tokens_consumed INTEGER DEFAULT 0,
        metadata TEXT DEFAULT '{}', created_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS policy_violations (
        id TEXT PRIMARY KEY, policy_id TEXT NOT NULL,
        violation_type TEXT NOT NULL, details TEXT DEFAULT '',
        severity TEXT DEFAULT 'medium', resolved INTEGER DEFAULT 0,
        created_at TEXT
    )""",
]


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create all required tables if they don't exist."""
    for stmt in DDL_STATEMENTS:
        conn.execute(stmt)
