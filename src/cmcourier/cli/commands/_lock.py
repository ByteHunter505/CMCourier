"""Per-config exclusive lock for the background runner (024).

Uses POSIX ``fcntl.flock(fd, LOCK_EX | LOCK_NB)`` so contention is
detected immediately (no blocking waits — operators handle retries
via cron / systemd). The lock file lives under
``$XDG_RUNTIME_DIR/cmcourier/`` (or ``/tmp/cmcourier/`` as
fallback) and the path digest is derived from the absolute config
path so two invocations on the same config collide deterministically.

The lock is released by the kernel when the fd closes — including
on ``SIGKILL`` — so a crashed background runner never blocks the
next scheduled instance.
"""

from __future__ import annotations

__all__ = ["LockHeldError", "acquire_config_lock"]

import contextlib
import datetime as _dt
import fcntl
import hashlib
import os
from collections.abc import Iterator
from pathlib import Path


class LockHeldError(Exception):
    """Raised when another process already holds the config lock."""

    def __init__(self, path: Path) -> None:
        super().__init__(f"another instance holds {path}")
        self.path = path


@contextlib.contextmanager
def acquire_config_lock(config_path: Path) -> Iterator[Path]:
    """Hold an exclusive lock for ``config_path`` for the cm body's lifetime.

    Yields the lock file path so callers can include it in error
    messages / observability events. Re-raises ``LockHeldError`` on
    contention. Releases on any exit path.
    """
    lock_path = _lock_path_for(config_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise LockHeldError(lock_path) from exc
        os.ftruncate(fd, 0)
        stamp = _dt.datetime.now(tz=_dt.UTC).isoformat(timespec="seconds")
        os.write(fd, f"{os.getpid()} {stamp}\n".encode())
        try:
            yield lock_path
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _lock_path_for(config_path: Path) -> Path:
    """Deterministic per-config lock path under ``<runtime>/cmcourier/``."""
    digest = hashlib.sha256(str(config_path.resolve()).encode("utf-8")).hexdigest()[:12]
    return _runtime_dir() / "cmcourier" / f"{digest}.lock"


def _runtime_dir() -> Path:
    """Return ``$XDG_RUNTIME_DIR`` when set, else ``/tmp``."""
    xdg = os.environ.get("XDG_RUNTIME_DIR")
    if xdg:
        return Path(xdg)
    return Path("/tmp")
