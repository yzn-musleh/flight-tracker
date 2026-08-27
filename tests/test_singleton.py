"""New in Phase 5: characterizes the single-instance PID-file lock."""

import os
import sys

import pytest

import singleton


def test_acquire_creates_a_lock_file_with_this_pid(tmp_path):
    path = str(tmp_path / "bot.lock")
    singleton.acquire(path)
    with open(path, encoding="utf-8") as f:
        assert int(f.read().strip()) == os.getpid()


def test_second_acquire_by_a_live_process_is_refused(tmp_path):
    path = str(tmp_path / "bot.lock")
    singleton.acquire(path)
    with pytest.raises(singleton.AlreadyRunningError, match=str(os.getpid())):
        singleton.acquire(path)


def test_release_removes_the_lock_file(tmp_path):
    path = str(tmp_path / "bot.lock")
    singleton.acquire(path)
    singleton.release(path)
    assert not os.path.exists(path)


def test_release_is_a_no_op_if_no_lock_exists(tmp_path):
    path = str(tmp_path / "bot.lock")
    singleton.release(path)  # must not raise


@pytest.mark.skipif(
    sys.platform == "win32",
    reason=(
        "os.kill(pid, 0) for a nonexistent pid raises a generic OSError on "
        "Windows (WinError 87), not ProcessLookupError, so pid_is_running "
        "conservatively assumes 'still running' there -- see singleton.py's "
        "docstring. Stale-lock reclaim is verified precisely on POSIX, the "
        "actual Docker/Linux deployment target (Phase 6)."
    ),
)
def test_stale_lock_from_a_dead_process_is_reclaimed(tmp_path):
    path = str(tmp_path / "bot.lock")
    # A pid essentially guaranteed not to be a running process.
    dead_pid = 999999
    with open(path, "w", encoding="utf-8") as f:
        f.write(str(dead_pid))

    singleton.acquire(path)  # must not raise -- reclaims the stale lock

    with open(path, encoding="utf-8") as f:
        assert int(f.read().strip()) == os.getpid()


def test_corrupt_lock_file_is_treated_as_reclaimable(tmp_path):
    path = str(tmp_path / "bot.lock")
    with open(path, "w", encoding="utf-8") as f:
        f.write("not-a-pid")

    singleton.acquire(path)  # must not raise

    with open(path, encoding="utf-8") as f:
        assert int(f.read().strip()) == os.getpid()
