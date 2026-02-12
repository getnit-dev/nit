"""FixVerifier agent — verifies that fixes don't introduce regressions.

This agent (task 3.9.7):
1. Applies generated fixes to source code
2. Runs existing test suite to check for regressions
3. Runs the reproduction test to verify the bug is fixed
4. Reports verification results with pass/fail status

Transaction safety: a sentinel file is written before modifying any source
file and removed after the original is restored.  An ``atexit`` handler and
the module-level ``_restore_pending_fixes()`` helper ensure the backup is
restored even when the process is interrupted or crashes.
"""

from __future__ import annotations

import atexit
import json
import logging
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from nit.adapters.base import CaseStatus
from nit.agents.base import BaseAgent, TaskInput, TaskOutput, TaskStatus

if TYPE_CHECKING:
    from nit.adapters.base import TestFrameworkAdapter
    from nit.agents.debuggers.fix_gen import GeneratedFix

logger = logging.getLogger(__name__)

# Test output limits
MAX_STDOUT_LENGTH = 2000  # Maximum stdout to include in output
MAX_STDERR_LENGTH = 1000  # Maximum stderr to include in output
MAX_FAILING_TESTS_TO_SHOW = 5  # Maximum number of failing test names to display

# Sentinel file used for crash-recovery.
_SENTINEL_FILENAME = "fix_in_progress.json"


# ---------------------------------------------------------------------------
# Crash-recovery helpers
# ---------------------------------------------------------------------------


def _sentinel_dir(project_root: Path) -> Path:
    """Return (and lazily create) the directory that holds sentinel files."""
    d = project_root / ".nit" / "tmp"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _sentinel_path(project_root: Path) -> Path:
    """Return the full path to the sentinel file for *project_root*."""
    return _sentinel_dir(project_root) / _SENTINEL_FILENAME


def _write_sentinel(project_root: Path, original_path: str, backup_path: str) -> None:
    """Persist a sentinel so the backup can be restored after a crash."""
    payload = {"original_path": original_path, "backup_path": backup_path}
    _sentinel_path(project_root).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    logger.debug("Wrote sentinel: %s", _sentinel_path(project_root))


def _remove_sentinel(project_root: Path) -> None:
    """Remove the sentinel file (called after a successful restore)."""
    path = _sentinel_path(project_root)
    if path.exists():
        path.unlink()
        logger.debug("Removed sentinel: %s", path)


def _restore_pending_fixes(project_root: Path) -> bool:
    """Check for a crash-recovery sentinel and restore the backup if found.

    This should be called early during ``nit`` startup (or at least before
    any new verification run) to heal source files that were left modified
    by a previous interrupted run.

    Args:
        project_root: Root directory of the project.

    Returns:
        ``True`` if a pending fix was detected and restored, ``False``
        otherwise.
    """
    sentinel = _sentinel_path(project_root)
    if not sentinel.exists():
        return False

    try:
        data = json.loads(sentinel.read_text(encoding="utf-8"))
        original = Path(data["original_path"])
        backup = Path(data["backup_path"])

        if backup.exists():
            shutil.copy2(backup, original)
            logger.warning(
                "Restored source file from crash-recovery backup: %s -> %s",
                backup,
                original,
            )
        else:
            logger.warning("Sentinel found but backup file missing: %s", backup)

        sentinel.unlink()
        return True

    except Exception:
        logger.exception("Failed to restore pending fix from sentinel")
        return False


# ---------------------------------------------------------------------------
# atexit registry (one entry per in-flight verification)
# ---------------------------------------------------------------------------

# Mutable module-level state: registered (project_root, original_path,
# backup_path) tuples that the atexit handler will try to restore.
_pending_restores: list[tuple[Path, str, Path]] = []


def _atexit_restore() -> None:
    """Restore every still-pending backup on interpreter shutdown."""
    for project_root, original_path_str, backup_path in _pending_restores:
        try:
            target = Path(original_path_str)
            if backup_path.exists():
                shutil.copy2(backup_path, target)
                logger.warning("atexit: restored %s from %s", target, backup_path)
            _remove_sentinel(project_root)
        except Exception:
            logger.exception("atexit: failed to restore %s", original_path_str)


atexit.register(_atexit_restore)


@dataclass
class FixVerificationTask(TaskInput):
    """Task input for fix verification."""

    task_type: str = "verify_fix"
    """Type of task (defaults to 'verify_fix')."""

    target: str = ""
    """Target file being fixed."""

    fix: GeneratedFix | None = None
    """The generated fix to verify."""

    original_code: str = ""
    """Original source code (before fix)."""

    reproduction_test_file: str = ""
    """Path to the reproduction test file."""

    adapter: TestFrameworkAdapter | None = None
    """Test framework adapter to use."""


@dataclass
class VerificationReport:
    """Result of fix verification."""

    is_verified: bool
    """Whether the fix is verified (no regressions, bug fixed)."""

    bug_fixed: bool
    """Whether the reproduction test now passes."""

    regressions_found: bool
    """Whether any existing tests started failing."""

    test_results: str
    """Full test execution output."""

    failing_tests: list[str]
    """Names of tests that failed after applying fix."""

    notes: str = ""
    """Additional verification notes."""


class FixVerifier(BaseAgent):
    """Verifies that generated fixes work correctly without introducing regressions."""

    def __init__(
        self,
        project_root: Path,
    ) -> None:
        """Initialize the FixVerifier.

        Args:
            project_root: Root directory of the project.
        """
        super().__init__()
        self._project_root = project_root
        self._backup_dir = project_root / ".nit" / "tmp" / "fix_backups"
        self._backup_dir.mkdir(parents=True, exist_ok=True)

        # Attempt crash-recovery for any previous interrupted run.
        _restore_pending_fixes(project_root)

    @property
    def name(self) -> str:
        """Return the agent name."""
        return "FixVerifier"

    @property
    def description(self) -> str:
        """Return the agent description."""
        return "Verifies fixes don't introduce regressions and actually fix the bug"

    async def run(self, task: TaskInput) -> TaskOutput:
        """Execute fix verification.

        Args:
            task: A FixVerificationTask specifying the fix to verify.

        Returns:
            TaskOutput with VerificationReport in result['verification'].
        """
        if not isinstance(task, FixVerificationTask):
            return TaskOutput(
                status=TaskStatus.FAILED,
                errors=["Task must be a FixVerificationTask instance"],
            )

        if not task.fix or not task.adapter:
            return TaskOutput(
                status=TaskStatus.FAILED,
                errors=["Generated fix and test adapter are required"],
            )

        backup_path: Path | None = None

        try:
            logger.info("Verifying fix for %s", task.target)

            # Step 1: Backup original file
            backup_path = self._backup_file(task.target, task.original_code)

            # Resolve the absolute path of the target for the sentinel.
            abs_target = self._resolve_target(task.target)

            # Step 2: Write sentinel *before* touching the source file.
            _write_sentinel(
                self._project_root,
                str(abs_target),
                str(backup_path),
            )

            # Step 3: Register an atexit handler entry.
            restore_entry = (self._project_root, str(abs_target), backup_path)
            _pending_restores.append(restore_entry)

            try:
                # Step 4: Apply the fix
                self._apply_fix(task.target, task.fix.fixed_code)

                # Step 5: Run reproduction test (should now pass)
                bug_fixed = await self._verify_bug_fixed(task.reproduction_test_file, task.adapter)

                # Step 6: Run full test suite to check for regressions
                regressions_found, test_output, failing_tests = await self._check_regressions(
                    task.adapter
                )

                # Step 7: Determine overall verification status
                is_verified = bug_fixed and not regressions_found

                report = VerificationReport(
                    is_verified=is_verified,
                    bug_fixed=bug_fixed,
                    regressions_found=regressions_found,
                    test_results=test_output,
                    failing_tests=failing_tests,
                    notes=self._generate_verification_notes(
                        is_verified=is_verified,
                        bug_fixed=bug_fixed,
                        regressions_found=regressions_found,
                        failing_tests=failing_tests,
                    ),
                )

                logger.info(
                    "Fix verification complete: %s (bug fixed: %s, regressions: %s)",
                    "VERIFIED" if is_verified else "FAILED",
                    bug_fixed,
                    regressions_found,
                )

            finally:
                # Step 8: Restore original file
                self._restore_backup(task.target, backup_path)

                # Step 9: Remove sentinel & atexit entry — file is safe now.
                _remove_sentinel(self._project_root)
                if restore_entry in _pending_restores:
                    _pending_restores.remove(restore_entry)

            return TaskOutput(
                status=TaskStatus.COMPLETED,
                result={
                    "verification": report,
                    "is_verified": is_verified,
                },
            )

        except Exception as e:
            logger.exception("Fix verification failed: %s", e)
            # Try to restore backup on error
            if backup_path is not None and backup_path.exists():
                self._restore_backup(task.target, backup_path)
                _remove_sentinel(self._project_root)

            return TaskOutput(
                status=TaskStatus.FAILED,
                errors=[f"Verification error: {e}"],
            )

    def _resolve_target(self, file_path: str) -> Path:
        """Return the absolute path for *file_path*.

        Args:
            file_path: Absolute or project-relative path.

        Returns:
            Resolved absolute ``Path``.
        """
        target = Path(file_path)
        if not target.is_absolute():
            target = self._project_root / file_path
        return target

    def _backup_file(self, file_path: str, content: str) -> Path:
        """Create a backup of the original file.

        Args:
            file_path: Path to the file to backup.
            content: Content of the file.

        Returns:
            Path to the backup file.
        """
        timestamp = int(time.time() * 1000)
        file_name = Path(file_path).name
        backup_path = self._backup_dir / f"{file_name}.{timestamp}.bak"

        backup_path.write_text(content, encoding="utf-8")
        logger.debug("Created backup: %s", backup_path)

        return backup_path

    def _apply_fix(self, file_path: str, fixed_code: str) -> None:
        """Apply the fix by writing the fixed code to the file.

        Args:
            file_path: Path to the file to fix.
            fixed_code: Fixed source code.
        """
        target_path = self._resolve_target(file_path)
        target_path.write_text(fixed_code, encoding="utf-8")
        logger.debug("Applied fix to %s", target_path)

    def _restore_backup(self, file_path: str, backup_path: Path) -> None:
        """Restore the original file from backup.

        Args:
            file_path: Path to the file to restore.
            backup_path: Path to the backup file.
        """
        target_path = self._resolve_target(file_path)
        shutil.copy2(backup_path, target_path)
        logger.debug("Restored original file from %s", backup_path)

    async def _verify_bug_fixed(
        self, reproduction_test_file: str, adapter: TestFrameworkAdapter
    ) -> bool:
        """Verify that the reproduction test now passes.

        Args:
            reproduction_test_file: Path to the reproduction test.
            adapter: Test framework adapter.

        Returns:
            True if the bug is fixed (test passes).
        """
        if not reproduction_test_file or not Path(reproduction_test_file).exists():
            logger.warning("No reproduction test file provided, skipping bug verification")
            return True  # Assume fixed if no test

        try:
            result = await adapter.run_tests(
                self._project_root,
                test_files=[Path(reproduction_test_file)],
                timeout=30.0,
            )

            # Check if all tests passed
            if result.test_cases:
                return all(tc.status == CaseStatus.PASSED for tc in result.test_cases)

            # If no specific test cases, check overall success flag
            return result.success

        except Exception as e:
            logger.exception("Error running reproduction test: %s", e)
            return False

    async def _check_regressions(
        self, adapter: TestFrameworkAdapter
    ) -> tuple[bool, str, list[str]]:
        """Run full test suite to check for regressions.

        Args:
            adapter: Test framework adapter.

        Returns:
            Tuple of (regressions_found, test_output, failing_test_names).
        """
        try:
            # Run all tests (test_files=None means all tests)
            result = await adapter.run_tests(
                self._project_root,
                test_files=None,
                timeout=120.0,
            )

            # Use raw_output from result
            test_output = result.raw_output[:MAX_STDOUT_LENGTH] if result.raw_output else ""

            # Check for failures
            failing_tests: list[str] = []
            regressions_found = False

            if result.test_cases:
                for tc in result.test_cases:
                    if tc.status != CaseStatus.PASSED:
                        failing_tests.append(tc.name)
                        regressions_found = True
            elif not result.success:
                # No test case details, but tests failed
                regressions_found = True
                failing_tests.append("(unknown - see output)")

            return regressions_found, test_output, failing_tests

        except Exception as e:
            logger.exception("Error running test suite: %s", e)
            return True, f"Test execution failed: {e}", ["(test run failed)"]

    def _generate_verification_notes(
        self,
        *,
        is_verified: bool,
        bug_fixed: bool,
        regressions_found: bool,
        failing_tests: list[str],
    ) -> str:
        """Generate notes about the verification process.

        Args:
            is_verified: Whether the fix is verified.
            bug_fixed: Whether the bug is fixed.
            regressions_found: Whether regressions were found.
            failing_tests: List of failing test names.

        Returns:
            Verification notes.
        """
        if is_verified:
            return "Fix verified successfully. Bug is fixed and no regressions detected."

        notes_parts: list[str] = []

        if not bug_fixed:
            notes_parts.append(
                "Bug not fixed - reproduction test still fails. "
                "The fix may be incomplete or incorrect."
            )

        if regressions_found:
            notes_parts.append(
                f"Regressions detected - {len(failing_tests)} test(s) started failing "
                f"after applying the fix:"
            )
            notes_parts.extend(
                f"  - {test_name}" for test_name in failing_tests[:MAX_FAILING_TESTS_TO_SHOW]
            )

            if len(failing_tests) > MAX_FAILING_TESTS_TO_SHOW:
                notes_parts.append(
                    f"  ... and {len(failing_tests) - MAX_FAILING_TESTS_TO_SHOW} more"
                )

            notes_parts.append(
                "\nThe fix needs to be revised to avoid breaking existing functionality."
            )

        if not notes_parts:
            notes_parts.append(
                "Verification completed but results are inconclusive. Manual review recommended."
            )

        return "\n".join(notes_parts)
