#!/usr/bin/env python3
"""Shared configuration for loop-engineering tools."""

import os
import sqlite3
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent


def get_db_path() -> str:
    """Return database path from LOOP_DB_PATH env var or default."""
    return os.environ.get(
        "LOOP_DB_PATH", os.path.expanduser("~/djimitflo/.data/djimitflo.sqlite")
    )


DDL_STATEMENTS = [
    """CREATE TABLE IF NOT EXISTS loop_runs (
        id TEXT PRIMARY KEY, goal_id TEXT, loop_name TEXT NOT NULL,
        mode TEXT NOT NULL CHECK(mode IN ('closed', 'open')),
        status TEXT NOT NULL CHECK(status IN (
            'created', 'planning', 'running', 'verifying',
            'ready_for_human_merge', 'blocked', 'completed', 'failed',
            'escalated', 'cancelled', 'interrupted'
        )), repository_path TEXT,
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
        id TEXT PRIMARY KEY, task_id TEXT, agent_id TEXT,
        provider TEXT NOT NULL, model TEXT NOT NULL,
        prompt_tokens INTEGER NOT NULL DEFAULT 0,
        completion_tokens INTEGER NOT NULL DEFAULT 0,
        cache_read_tokens INTEGER NOT NULL DEFAULT 0,
        cache_create_tokens INTEGER NOT NULL DEFAULT 0,
        cost REAL NOT NULL DEFAULT 0, duration_ms INTEGER,
        timestamp TEXT, discussion_id TEXT, task_type TEXT,
        total_tokens INTEGER NOT NULL DEFAULT 0, cost_estimate REAL,
        metadata TEXT DEFAULT '{}', created_at TEXT, updated_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS policy_violations (
        id TEXT PRIMARY KEY, task_id TEXT, execution_event_id TEXT,
        policy_id TEXT, action_type TEXT NOT NULL, risk_level TEXT NOT NULL,
        status TEXT NOT NULL, description TEXT NOT NULL,
        metadata TEXT NOT NULL DEFAULT '{}', created_at TEXT, updated_at TEXT
    )""",
]


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create all required tables if they don't exist."""
    for stmt in DDL_STATEMENTS:
        conn.execute(stmt)
