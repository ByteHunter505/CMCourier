# 079 — Eje Y con etiquetas + barras pegadas + detección de link speed

## Por qué

Post-078 el chart de UPLOAD ya es multi-línea con color verde, pero
tres feedback del operador:

1. **Barras separadas con aire** — la convención en chart-of-bars
   es las barras pegadas. El espacio entre cada barra (parte de la
   "delgada" del 078) confunde más que ayuda.
2. **Eje Y sin números** — no hay forma de leer "¿en cuánto está
   esta barra?" sin contar pixels y dividir.
3. **Techo del eje Y no es referencia útil** — hoy es el peak
   observed cuando ``max_bandwidth_mbps == 0``. Eso significa
   que el chart auto-re-escala con cada upload — `peak` cambia →
   las barras cambian de altura post-hoc. Lo que el operador
   quiere es un techo **fijo** que represente la capacidad real:
   el max throttle configurado, o si no hay throttle, la velocidad
   máxima de la NIC.

## Qué

### Cambios en el chart

1. **Barras pegadas**: cada barra ocupa 1 columna (no 2). El `+ " "`
   del 078 se quita. Para 60 valores de la serie → 60 columnas de
   barras pegadas.

2. **Eje Y con etiquetas**: prefijar cada row del chart con una
   etiqueta numérica derecha-alineada de 4 chars + ` │` separator.
   Etiquetas en 4-5 ticks distribuidos sobre el alto del chart:
   top (100%), 75%, 50%, 25%. La línea de eje inferior gana un
   label "0".

   Layout aproximado:

   ```
    100 │ ▆█                            
     75 │ ████ ▂▆      ▆                
     50 │ ████ ███▃   ▃█▆               
     25 │ ████ ████▆ ▅████▅             
      0 └────────────────────────────────
   ```

3. **Detección de link speed**: nueva función helper
   ``detect_link_speed_mbps()`` en
   ``observability/network_info.py`` (módulo nuevo) que usa
   ``psutil.net_if_stats()`` para encontrar la NIC física más
   rápida que esté UP. Filtra interfaces virtuales típicas
   (``lo``, ``docker``, ``br-*``, ``veth*``, ``vmnet``, ``vboxnet``,
   ``tun*``, ``tap*``) por prefix. Devuelve ``0.0`` si no se puede
   detectar.

4. **Ceiling logic en ``data_provider``**: el campo
   ``bandwidth_ceiling_mbps`` de la snapshot ahora se computa así:

   * Si ``cmis.max_bandwidth_mbps > 0``: ese es el techo (throttle
     configurado por el operador, en MB/s).
   * Si no: detectar link speed via psutil → convertir Mbps → MB/s
     (÷ 8).
   * Si psutil falla / NIC speed = 0: ``0.0`` (auto-scale al peak,
     comportamiento pre-079 como fallback).

   La detección se hace **una vez** al inicio del run (caché en
   ``DataProvider``), no por cada refresh de TUI.

### Alcance

* **`src/cmcourier/tui/chart.py`**:
  * `render_bar_chart` actualizado: barras pegadas (sin `+ " "`),
    nuevo parámetro `show_y_axis: bool = True`, etiquetas
    derecha-alineadas con `│` separator.
  * Nueva constante interna `_Y_AXIS_LABEL_WIDTH = 4`.

* **`src/cmcourier/observability/network_info.py`** (nuevo):
  * `detect_link_speed_mbps() -> float` que retorna la velocidad
    Mbps de la NIC física más rápida UP, o 0 si no detecta.

* **`src/cmcourier/tui/data_provider.py`**:
  * Importar `detect_link_speed_mbps`.
  * En el constructor del DataProvider, computar el ceiling una
    vez basado en la lógica de arriba. Cachearlo en
    `self._bandwidth_ceiling_mbps`.
  * La snapshot usa el cached value.

* **`src/cmcourier/tui/upload_tab.py`**:
  * `width_chars` del chart pasa a 60 (sin cambio de total porque
    el padding "  " sigue afuera). Total width: 6 (label + `│`) +
    60 (chart) = 66 chars. Eso es 4 más que los 60 actuales — el
    título y el footer se ajustan para alinearse.

### Fuera de alcance

* **No configuración nueva en YAML** para el ceiling. Reusamos
  `cmis.max_bandwidth_mbps`. Si en el futuro el operador quiere
  un ceiling distinto solo para la TUI (sin throttle real),
  agregamos una opción aparte.
* **No mostramos el origen del ceiling** ("from config" /
  "from NIC" / "auto") en la TUI. El title del chart ya dice
  ``y: 0 → X.Y`` con el número; si el operador quiere saber por
  qué ese número, es info de log/diagnóstico.

## Criterios de aceptación

1. Chart muestra barras pegadas — no hay espacios entre columnas
   adyacentes con valor > 0.
2. Cada row del chart tiene una etiqueta numérica izquierda
   (4 chars right-aligned + ` │`). Ticks en top, 75%, 50%, 25%
   del cap.
3. La línea inferior del eje (`└──...`) tiene un `0 ` alineado a
   la izquierda.
4. Cuando `cmis.max_bandwidth_mbps == 0` y `psutil` detecta una
   NIC de 1000 Mbps, el ceiling resulta `125.0 MB/s`.
5. Cuando `psutil` solo encuentra interfaces virtuales (Docker,
   loopback, VPN), el ceiling cae a auto-scale.
6. Tests unit cubren ≥ 6 escenarios nuevos.
7. `pytest -m unit` pasa.

## Riesgos

* **psutil overhead**: una llamada al constructor del DataProvider,
  toma <5ms. No afecta el TUI refresh loop.
* **Interfaz "rápida" virtual**: en sistemas con muchas interfaces
  Docker/VPN, la heurística de "más rápida que no sea virtual"
  puede equivocarse. Para corridas reales en bancos, las NICs
  físicas son las únicas UP — bajo riesgo.
* **Cambio de UX**: las barras pegadas + el label cambian
  visualmente el chart. Si al operador no le gusta, retoque
  futuro.
