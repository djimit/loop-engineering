#!/usr/bin/env python3
"""Deterministic mutation check on critical governance logic (herhaalbaar).

Applies 4 minimal semantic mutants to the two most critical control paths
(scope gate, budget cap, escalation deadline, injection gate) and verifies
the test suite FAILS for each (mutant killed). Read-only vs. git: every
mutant is reverted via git checkout before the next.

Usage: python3 tools/mutation_check.py   # prints per-mutant verdict + rate
"""

import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_suite(db_path: str) -> int:
    env = dict(os.environ, LOOP_DB_PATH=db_path)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-q"],
        capture_output=True,
        text=True,
        cwd=REPO,
        env=env,
        timeout=300,
    )
    return result.returncode


def mutate(rel_path: str, old: str, new: str) -> None:
    full = os.path.join(REPO, rel_path)
    with open(full) as fh:
        src = fh.read()
    assert old in src, f"pattern not found in {rel_path}: {old[:60]!r}"
    backups[rel_path] = src
    with open(full, "w") as fh:
        fh.write(src.replace(old, new, 1))


_backups: dict[str, str] = {}
backups = _backups  # alias without type annotation churn below


def restore(rel_path: str) -> None:
    # Restore from in-memory backup; git checkout is not reliable when the
    # file is not yet tracked/staged (untracked mutants would be lost).
    if rel_path in backups:
        full = os.path.join(REPO, rel_path)
        with open(full, "w") as fh:
            fh.write(backups[rel_path])
        del backups[rel_path]


MUTANTS = [
    (
        "tools/loop_orchestrator.py",
        # Mutant M0: disable the mode-config scope guard (dead branch).
        # The remaining token-scope layer still enforces, so this mutant is
        # an equivalent mutant UNLESS a test exercises a divergence between
        # mode_config.scopes and token scopes — kept as a defense-in-depth
        # canary (kill demonstrates the layers are independently tested).
        'def _authorize(self, scope: str = "read") -> None:\n'
        '        if scope not in self.mode_config["scopes"]:\n'
        '            raise PermissionError(f"Mode {self.mode} does not grant'
        ' scope {scope}")\n'
        "        token = self._token()",
        'def _authorize(self, scope: str = "read") -> None:\n'
        "        if False:\n"
        '            raise PermissionError(f"Mode {self.mode} does not grant'
        ' scope {scope}")\n'
        "        token = self._token()",
    ),
    (
        "tools/loop_orchestrator.py",
        "if self.token_usage + tokens > self.budget_cap:",
        "if self.token_usage + tokens > self.budget_cap + 10000:",
    ),
    (
        "tools/escalation_gateway.py",
        'if (now or _now()) < _parse_datetime(summary["escalation"]["expires_at"]):',
        "if False:",
    ),
    (
        "tools/injection_gate.py",
        "if pattern_name not in INJECTION_PATTERNS:",
        "if False:",
    ),
]


def main() -> int:
    dbdir = tempfile.mkdtemp(prefix="mut_")
    results = []
    try:
        for i, (path, old, new) in enumerate(MUTANTS):
            db = os.path.join(dbdir, f"m{i}.sqlite")
            mutate(path, old, new)
            try:
                rc = run_suite(db)
            finally:
                restore(path)
            killed = rc != 0
            results.append(killed)
            print(
                f"mutant {i} [{os.path.basename(path)}]: "
                f"{'KILLED' if killed else '*** SURVIVED ***'}"
            )
    finally:
        for path, _, _ in MUTANTS:
            restore(path)
        shutil.rmtree(dbdir, ignore_errors=True)

    rate = sum(results) / len(results) if results else 0.0
    print(f"\nKill rate: {sum(results)}/{len(results)} = {rate:.0%}")
    return 0 if rate == 1.0 else 1


if __name__ == "__main__":
    sys.exit(main())
