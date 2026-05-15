"""Lock exclusivo por config para el runner en background (024).

Cross-platform. En POSIX usa ``fcntl.flock(fd, LOCK_EX | LOCK_NB)``;
en Windows usa ``msvcrt.locking(fd, LK_NBLCK, 1)`` contra el primer
byte del archivo de lock. Ambas APIs son non-blocking, asi que la
contencion se detecta al toque (sin esperas bloqueantes: los retries
los maneja el operador via cron / `Task Scheduler`). El archivo de
lock vive bajo ``$XDG_RUNTIME_DIR/cmcourier/`` en POSIX (con fallback
a ``/tmp``) o bajo ``tempfile.gettempdir()/cmcourier/`` en Windows. El
digest del path se deriva del path absoluto de la config asi dos
invocaciones sobre la misma config colisionan deterministicamente.

El kernel (POSIX) o la capa de file system de Windows libera el lock
automaticamente cuando se cierra el `fd`, incluido el caso de
``SIGKILL`` / terminacion forzada del proceso, asi que un runner en
background crasheado nunca bloquea a la siguiente instancia
agendada.
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
    """Se levanta cuando otro proceso ya tiene tomado el lock de la config."""

    def __init__(self, path: Path) -> None:
        super().__init__(f"another instance holds {path}")
        self.path = path


@contextlib.contextmanager
def acquire_config_lock(config_path: Path) -> Iterator[Path]:
    """Mantiene un lock exclusivo de ``config_path`` por la vida del cm body.

    Yieldea el path del archivo de lock para que los callers lo puedan
    incluir en mensajes de error / eventos de observabilidad.
    Re-eleva ``LockHeldError`` ante contencion. Lo libera por
    cualquier camino de salida.
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
    """Path deterministico del lock por config bajo ``<runtime>/cmcourier/``."""
    digest = hashlib.sha256(str(config_path.resolve()).encode("utf-8")).hexdigest()[:12]
    return _runtime_dir() / "cmcourier" / f"{digest}.lock"


def _runtime_dir() -> Path:
    """Directorio runtime por usuario para los archivos de lock.

    En POSIX prefiere ``$XDG_RUNTIME_DIR`` cuando esta seteado, sino cae
    a ``/tmp``. Windows no tiene el concepto XDG: siempre usa el
    directorio temp del sistema (``%TEMP%`` / ``tempfile.gettempdir()``).
    """
    if sys.platform == "win32":
        return Path(tempfile.gettempdir())
    xdg = os.environ.get("XDG_RUNTIME_DIR")
    if xdg:
        return Path(xdg)
    return Path("/tmp")


# ---------------------------------------------------------------------------
# Primitivas de lock especificas por plataforma
# ---------------------------------------------------------------------------

if sys.platform == "win32":

    def _platform_lock(fd: int) -> None:
        # `msvcrt.locking()` lockea ``nbytes`` arrancando en la posicion
        # ACTUAL del archivo. El `fd` esta fresco (offset 0), asi que
        # esto lockea el byte 0. Ante contencion `msvcrt` levanta OSError:
        # lo re-wrappeamos como `BlockingIOError` para que el manejo de
        # excepciones del caller siga siendo agnostico a la plataforma.
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise BlockingIOError(str(exc)) from exc

    def _platform_unlock(fd: int) -> None:
        # Despues del `write()` el puntero de archivo paso del byte 0.
        # Hacemos seek hacia atras para que el unlock apunte al mismo
        # byte que lockeamos.
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)

else:

    def _platform_lock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _platform_unlock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)
