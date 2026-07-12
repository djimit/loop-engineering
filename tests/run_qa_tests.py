#!/usr/bin/env python3
"""Run the complete unit and integration test suite."""

import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent


def main() -> int:
    suite = unittest.TestSuite()
    for pattern in ("test_qa_gates.py", "test_seed_governance.py"):
        suite.addTests(
            unittest.defaultTestLoader.discover(
                str(REPO_ROOT / "tests"), pattern=pattern
            )
        )
    if not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful():
        return 1
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "tests" / "test_integration.py")],
        cwd=REPO_ROOT,
        check=False,
    ).returncode

if __name__ == "__main__":
    sys.exit(main())
