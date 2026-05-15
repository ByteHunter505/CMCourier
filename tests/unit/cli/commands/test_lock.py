"""Tests unitarios para el módulo de `lock` por config (024)."""

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
    """Aísla `XDG_RUNTIME_DIR` por test."""
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
        # La segunda adquisición funciona después de release.
        with acquire_config_lock(config_path):
            pass

    def test_contention_raises_lock_held(self, runtime_dir: Path, tmp_path: Path) -> None:
        config_path = _make_config_file(tmp_path)
        with acquire_config_lock(config_path) as lock_path:
            # Mantiene un segundo fd sobre el mismo path y prueba
            # `LOCK_EX | LOCK_NB`. El wrapper debería rechazar igual.
            with pytest.raises(LockHeldError) as ei, acquire_config_lock(config_path):
                pass
            assert ei.value.path == lock_path

    def test_pid_and_timestamp_written(self, runtime_dir: Path, tmp_path: Path) -> None:
        config_path = _make_config_file(tmp_path)
        # Lee DESPUÉS del release: `msvcrt.locking` en Windows es un
        # `lock` mandatorio, así que leer mientras el `lock` está
        # tomado levanta `PermissionError`. El archivo del `lock`
        # persiste tras el release en ambas plataformas.
        with acquire_config_lock(config_path) as lock_path:
            pass
        content = lock_path.read_text()
        # Espera "<pid> <iso-timestamp>".
        match = re.match(r"^(\d+) (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})", content)
        assert match is not None
        assert int(match.group(1)) == os.getpid()

    def test_lock_file_truncated_on_reacquire(self, runtime_dir: Path, tmp_path: Path) -> None:
        config_path = _make_config_file(tmp_path)
        # El primer acquire crea el archivo y escribe pid+timestamp.
        with acquire_config_lock(config_path) as lock_path:
            pass
        # Simula basura `stale` dejada por un dueño previo (entre
        # acquires, cuando nadie tiene el `lock` — el `lock` mandatorio
        # de Windows bloquearía esta escritura de otra manera).
        lock_path.write_text("stale junk from a previous owner\n")
        # El segundo acquire trunca primero.
        with acquire_config_lock(config_path):
            pass
        content = lock_path.read_text()
        assert "stale junk" not in content
        assert str(os.getpid()) in content

    @pytest.mark.skipif(_IS_WINDOWS, reason="fcntl is POSIX-only; msvcrt has different semantics")
    def test_low_level_fcntl_blocks_after_acquire(self, runtime_dir: Path, tmp_path: Path) -> None:
        """Sanity check de que la semántica subyacente de `fcntl` es no-bloqueante."""
        config_path = _make_config_file(tmp_path)
        with acquire_config_lock(config_path) as lock_path:
            fd = os.open(str(lock_path), os.O_RDWR)
            try:
                with pytest.raises(BlockingIOError):
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally:
                os.close(fd)
