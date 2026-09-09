"""Docker HEALTHCHECK script.

Passes iff this container's bot process is alive and holds its own
single-instance lock (singleton.py).
"""

import sys

import singleton


def check() -> bool:
    try:
        with open(singleton.LOCK_PATH, encoding="utf-8") as f:
            pid = int(f.read().strip())
    except (OSError, ValueError):
        return False
    return singleton.pid_is_running(pid)


if __name__ == "__main__":
    sys.exit(0 if check() else 1)
