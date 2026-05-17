"""079: helpers para introspección de interfaces de red.

Se usa para inferir el ``y_max`` del chart de bandwidth de la TUI
cuando el operador no fijó un throttle explícito vía
``cmis.max_bandwidth_mbps``. La idea: si no hay techo configurado,
el operador típicamente quiere ver el chart escalado al máximo
teórico de su NIC (1 Gbps → 125 MB/s, 10 Gbps → 1250 MB/s) en
lugar del peak observado, que cambia con cada upload y desbalancea
visualmente el chart.
"""

from __future__ import annotations

import logging

__all__ = ["detect_link_speed_mbps"]

_log = logging.getLogger(__name__)

# Prefixes de interfaces virtuales / túneles que descartamos al
# buscar la NIC física más rápida. Cubre Linux (docker, br-, veth,
# lo, tun, tap), Windows (Loopback, VPN, VirtualBox) y macOS
# (utun, gif, stf, bridge, awdl, llw).
_VIRTUAL_PREFIXES: tuple[str, ...] = (
    "lo",
    "loopback",
    "docker",
    "br-",
    "veth",
    "vmnet",
    "vboxnet",
    "tun",
    "tap",
    "utun",
    "gif",
    "stf",
    "bridge",
    "awdl",
    "llw",
    "vpn",
)


def detect_link_speed_mbps() -> float:
    """Devuelve la velocidad Mbps de la NIC física más rápida UP.

    Excluye interfaces virtuales / túneles por prefix de nombre.
    Devuelve ``0.0`` si no encuentra ninguna física UP con
    ``speed > 0``, o si ``psutil`` no está disponible (no debería
    pasar porque es runtime dep, pero defensivo).
    """
    try:
        import psutil  # noqa: PLC0415 — import lazy intencional
    except ImportError:
        _log.warning("psutil no disponible — link speed detection desactivada")
        return 0.0

    try:
        stats = psutil.net_if_stats()
    except Exception:  # noqa: BLE001
        _log.warning(
            "psutil.net_if_stats() falló — link speed detection desactivada", exc_info=True
        )
        return 0.0

    candidate_speeds: list[float] = []
    for iface, st in stats.items():
        if not st.isup or st.speed <= 0:
            continue
        name_lc = iface.lower()
        if any(name_lc.startswith(p) for p in _VIRTUAL_PREFIXES):
            continue
        candidate_speeds.append(float(st.speed))
    return max(candidate_speeds) if candidate_speeds else 0.0
