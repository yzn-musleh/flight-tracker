"""A simple, crash-safe single-instance lock backed by a PID file.

Not a distributed lock -- just enough to stop a second copy of this bot from
being started against the same Telegram token / SQLite DB on one machine
(Telegram's long-polling API itself would eventually reject a second
getUpdates caller with a 409, but that's a confusing failure mode to debug;
this fails fast with a clear message instead).
"""

import os

LOCK_PATH = os.environ.get("LOCK_PATH", "bot.lock")


class AlreadyRunningError(Exception):
    pass


def pid_is_running(pid: int) -> bool:
    """Best-effort liveness check. Reliable on POSIX (os.kill(pid, 0) raises
    ProcessLookupError/OSError if the pid is gone, without actually sending a
    signal). Python's os.kill on Windows doesn't support signal 0 the same
    way, so a stale lock left by a crashed process may not be detected there
    -- the actual deployment target (Phase 6) is Docker/Linux, where this is
    exact; see PROGRESS.md's Phase 5 entry for the Windows caveat.
    """
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    else:
        return True


def acquire(path: str | None = None) -> None:
    """Raises AlreadyRunningError if another live instance holds the lock.
    A lock file left by a process that's no longer running (a stale lock,
    e.g. after a crash) is detected and silently reclaimed."""
    path = path or LOCK_PATH
    if os.path.exists(path):
        old_pid = None
        try:
            with open(path, encoding="utf-8") as f:
                old_pid = int(f.read().strip())
        except (ValueError, OSError):
            pass
        if old_pid is not None and pid_is_running(old_pid):
            raise AlreadyRunningError(
                f"Another instance appears to already be running "
                f"(pid {old_pid}, lock file {path})."
            )
    with open(path, "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))


def release(path: str | None = None) -> None:
    path = path or LOCK_PATH
    try:
        os.remove(path)
    except OSError:
        pass
