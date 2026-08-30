#!/usr/bin/env python3
"""Single source of truth for deterministic injection patterns.

Shared by the test suite (tests/prompt_injection/test_injection.py) and the
enforcement gate (tools/injection_gate.py). Adding a pattern here extends
both detection and enforcement in one place.
"""

import re

INJECTION_PATTERNS = {
    "ignore_instructions": re.compile(
        r"ignore\s+(previous|all|above|prior|the\s+above)\s+(instructions|rules|constraints|guidelines)",
        re.IGNORECASE,
    ),
    "secret_extraction": re.compile(
        r"(print|show|display|reveal|dump|export|send|me)\s+(all\s+|the\s+)?(secrets?|credentials?|api.?keys?|tokens?|passwords?|environment)",
        re.IGNORECASE,
    ),
    "unauthorized_merge": re.compile(
        r"(merge|approve)\s+(this|the)\s+PR(\s+immediately|\s+now|\s+without\s+review)?",
        re.IGNORECASE,
    ),
    "test_disabling": re.compile(
        r"(disable|skip|bypass|ignore)\s+(all\s+)?(tests?|checks?|validations?|gates?|the\s+checks)",
        re.IGNORECASE,
    ),
}


def detect_injection(text: str) -> list[str]:
    """Detect injection patterns in text. Returns list of matched pattern names."""
    matches = []
    for name, pattern in INJECTION_PATTERNS.items():
        if pattern.search(text):
            matches.append(name)
    return matches
