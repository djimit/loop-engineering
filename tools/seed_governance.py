#!/usr/bin/env python3
"""
Seed Djitimflo governance_policies and capability_tables from loop-constraints.md.

Reads loop-constraints.md, extracts structured constraint definitions,
and inserts them into the Djitimflo SQLite database.
"""

import json
import logging
import re
import sqlite3
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from config import REPO_ROOT, ensure_schema, get_db_path

DJITIMFLO_DB = get_db_path()
logger = logging.getLogger(__name__)
CONSTRAINTS_FILE = REPO_ROOT / "loop-constraints.md"
TOKEN_CONFIG_FILE = REPO_ROOT / "tools" / "capability_config.json"


def parse_constraints(md_path: Path) -> list[dict]:
    """Parse loop-constraints.md into structured policy records."""
    content = md_path.read_text()
    constraints = []
    current = None

    for line in content.split("\n"):
        line = line.strip()

        # Match constraint header: ### Constraint: <name>
        m = re.match(r"^### Constraint:\s*(.+)$", line)
        if m:
            if current:
                constraints.append(current)
            current = {
                "name": m.group(1).strip(),
                "id": "",
                "risk_class": "medium",
                "scopes": ["read"],
                "description": "",
                "enforcement": "warn_and_log",
            }
            continue

        if not current:
            continue

        # Match key-value fields
        m = re.match(r"^- \*\*id\*\*: `([^`]+)`", line)
        if m:
            current["id"] = m.group(1)
            continue

        m = re.match(r"^- \*\*risk_class\*\*: (\w+)", line)
        if m:
            current["risk_class"] = m.group(1)
            continue

        m = re.match(r"^- \*\*scopes\*\*: \[([^\]]+)\]", line)
        if m:
            current["scopes"] = [s.strip() for s in m.group(1).split(",")]
            continue

        m = re.match(r"^- \*\*description\*\*: (.+)", line)
        if m:
            current["description"] = m.group(1)
            continue

        m = re.match(r"^- \*\*enforcement\*\*: (\w+)", line)
        if m:
            current["enforcement"] = m.group(1)
            continue

    if current:
        constraints.append(current)

    return constraints


def ensure_tables(conn: sqlite3.Connection):
    """Ensure required tables exist with correct schema."""
    ensure_schema(conn)


def seed_policies(conn: sqlite3.Connection, constraints: list[dict]) -> int:
    """Insert governance policies idempotently. Returns count of new policies."""
    count = 0
    for c in constraints:
        rules = {
            "risk_class": c["risk_class"],
            "scopes": c["scopes"],
            "enforcement": c["enforcement"],
        }
        existing = conn.execute(
            "SELECT id FROM governance_policies WHERE id = ?", (c["id"],)
        ).fetchone()

        if existing:
            conn.execute(
                """UPDATE governance_policies
                   SET name=?, description=?, rules_json=?
                   WHERE id=?""",
                (c["name"], c["description"], json.dumps(rules), c["id"]),
            )
        else:
            conn.execute(
                """INSERT INTO governance_policies (id, name, description, rules_json)
                   VALUES (?, ?, ?, ?)""",
                (c["id"], c["name"], c["description"], json.dumps(rules)),
            )
            count += 1

        # Log seeding event
        conn.execute(
            """INSERT INTO governance_events (id, agent_id, session_id, action_type, metadata_json)
               VALUES (?, ?, ?, 'policy_seeded', ?)""",
            (
                str(uuid.uuid4()),
                "seed_governance",
                str(uuid.uuid4()),
                json.dumps({"policy_id": c["id"]}),
            ),
        )

    return count


def seed_capability_tokens(conn: sqlite3.Connection) -> int:
    """Insert L1/L2/L3 capability tokens. Returns count of new tokens."""
    config_path = TOKEN_CONFIG_FILE
    if not config_path.exists():
        logger.warning("%s not found, skipping capability token seeding", config_path)
        return 0

    config = json.loads(config_path.read_text())
    count = 0

    for mode, cfg in config.items():
        token_ref = f"loop-{mode}-token"
        existing = conn.execute(
            "SELECT id FROM capability_tokens WHERE token_ref = ?", (token_ref,)
        ).fetchone()

        metadata = {
            "max_budget": cfg["max_budget"],
            "mode": mode,
        }

        expires_at = (datetime.now() + timedelta(hours=24)).isoformat() + "Z"

        if existing:
            conn.execute(
                """UPDATE capability_tokens
                   SET scopes_json=?, risk_class=?, metadata=?, expires_at=?, updated_at=datetime('now')
                   WHERE token_ref=?""",
                (
                    json.dumps(cfg["scopes"]),
                    cfg["risk_class"],
                    json.dumps(metadata),
                    expires_at,
                    token_ref,
                ),
            )
        else:
            conn.execute(
                """INSERT INTO capability_tokens
                   (id, token_ref, scopes_json, risk_class, status, expires_at, metadata)
                   VALUES (?, ?, ?, ?, 'active', ?, ?)""",
                (
                    str(uuid.uuid4()),
                    token_ref,
                    json.dumps(cfg["scopes"]),
                    cfg["risk_class"],
                    expires_at,
                    json.dumps(metadata),
                ),
            )
            count += 1

    return count


def detect_drift(conn: sqlite3.Connection, workflows_dir: Path) -> list[dict]:
    """Detect constraint drift between policies and workflow YAML files."""
    violations = []
    if not workflows_dir.exists():
        return violations

    for wf_file in workflows_dir.glob("*.yml"):
        content = wf_file.read_text()
        # Check for auto-merge patterns
        if "gh pr merge" in content or "auto-merge" in content:
            policy = conn.execute(
                "SELECT id FROM governance_policies WHERE id = 'no-auto-merge-main'"
            ).fetchone()
            if policy:
                violations.append(
                    {
                        "file": str(wf_file),
                        "policy_id": "no-auto-merge-main",
                        "issue": "Workflow contains auto-merge command",
                    }
                )
                conn.execute(
                    """INSERT INTO policy_violations
                       (id, policy_id, action_type, risk_level, status,
                        description, metadata)
                       VALUES (?, 'no-auto-merge-main', 'constraint_drift',
                               'high', 'open', ?, '{}')""",
                    (str(uuid.uuid4()), f"{wf_file}: auto-merge found"),
                )

    return violations


def main():
    constraints = parse_constraints(CONSTRAINTS_FILE)
    logger.info("Parsed %d constraints from %s", len(constraints), CONSTRAINTS_FILE)

    conn = sqlite3.connect(DJITIMFLO_DB)
    ensure_tables(conn)

    policy_count = seed_policies(conn, constraints)
    token_count = seed_capability_tokens(conn)

    workflows_dir = REPO_ROOT / ".github" / "workflows"
    drift = detect_drift(conn, workflows_dir)

    conn.commit()
    conn.close()

    print(
        f"Seeded {policy_count} new policies, updated {len(constraints) - policy_count} existing"
    )
    print(f"Seeded {token_count} new capability tokens")
    if drift:
        print(f"Detected {len(drift)} constraint drift violations:")
        for v in drift:
            print(f"  - {v['file']}: {v['issue']}")
    else:
        print("No constraint drift detected")

    return 0


if __name__ == "__main__":
    sys.exit(main())
