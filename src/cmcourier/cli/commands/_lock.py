"""Per-config exclusive lock for the background runner (024).

Cross-platform. On POSIX uses ``fcntl.flock(fd, LOCK_EX | LOCK_NB)``;
on Windows uses ``msvcrt.locking(fd, LK_NBLCK, 1)`` against the first
byte of the lock file. Both APIs are non-blocking, so contention is
detected immediately (no blocking waits — operators handle retries
via cron / Task Scheduler). The lock file lives under
``$XDG_RUNTIME_DIR/cmcourier/`` on POSIX (falling back to ``/tmp``)
or under ``tempfile.gettempdir()/cmcourier/`` on Windows. The path
digest is derived from the absolute config path so two invocations
on the same config collide deterministically.

The kernel (POSIX) or the Windows file-system layer releases the
lock automatically when the fd closes — including on ``SIGKILL`` /
forced process termination — so a crashed background runner never
blocks the next scheduled instance.
"""

from __future__ import annotations

__all__ = ["LockHeldError", "acquire_config_lock"]

import contextlib
import datetime as _dt
import hashlib
import os
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl


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
            _platform_lock(fd)
        except BlockingIOError as exc:
            raise LockHeldError(lock_path) from exc
        os.ftruncate(fd, 0)
        stamp = _dt.datetime.now(tz=_dt.UTC).isoformat(timespec="seconds")
        os.write(fd, f"{os.getpid()} {stamp}\n".encode())
        try:
            yield lock_path
        finally:
            with contextlib.suppress(OSError):
                _platform_unlock(fd)
    finally:
        os.close(fd)


def _lock_path_for(config_path: Path) -> Path:
    """Deterministic per-config lock path under ``<runtime>/cmcourier/``."""
    digest = hashlib.sha256(str(config_path.resolve()).encode("utf-8")).hexdigest()[:12]
    return _runtime_dir() / "cmcourier" / f"{digest}.lock"


def _runtime_dir() -> Path:
    """Per-user runtime directory for lock files.

    On POSIX prefers ``$XDG_RUNTIME_DIR`` when set, else falls back to
    ``/tmp``. Windows has no XDG concept; always uses the system temp
    directory (``%TEMP%`` / ``tempfile.gettempdir()``).
    """
    if sys.platform == "win32":
        return Path(tempfile.gettempdir())
    xdg = os.environ.get("XDG_RUNTIME_DIR")
    if xdg:
        return Path(xdg)
    return Path("/tmp")


# ---------------------------------------------------------------------------
# Platform-specific lock primitives
# ---------------------------------------------------------------------------

if sys.platform == "win32":

    def _platform_lock(fd: int) -> None:
        # msvcrt.locking() locks ``nbytes`` starting at the CURRENT file
        # position. The fd is fresh (offset 0), so this locks byte 0.
        # On contention msvcrt raises OSError — re-wrap as BlockingIOError
        # so the caller's exception handling stays platform-agnostic.
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise BlockingIOError(str(exc)) from exc

    def _platform_unlock(fd: int) -> None:
        # After write() the file pointer has moved past byte 0. Seek back
        # so the unlock targets the same byte we locked.
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)

else:

    def _platform_lock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _platform_unlock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)
