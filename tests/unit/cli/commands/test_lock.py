"""Unit tests for the per-config lock module (024)."""

from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path

import pytest

from cmcourier.cli.commands._lock import (
    LockHeldError,
    _lock_path_for,
    acquire_config_lock,
)

if sys.platform != "win32":
    import fcntl

pytestmark = pytest.mark.unit
_IS_WINDOWS = sys.platform == "win32"


@pytest.fixture
def runtime_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolate XDG_RUNTIME_DIR per test."""
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    return tmp_path


def _make_config_file(tmp_path: Path, name: str = "config.yaml") -> Path:
    path = tmp_path / name
    path.write_text("# placeholder\n")
    return path


class TestLockPathFor:
    def test_deterministic_for_same_config(self, runtime_dir: Path, tmp_path: Path) -> None:
        config_path = _make_config_file(tmp_path)
        assert _lock_path_for(config_path) == _lock_path_for(config_path)

    def test_different_configs_get_different_paths(self, runtime_dir: Path, tmp_path: Path) -> None:
        a = _make_config_file(tmp_path, "a.yaml")
        b = _make_config_file(tmp_path, "b.yaml")
        assert _lock_path_for(a) != _lock_path_for(b)

    @pytest.mark.skipif(_IS_WINDOWS, reason="XDG_RUNTIME_DIR is POSIX-only")
    def test_uses_xdg_runtime_dir(self, runtime_dir: Path, tmp_path: Path) -> None:
        config_path = _make_config_file(tmp_path)
        lock_path = _lock_path_for(config_path)
        assert lock_path.is_relative_to(runtime_dir / "cmcourier")

    def test_falls_back_to_system_temp_when_xdg_unset(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
        config_path = _make_config_file(tmp_path)
        lock_path = _lock_path_for(config_path)
        expected_base = (Path(tempfile.gettempdir()) if _IS_WINDOWS else Path("/tmp")) / "cmcourier"
        assert lock_path.is_relative_to(expected_base)


class TestAcquireConfigLock:
    def test_acquire_release_roundtrip(self, runtime_dir: Path, tmp_path: Path) -> None:
        config_path = _make_config_file(tmp_path)
        with acquire_config_lock(config_path) as lock_path:
            assert lock_path.exists()
        # Second acquisition works after release.
        with acquire_config_lock(config_path):
            pass

    def test_contention_raises_lock_held(self, runtime_dir: Path, tmp_path: Path) -> None:
        config_path = _make_config_file(tmp_path)
        with acquire_config_lock(config_path) as lock_path:
            # Hold a second fd on the same path and try LOCK_EX | LOCK_NB.
            # Our wrapper should reject identically.
            with pytest.raises(LockHeldError) as ei, acquire_config_lock(config_path):
                pass
            assert ei.value.path == lock_path

    def test_pid_and_timestamp_written(self, runtime_dir: Path, tmp_path: Path) -> None:
        config_path = _make_config_file(tmp_path)
        # Read AFTER release: msvcrt.locking on Windows is a mandatory
        # lock, so reading while the lock is held raises PermissionError.
        # The lock file persists after release on both platforms.
        with acquire_config_lock(config_path) as lock_path:
            pass
        content = lock_path.read_text()
        # Expect "<pid> <iso-timestamp>".
        match = re.match(r"^(\d+) (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})", content)
        assert match is not None
        assert int(match.group(1)) == os.getpid()

    def test_lock_file_truncated_on_reacquire(self, runtime_dir: Path, tmp_path: Path) -> None:
        config_path = _make_config_file(tmp_path)
        # First acquire creates the file and writes pid+timestamp.
        with acquire_config_lock(config_path) as lock_path:
            pass
        # Simulate stale junk left behind by a previous owner (between
        # acquires, when nobody holds the lock — Windows mandatory lock
        # would block this write otherwise).
        lock_path.write_text("stale junk from a previous owner\n")
        # Second acquire truncates first.
        with acquire_config_lock(config_path):
            pass
        content = lock_path.read_text()
        assert "stale junk" not in content
        assert str(os.getpid()) in content

    @pytest.mark.skipif(_IS_WINDOWS, reason="fcntl is POSIX-only; msvcrt has different semantics")
    def test_low_level_fcntl_blocks_after_acquire(self, runtime_dir: Path, tmp_path: Path) -> None:
        """Sanity check that the underlying fcntl semantics are non-blocking."""
        config_path = _make_config_file(tmp_path)
        with acquire_config_lock(config_path) as lock_path:
            fd = os.open(str(lock_path), os.O_RDWR)
            try:
                with pytest.raises(BlockingIOError):
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally:
                os.close(fd)
