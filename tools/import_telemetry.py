#!/usr/bin/env python3
"""Import append-only swarm telemetry into Djitimflo."""

import json
import sqlite3
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

from config import REPO_ROOT, ensure_schema, get_db_path

DJITIMFLO_DB = get_db_path()
TELEMETRY_FILE = REPO_ROOT / ".swarm" / "telemetry.jsonl"
_ID_NAMESPACE = uuid.UUID("8dc4da40-e879-4f7b-8ddf-63c68271359d")


def _stable_id(*parts: object) -> str:
    return str(uuid.uuid5(_ID_NAMESPACE, ":".join(map(str, parts))))


def import_telemetry(
    conn: sqlite3.Connection, telemetry_path: Path, start_offset: int = 0
) -> dict:
    """Import telemetry from a byte offset without duplicating prior records."""
    stats = {
        "imported": 0,
        "skipped": 0,
        "runs_created": 0,
        "next_offset": start_offset,
    }
    if not telemetry_path.exists():
        return stats

    source = str(telemetry_path.resolve())
    current_run_id = None

    with telemetry_path.open(encoding="utf-8") as telemetry:
        telemetry.seek(start_offset)
        while True:
            line_offset = telemetry.tell()
            line = telemetry.readline()
            if not line:
                break
            stats["next_offset"] = telemetry.tell()
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                stats["skipped"] += 1
                continue

            event = entry.get("event", "unknown")
            session_id = entry.get("sessionId", "")
            agent_name = entry.get("agentName", "")
            timestamp = entry.get("timestamp", datetime.now().isoformat())
            correlation_id = _stable_id(source, session_id or "orphan")
            run_id = _stable_id(source, session_id or "orphan")

            if event == "session_started" or current_run_id != run_id:
                before = conn.total_changes
                conn.execute(
                    """INSERT OR IGNORE INTO loop_runs
                       (id, loop_name, mode, status, repository_path, metadata, created_at)
                       VALUES (?, ?, 'open', 'running', ?, ?, ?)""",
                    (
                        run_id,
                        agent_name or "unknown",
                        str(REPO_ROOT),
                        json.dumps(
                            {
                                "session_id": session_id,
                                "correlation_id": correlation_id,
                                "telemetry_source": source,
                            }
                        ),
                        timestamp,
                    ),
                )
                stats["runs_created"] += conn.total_changes - before
                current_run_id = run_id

            metadata = json.dumps(
                {
                    "session_id": session_id,
                    "correlation_id": correlation_id,
                    "telemetry_source": source,
                    "source_offset": line_offset,
                }
            )
            before = conn.total_changes
            conn.execute(
                """INSERT OR IGNORE INTO loop_events
                   (id, loop_run_id, event_type, level, message, metadata, created_at)
                   VALUES (?, ?, ?, 'info', ?, ?, ?)""",
                (
                    _stable_id(source, line_offset, "event"),
                    run_id,
                    event,
                    f"{agent_name}: {event}",
                    metadata,
                    timestamp,
                ),
            )
            stats["imported"] += conn.total_changes - before

            if event == "agent_activated":
                conn.execute(
                    """INSERT OR IGNORE INTO loop_checkpoints
                       (id, loop_run_id, label, state_json, gates_json,
                        findings_json, metadata, created_at)
                       VALUES (?, ?, ?, ?, '[]', '[]', ?, ?)""",
                    (
                        _stable_id(source, line_offset, "checkpoint"),
                        run_id,
                        f"agent_{agent_name}",
                        json.dumps({"agent": agent_name, "session_id": session_id}),
                        metadata,
                        timestamp,
                    ),
                )

    return stats


def watch_mode(
    conn: sqlite3.Connection, telemetry_path: Path, interval: float = 5.0
) -> None:
    """Continuously import only bytes appended after the last import."""
    stats = import_telemetry(conn, telemetry_path)
    conn.commit()
    offset = stats["next_offset"]
    print(f"Watching {telemetry_path} from byte {offset} (interval: {interval}s)...")

    try:
        while True:
            time.sleep(interval)
            if not telemetry_path.exists():
                continue
            if telemetry_path.stat().st_size < offset:
                offset = 0
            stats = import_telemetry(conn, telemetry_path, offset)
            offset = stats["next_offset"]
            if stats["imported"] or stats["skipped"]:
                conn.commit()
                print(
                    f"Imported {stats['imported']} new entries, "
                    f"{stats['skipped']} skipped"
                )
    except KeyboardInterrupt:
        print("Watch mode stopped")


def main() -> int:
    conn = sqlite3.connect(DJITIMFLO_DB)
    ensure_schema(conn)

    if "--watch" in sys.argv[1:]:
        watch_mode(conn, TELEMETRY_FILE)
    else:
        stats = import_telemetry(conn, TELEMETRY_FILE)
        conn.commit()
        print(
            f"Imported {stats['imported']} telemetry entries, "
            f"{stats['runs_created']} runs created, {stats['skipped']} skipped"
        )
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
