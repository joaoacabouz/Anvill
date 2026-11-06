"""Anvill Test Runner.

Executes all test suites in testsuit/ and reports results.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TEST_DIR = REPO_ROOT / "testsuit"
SRC_DIR = REPO_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def main() -> int:
    print("=" * 70)
    print("  ANVILL COMPREHENSIVE TEST SUITE")
    print(f"  Test Directory: {TEST_DIR}")
    print(f"  Source Directory: {SRC_DIR}")
    print("=" * 70)

    loader = unittest.TestLoader()
    suite = loader.discover(start_dir=str(TEST_DIR), pattern="test_*.py")

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("-" * 70)
    total = result.testsRun
    failed = len(result.failures)
    errored = len(result.errors)
    passed = total - (failed + errored)

    print(f"Total Tests Run : {total}")
    print(f"Passed          : {passed}")
    print(f"Failures        : {failed}")
    print(f"Errors          : {errored}")
    print("-" * 70)

    if result.wasSuccessful():
        print(">>> ALL TESTS PASSED SUCCESSFULLY! <<<")
        return 0
    else:
        print(">>> SOME TESTS FAILED <<<")
        return 1


if __name__ == "__main__":
    sys.exit(main())

