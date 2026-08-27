"""New in Phase 6: characterizes the Docker HEALTHCHECK script's pass/fail
logic (same check regardless of polling vs webhook mode)."""

import os

import healthcheck
import singleton


def test_fails_when_no_lock_file_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(singleton, "LOCK_PATH", str(tmp_path / "bot.lock"))
    assert healthcheck.check() is False


def test_fails_on_a_corrupt_lock_file(tmp_path, monkeypatch):
    path = str(tmp_path / "bot.lock")
    monkeypatch.setattr(singleton, "LOCK_PATH", path)
    with open(path, "w", encoding="utf-8") as f:
        f.write("not-a-pid")
    assert healthcheck.check() is False


def test_passes_when_lock_pid_is_this_live_process(tmp_path, monkeypatch):
    path = str(tmp_path / "bot.lock")
    monkeypatch.setattr(singleton, "LOCK_PATH", path)
    with open(path, "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))
    assert healthcheck.check() is True
