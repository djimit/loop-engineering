#!/usr/bin/env python3
"""Unit tests for seed_governance.py parse_constraints and detect_drift."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

os.environ.setdefault(
    "LOOP_DB_PATH", tempfile.mktemp(suffix=".sqlite", prefix="seed_test_")
)

from seed_governance import detect_drift, parse_constraints


class TestParseConstraints(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="seed_test_")

    def _write_md(self, content: str) -> Path:
        p = Path(self.tmpdir) / "test_constraints.md"
        p.write_text(content)
        return p

    def test_valid_constraints(self):
        md = self._write_md("""\
### Constraint: no-auto-merge
- **id**: `no-auto-merge-main`
- **risk_class**: high
- **scopes**: ["read", "execute"]
- **description**: Prevent auto-merge on main
- **enforcement**: block

### Constraint: require-review
- **id**: `require-review`
- **risk_class**: medium
- **scopes**: ["read"]
- **description**: Require human review
- **enforcement**: warn_and_log
""")
        result = parse_constraints(md)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["id"], "no-auto-merge-main")
        self.assertEqual(result[0]["risk_class"], "high")
        self.assertEqual(result[1]["id"], "require-review")

    def test_empty_file(self):
        md = self._write_md("")
        result = parse_constraints(md)
        self.assertEqual(result, [])

    def test_malformed_headers(self):
        md = self._write_md("""\
# Not a constraint
Some random text
- **id**: `test`
""")
        result = parse_constraints(md)
        self.assertEqual(result, [])

    def test_duplicate_ids(self):
        md = self._write_md("""\
### Constraint: first
- **id**: `same-id`
- **risk_class**: low

### Constraint: second
- **id**: `same-id`
- **risk_class**: high
""")
        result = parse_constraints(md)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["id"], "same-id")
        self.assertEqual(result[1]["id"], "same-id")


class TestDetectDrift(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="seed_test_")

    def _write_workflow(self, name: str, content: str) -> Path:
        wf_dir = Path(self.tmpdir) / "workflows"
        wf_dir.mkdir(exist_ok=True)
        p = wf_dir / name
        p.write_text(content)
        return wf_dir

    def test_detects_auto_merge(self):
        wf_dir = self._write_workflow(
            "ci.yml",
            """\
name: CI
on: push
jobs:
  deploy:
    steps:
      - run: gh pr merge --auto --merge
""",
        )
        import sqlite3

        conn = sqlite3.connect(os.environ["LOOP_DB_PATH"])
        from config import ensure_schema

        ensure_schema(conn)
        conn.execute(
            "INSERT OR IGNORE INTO governance_policies (id, name) VALUES (?, ?)",
            ("no-auto-merge-main", "No auto-merge on main"),
        )
        conn.commit()
        violations = detect_drift(conn, wf_dir)
        conn.close()
        self.assertGreater(len(violations), 0)
        self.assertEqual(violations[0]["policy_id"], "no-auto-merge-main")

    def test_clean_workflow(self):
        wf_dir = self._write_workflow(
            "ci.yml",
            """\
name: CI
on: push
jobs:
  test:
    steps:
      - run: pytest
""",
        )
        import sqlite3

        conn = sqlite3.connect(os.environ["LOOP_DB_PATH"])
        from config import ensure_schema

        ensure_schema(conn)
        violations = detect_drift(conn, wf_dir)
        conn.close()
        self.assertEqual(len(violations), 0)

    def test_empty_workflows_dir(self):
        wf_dir = Path(self.tmpdir) / "workflows"
        wf_dir.mkdir(exist_ok=True)
        import sqlite3

        conn = sqlite3.connect(os.environ["LOOP_DB_PATH"])
        from config import ensure_schema

        ensure_schema(conn)
        violations = detect_drift(conn, wf_dir)
        conn.close()
        self.assertEqual(len(violations), 0)


if __name__ == "__main__":
    unittest.main()
