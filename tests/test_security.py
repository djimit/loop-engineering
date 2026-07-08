#!/usr/bin/env python3
"""Tests for security module — path traversal, state file allowlist, git ref validation."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from security import (
    assert_safe_segment,
    assert_safe_path,
    is_state_file_allowed,
    validate_git_ref,
)


def check(condition, msg=""):
    if not condition:
        raise AssertionError(msg)


def test_safe_segment_valid():
    check(assert_safe_segment("abc123") == True, "abc123 should be safe")
    check(assert_safe_segment("loop-run-1") == True, "loop-run-1 should be safe")
    check(
        assert_safe_segment("feature_branch") == True, "feature_branch should be safe"
    )


def test_safe_segment_invalid():
    check(assert_safe_segment("") == False, "empty should be unsafe")
    check(
        assert_safe_segment("-leading-dash") == False, "leading dash should be unsafe"
    )
    check(assert_safe_segment("has/slash") == False, "slash should be unsafe")
    check(assert_safe_segment("has..dotdot") == False, "dotdot should be unsafe")
    check(assert_safe_segment("has space") == False, "space should be unsafe")
    check(assert_safe_segment("a" * 256) == False, "256 chars should be unsafe")


def test_safe_path_within_base():
    base = "/tmp/test-base-security"
    os.makedirs(base, exist_ok=True)
    result = assert_safe_path("STATE.md", base)
    check(
        result.endswith("STATE.md"), f"Expected path ending with STATE.md, got {result}"
    )


def test_safe_path_blocks_traversal():
    base = "/tmp/test-base-security"
    os.makedirs(base, exist_ok=True)
    try:
        assert_safe_path("../etc/passwd", base)
        raise AssertionError("Should have raised ValueError for traversal")
    except ValueError:
        pass


def test_safe_path_blocks_absolute():
    base = "/tmp/test-base-security"
    os.makedirs(base, exist_ok=True)
    try:
        assert_safe_path("/etc/passwd", base)
        raise AssertionError("Should have raised ValueError for absolute path")
    except ValueError:
        pass


def test_state_file_allowlist():
    check(is_state_file_allowed("STATE.md") == True)
    check(is_state_file_allowed("LOOP.md") == True)
    check(is_state_file_allowed("auth.json") == False)
    check(is_state_file_allowed(".env") == False)
    check(is_state_file_allowed("../etc/passwd") == False)


def test_git_ref_valid():
    check(validate_git_ref("main") == True, "main should be valid ref")
    check(
        validate_git_ref("feature/my-feature") == True,
        "feature/my-feature should be valid ref",
    )
    check(validate_git_ref("loop/run-123") == True, "loop/run-123 should be valid ref")


def test_git_ref_invalid():
    check(validate_git_ref("") == False)
    check(validate_git_ref(".hidden") == False)
    check(validate_git_ref("has..dotdot") == False)
    check(validate_git_ref("has space") == False)
    check(validate_git_ref("has~tilde") == False)
    check(validate_git_ref("has^caret") == False)


def main():
    tests = [
        test_safe_segment_valid,
        test_safe_segment_invalid,
        test_safe_path_within_base,
        test_safe_path_blocks_traversal,
        test_safe_path_blocks_absolute,
        test_state_file_allowlist,
        test_git_ref_valid,
        test_git_ref_invalid,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
            print(f"  [PASS] {test.__name__}")
        except (AssertionError, Exception) as e:
            failed += 1
            print(f"  [FAIL] {test.__name__}: {e}")

    print(f"\nSecurity tests: {passed}/{passed + failed} passed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
