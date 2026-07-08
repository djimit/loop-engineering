#!/usr/bin/env python3
"""Shared security module for MCP server hardening.

Adopts path traversal patterns from loop-mcp-server.
"""

import os
import re
from pathlib import Path

# State files that MCP server is allowed to read
STATE_FILE_ALLOWLIST = {
    "STATE.md",
    "LOOP.md",
    "telemetry.jsonl",
    "context.md",
    "config.example.json",
    "repo-graph.json",
}

# Deny patterns for path traversal
DENY_PATTERNS = [
    re.compile(r"\.\."),  # parent directory traversal
    re.compile(r"^[/\\\\]"),  # absolute paths (leading slash or backslash)
    re.compile(r"\x00"),  # null bytes
    re.compile(r"[~`$|;&<>]"),  # shell metacharacters
]

# Safe segment pattern for runId, filenames, etc.
SAFE_SEGMENT_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")


def assert_safe_segment(segment: str) -> bool:
    """Return True if segment is safe for use in file paths and branch names."""
    if not segment:
        return False
    if len(segment) > 255:
        return False
    if segment.startswith("-"):
        return False
    if ".." in segment:
        return False
    return bool(SAFE_SEGMENT_PATTERN.match(segment))


def assert_safe_path(resource_path: str, base_dir: str) -> str:
    """Validate resource path and return resolved path.

    Raises ValueError if path traversal is detected or path escapes base_dir.
    """
    for pattern in DENY_PATTERNS:
        if pattern.search(resource_path):
            raise ValueError(f"Path contains denied pattern: {pattern.pattern}")

    base = Path(base_dir).resolve()
    target = (base / resource_path).resolve()

    # Ensure resolved path is within base directory
    try:
        target.relative_to(base)
    except ValueError:
        raise ValueError(f"Path escapes base directory: {resource_path}")

    return str(target)


def is_state_file_allowed(filename: str) -> bool:
    """Check if a filename is in the state file allowlist."""
    basename = os.path.basename(filename)
    return basename in STATE_FILE_ALLOWLIST


def validate_git_ref(ref: str) -> bool:
    """Validate a git reference name using git check-ref-format rules.

    Note: forward slashes ARE allowed in git refs (e.g. feature/my-feature).
    Only backslashes are denied.
    """
    if not ref or len(ref) > 255:
        return False
    # Git ref format rules
    deny_patterns = [
        re.compile(r"^\."),  # leading dot
        re.compile(r"\.\."),  # double dot anywhere
        re.compile(r"[\\]"),  # backslash only (forward slash is valid in refs)
        re.compile(r"[\x00-\x20]"),  # control characters
        re.compile(r"[~^:?*\[\]]"),  # special git chars
        re.compile(r"@{"),  # @{ sequence
        re.compile(r"/$"),  # trailing slash
    ]
    for pattern in deny_patterns:
        if pattern.search(ref):
            return False
    return True
