#!/usr/bin/env python3
"""Import .swarm/telemetry.jsonl into Djitimflo loop_runs, loop_events, and loop_checkpoints."""

import json
import os
import sqlite3
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

DJITIMFLO_DB = os.environ.get(
    "LOOP_DB_PATH", os.path.expanduser("~/djimitflo/.data/djimitflo.sqlite")
)
REPO_ROOT = Path(__file__).parent.parent
TELEMETRY_FILE = REPO_ROOT / ".swarm" / "telemetry.jsonl"


def ensure_tables(conn: sqlite3.Connection):
    """Ensure telemetry tables exist."""
    statements = [
        """CREATE TABLE IF NOT EXISTS loop_runs (
            id TEXT PRIMARY KEY,
            goal_id TEXT,
            loop_name TEXT NOT NULL,
            mode TEXT NOT NULL,
            status TEXT NOT NULL,
            repository_path TEXT,
            state_file TEXT,
            findings_json TEXT DEFAULT '[]',
            plan_json TEXT DEFAULT '{}',
            gates_json TEXT DEFAULT '[]',
            next_actions_json TEXT DEFAULT '[]',
            metadata TEXT DEFAULT '{}',
            created_at TEXT,
            updated_at TEXT,
            completed_at TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS loop_events (
            id TEXT PRIMARY KEY,
            loop_run_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            level TEXT,
            message TEXT NOT NULL,
            metadata TEXT DEFAULT '{}',
            created_at TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS loop_checkpoints (
            id TEXT PRIMARY KEY,
            loop_run_id TEXT NOT NULL,
            label TEXT NOT NULL,
            state_json TEXT DEFAULT '{}',
            gates_json TEXT DEFAULT '[]',
            findings_json TEXT DEFAULT '[]',
            leases_json TEXT DEFAULT '[]',
            metadata TEXT DEFAULT '{}',
            created_at TEXT
        )""",
    ]
    for stmt in statements:
        conn.execute(stmt)


def import_telemetry(conn: sqlite3.Connection, telemetry_path: Path) -> dict:
    """Import telemetry entries. Returns stats dict."""
    if not telemetry_path.exists():
        return {"imported": 0, "skipped": 0, "runs_created": 0}

    stats = {"imported": 0, "skipped": 0, "runs_created": 0}
    correlation_id = str(uuid.uuid4())
    run_id = None

    with open(telemetry_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                stats["skipped"] += 1
                continue

            event = entry.get("event", "")
            session_id = entry.get("sessionId", "")
            agent_name = entry.get("agentName", "")
            timestamp = entry.get("timestamp", datetime.now().isoformat())

            # Create a loop_run per session
            if event == "session_started":
                run_id = str(uuid.uuid4())
                conn.execute(
                    """INSERT OR IGNORE INTO loop_runs
                       (id, loop_name, mode, status, repository_path, metadata, created_at)
                       VALUES (?, ?, 'L1', 'running', ?, ?, ?)""",
                    (
                        run_id,
                        agent_name,
                        str(REPO_ROOT),
                        json.dumps(
                            {"session_id": session_id, "correlation_id": correlation_id}
                        ),
                        timestamp,
                    ),
                )
                stats["runs_created"] += 1

            if run_id is None:
                run_id = str(uuid.uuid4())
                conn.execute(
                    """INSERT OR IGNORE INTO loop_runs
                       (id, loop_name, mode, status, repository_path, metadata, created_at)
                       VALUES (?, 'unknown', 'L1', 'running', ?, ?, ?)""",
                    (
                        run_id,
                        str(REPO_ROOT),
                        json.dumps({"correlation_id": correlation_id, "orphan": True}),
                        timestamp,
                    ),
                )
                stats["runs_created"] += 1

            # Create loop_event
            conn.execute(
                """INSERT INTO loop_events (id, loop_run_id, event_type, level, message, metadata, created_at)
                   VALUES (?, ?, ?, 'info', ?, ?, ?)""",
                (
                    str(uuid.uuid4()),
                    run_id,
                    event,
                    f"{agent_name}: {event}",
                    json.dumps(
                        {"session_id": session_id, "correlation_id": correlation_id}
                    ),
                    timestamp,
                ),
            )

            # Create checkpoint on agent transitions
            if event == "agent_activated":
                conn.execute(
                    """INSERT INTO loop_checkpoints
                       (id, loop_run_id, label, state_json, gates_json, findings_json, metadata, created_at)
                       VALUES (?, ?, ?, ?, '[]', '[]', ?, ?)""",
                    (
                        str(uuid.uuid4()),
                        run_id,
                        f"agent_{agent_name}",
                        json.dumps({"agent": agent_name, "session_id": session_id}),
                        json.dumps({"correlation_id": correlation_id}),
                        timestamp,
                    ),
                )

            stats["imported"] += 1

    return stats


def watch_mode(conn: sqlite3.Connection, telemetry_path: Path, interval: float = 5.0):
    """Watch telemetry file for new entries and import incrementally."""
    print(f"Watching {telemetry_path} for new entries (interval: {interval}s)...")
    last_size = telemetry_path.stat().st_size if telemetry_path.exists() else 0

    try:
        while True:
            time.sleep(interval)
            if not telemetry_path.exists():
                continue
            current_size = telemetry_path.stat().st_size
            if current_size > last_size:
                with open(telemetry_file) as f:
                    f.seek(last_size)
                    new_lines = f.readlines()
                    # Process new lines...
                    for line in new_lines:
                        line = line.strip()
                        if line:
                            stats = import_telemetry(conn, telemetry_path)
                            if stats["imported"] > 0:
                                print(f"Imported {stats['imported']} new entries")
                last_size = current_size
    except KeyboardInterrupt:
        print("Watch mode stopped")


def main():
    args = sys.argv[1:]
    watch = "--watch" in args

    conn = sqlite3.connect(DJITIMFLO_DB)
    ensure_tables(conn)

    stats = import_telemetry(conn, TELEMETRY_FILE)
    conn.commit()

    print(
        f"Imported {stats['imported']} telemetry entries, {stats['runs_created']} runs created, {stats['skipped']} skipped"
    )

    if watch:
        watch_mode(conn, TELEMETRY_FILE)
    else:
        conn.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
