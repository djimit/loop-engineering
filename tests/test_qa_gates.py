#!/usr/bin/env python3
"""Unit tests for qa_gates.py check functions."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

os.environ.setdefault(
    "LOOP_DB_PATH", tempfile.mktemp(suffix=".sqlite", prefix="qa_test_")
)

from qa_gates import (
    check_architecture_soundness,
    check_feasibility,
    check_risk_identification,
    check_scope_clarity,
    check_security_posture,
)


class TestCheckFeasibility(unittest.TestCase):
    def test_valid_proposal(self):
        result = check_feasibility(
            "Integrate OpenMythos QA gates into the orchestrator.",
            "Sequential 6-phase pipeline with circuit breaker.",
        )
        self.assertIn("score", result)
        self.assertIn("findings", result)
        self.assertIsInstance(result["score"], int)
        self.assertGreater(result["score"], 0)

    def test_empty_proposal(self):
        result = check_feasibility("", "")
        self.assertIn("score", result)
        self.assertIsInstance(result["findings"], list)


class TestCheckScopeClarity(unittest.TestCase):
    def test_clear_scope(self):
        result = check_scope_clarity(
            "Add structured logging. No production changes.",
            "Replace print() with logging module.",
        )
        self.assertIn("score", result)
        self.assertIsInstance(result["findings"], list)

    def test_vague_scope(self):
        result = check_scope_clarity("Improve things.", "Make it better.")
        self.assertGreater(len(result["findings"]), 0)


class TestCheckRiskIdentification(unittest.TestCase):
    def test_with_mitigations(self):
        result = check_risk_identification(
            "Refactor config. Risk: breaking imports. Mitigation: backward-compatible.",
            "Extract config.py. Risk: import failures. Mitigation: gradual migration.",
        )
        self.assertIn("score", result)
        self.assertIsInstance(result["findings"], list)

    def test_no_mitigations(self):
        result = check_risk_identification("Rewrite everything.", "New architecture.")
        self.assertGreater(len(result["findings"]), 0)


class TestCheckArchitectureSoundness(unittest.TestCase):
    def test_sound_design(self):
        result = check_architecture_soundness(
            "Single config module. Tools import from it."
        )
        self.assertIn("score", result)
        self.assertIsInstance(result["findings"], list)

    def test_no_data_flow(self):
        result = check_architecture_soundness("Make it work.")
        self.assertGreater(len(result["findings"]), 0)


class TestCheckSecurityPosture(unittest.TestCase):
    def setUp(self):
        self.specs_dir = Path(tempfile.mkdtemp(prefix="qa_test_specs_"))

    def test_with_security(self):
        result = check_security_posture(
            "Input validation. Path traversal protection. SQL parameterization.",
            self.specs_dir,
        )
        self.assertIn("score", result)
        self.assertIsInstance(result["findings"], list)

    def test_no_security(self):
        result = check_security_posture("Just make it work fast.", self.specs_dir)
        self.assertGreater(len(result["findings"]), 0)


if __name__ == "__main__":
    unittest.main()
