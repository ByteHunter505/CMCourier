# 079 — Plan

## Cambio 1: `network_info.py` (nuevo módulo)

```python
"""079: helpers para introspección de interfaces de red.

Se usa para inferir el ``y_max`` del chart de bandwidth de la TUI
cuando el operador no fijó un throttle explícito vía
``cmis.max_bandwidth_mbps``.
"""

from __future__ import annotations

import logging

__all__ = ["detect_link_speed_mbps"]

_log = logging.getLogger(__name__)

# Prefixes de interfaces virtuales / túneles que descartamos al
# buscar la NIC física más rápida. Cubre Linux (docker, br-, veth,
# lo, tun, tap), Windows (Loopback, VPN, VirtualBox), y macOS
# (utun, gif, stf, bridge, awdl, llw).
_VIRTUAL_PREFIXES = (
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

    Excluye interfaces virtuales / túneles por prefix. Devuelve
    ``0.0`` si no encuentra ninguna o si ``psutil`` no está
    disponible (no debería pasar — es runtime dep — pero
    defensivo).
    """
    try:
        import psutil  # noqa: PLC0415 — import lazy intencional
    except ImportError:
        _log.warning("psutil no disponible — link speed detection desactivada")
        return 0.0

    try:
        stats = psutil.net_if_stats()
    except Exception:  # noqa: BLE001
        _log.warning("psutil.net_if_stats() falló — link speed detection desactivada")
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
```

## Cambio 2: `data_provider.py` — usar el helper para el ceiling

Cachear en el constructor:

```python
# En __init__:
configured_ceiling = float(self._cmis_config.max_bandwidth_mbps)
if configured_ceiling > 0:
    self._bandwidth_ceiling_mbps = configured_ceiling
else:
    link_mbps = detect_link_speed_mbps()
    if link_mbps > 0:
        # Mbps → MB/s.
        self._bandwidth_ceiling_mbps = link_mbps / 8.0
    else:
        self._bandwidth_ceiling_mbps = 0.0  # auto-scale fallback

# En la snapshot:
bandwidth_ceiling_mbps=self._bandwidth_ceiling_mbps,
```

Importar `detect_link_speed_mbps` arriba.

## Cambio 3: `chart.py` — barras pegadas + Y axis labels

```python
def render_bar_chart(
    values: list[float],
    *,
    y_max: float,
    height: int = 8,
    width_chars: int = 60,
    color: str = "green",
    show_y_axis: bool = True,
) -> str:
    """..."""
    # ... blank-fill / empty cases — preservar pero usar el nuevo
    # ``_full_width`` que incluye el ancho del label si show_y_axis ...
```

Layout final con label prefix (4 chars right-aligned + ` │ `):

```
 100 │ <60 chars de barras>
  75 │ <...>
  50 │ <...>
  25 │ <...>
   0 │ <...>
```

Sin spacing entre barras: cada barra es 1 char.

Pseudo-código:

```python
LABEL_WIDTH = 4
LABEL_PREFIX_TOTAL = LABEL_WIDTH + 3  # 4 char label + " │ "

def _label_for_row(row, height, cap):
    # ticks @ rows 0, height/4, height/2, 3*height/4
    # mapeo row → fraction
    rows_from_bottom = height - 1 - row
    fraction = (rows_from_bottom + 1) / height
    return cap * fraction
```

Actually mejor: para height=8, etiquetar 4 rows con valores 100%, 75%, 50%, 25% del cap.

Voy a hacerlo más simple: etiquetar las filas según `step = height // 4`. Para height=8, step=2 → labels en rows 0, 2, 4, 6.

```python
def _row_label(row, height, cap):
    """Devuelve la etiqueta numérica para la row, o spaces si no toca."""
    step = max(1, height // 4)
    rows_from_top = row  # 0 = top
    if rows_from_top % step != 0:
        return " " * LABEL_WIDTH
    # cuánta fracción de cap representa esta row (top-to-bottom)
    rows_from_bottom = height - 1 - row
    fraction = (rows_from_bottom + 1) / height
    value = cap * fraction
    if value >= 100:
        return f"{int(round(value)):>4}"
    elif value >= 10:
        return f"{value:>4.0f}"
    else:
        return f"{value:>4.1f}"
```

Probemos: height=8, cap=100, ticks deseados:
- row 0 (top): fraction = 8/8 = 1.0 → 100 ✓
- row 2: fraction = 6/8 = 0.75 → 75 ✓
- row 4: fraction = 4/8 = 0.50 → 50 ✓
- row 6: fraction = 2/8 = 0.25 → 25 ✓
- rows 1,3,5,7: " " * 4 ✓

Bueno.

## Cambio 4: `upload_tab.py` — sin spacing pero ajustar widths

El chart ahora tiene labels prefijadas. Voy a:

```python
chart = render_bar_chart(
    series_values,
    y_max=snap.bandwidth_ceiling_mbps,
    height=8,
    width_chars=60,
    color="green",
    show_y_axis=True,
)
```

El footer del eje (`└─...─┘`) se ajusta al nuevo ancho total
incluyendo el espacio del label. La línea actual usa `─ * 58`;
necesito recalcularlo con el prefix.

Layout final del bloque del chart:

```
  100 │ <60 chars de barras>
   75 │ <...>
   50 │ <...>
   25 │ <...>
    0 └─────────────────...─┘  -60s ............. now
```

El " │ " del label es de 3 chars (` │ `). El footer reemplaza el
` │ ` por ` └─` para alinear visualmente.

Voy a hacer el footer con el mismo prefix `    0 ` (label-aligned) +
`└` + `─` * 60 + `┘`.

## Tests

`tests/unit/tui/test_chart_bar_y_axis.py` nuevo:

1. `test_bars_now_adjacent_no_spaces` — verifica que dos valores
   altos consecutivos no tienen espacio entre.
2. `test_y_axis_labels_appear_at_correct_rows` — height=8, cap=100,
   labels 100/75/50/25 en filas 0/2/4/6.
3. `test_y_axis_disabled_returns_chart_without_labels` — flag off.
4. `test_label_formatting_for_small_values` — cap=10, labels 10.0/7.5/5.0/2.5
   (1 decimal).
5. `test_label_formatting_for_large_values` — cap=1500, labels 1500/1125/...
   sin decimales.

Y para `network_info.py`: `tests/unit/observability/test_network_info.py`:

6. `test_detect_link_speed_returns_max_physical_iface_speed` — mockear
   `psutil.net_if_stats` con un mix de virtual + físico.
7. `test_detect_link_speed_excludes_virtual_prefixes` — solo virtuales,
   devuelve 0.
8. `test_detect_link_speed_handles_psutil_import_error` — psutil
   no disponible.

## Phased commits

1. `feat: add 079 spec, plan, tasks`
2. `feat(observability): add detect_link_speed_mbps helper (079)`
3. `feat(tui): bars adjacent + Y axis labels in chart (079)`
4. `feat(tui): use link speed as bandwidth ceiling fallback (079)`
5. `test: cover 079 chart + network_info`
6. `docs(079): CHANGELOG 0.81.0 + version bump`
