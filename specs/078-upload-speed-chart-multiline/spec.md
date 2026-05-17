# 078 — Chart de UPLOAD speed multi-línea con barras delgadas verdes

## Por qué

El sparkline actual del tab UPLOAD (spec 025 fase 3) es **una sola
línea** de caracteres bloque Unicode (``▁▂▃▄▅▆▇█``). Mostraba:

```
 UPLOAD SPEED (60s · MB/s · y: 0 → 100.0)
  ▁▁▂▃▄▅▆▇█████▇▆▅▄▃▂▁
  └──────────────────────────────────────────────┘  -60s ........... now
```

Cabe pero es **demasiado chico para leer**: 1 línea de altura, sin
contraste visual, sin color. El operador que mira la TUI durante
una corrida productiva se pierde la información de throughput a
ojo — tiene que entrecerrar los ojos contra los píxeles del
terminal.

## Qué

Reemplazar el sparkline por un **gráfico de barras vertical multi-línea**:

* **Altura**: 8 líneas (8x más que antes, tampoco gigante).
* **Barras delgadas**: cada barra ocupa 2 columnas (bloque + espacio)
  para tener "aire" entre barras. Visualmente más legible que la
  línea sólida actual.
* **Color verde** (rich markup ``[green]...[/green]``) — Textual
  ``Static`` ya soporta markup, no hace falta tocar el rendering.
* **Sub-niveles verticales**: cada celda Unicode tiene 8 sub-niveles
  (``▁`` a ``█``), así el chart distingue entre 64 niveles totales
  (8 alto × 8 sub) — mucho mejor resolución que los 8 del sparkline.
* **Sub-sampling**: si la serie tiene más valores que el ancho
  disponible (típicamente 60 valores en 30 columnas), se agrupan
  promediando. La sparkline ya viene con 60 valores; mostramos 30
  barras de 2-segundos cada una.

### Footer del chart

Mantener el footer existente (`└─...─┘  -60s ... now`) pero
ajustar para el ancho nuevo.

### Alcance

* **`src/cmcourier/tui/chart.py`**: agregar
  `render_bar_chart(values, *, y_max, height=8, width_chars=60, color="green")`.
  Devuelve un **string multi-línea** con rich markup. Mantiene
  `render_sparkline` existente sin tocar (por si otro tab lo usa
  en el futuro — hoy nada lo referencia, pero el principio open/closed
  evita romper consumers no visibles).
* **`src/cmcourier/tui/upload_tab.py`**: reemplazar la llamada a
  `render_sparkline` por `render_bar_chart`. Ajustar el footer
  del chart al nuevo ancho.

### Fuera de alcance

* **No tocar otros tabs** (PREP, CHUNKS, BUCKET, DETAIL) — ninguno
  usa charts hoy.
* **No agregar configuración** (`chart.height` en YAML, etc.).
  Hardcoded a 8 líneas. Si aparece feedback de "muy alto"/"muy
  bajo", se ajusta en otra spec.
* **No animaciones / smooth scroll**. La TUI refresca cada 250 ms;
  el chart redibujado entero cada vez es aceptable.

## Criterios de aceptación

1. Tab UPLOAD muestra el chart de bandwidth con **8 líneas de altura**.
2. Las barras se ven separadas (con espacio entre cada una) — look
   "barras delgadas" en lugar de línea sólida.
3. Las barras están coloreadas verde (verificable visualmente o
   inspeccionando el output con `[green]` markup).
4. Sub-niveles funcionan: un valor del 50% del cap renderiza 4
   líneas llenas + 4 vacías; un valor del 25% renderiza 2 llenas.
5. Series vacías o todas en cero renderizan 8 líneas de espacios
   (no rompen layout).
6. Tests unit cubren ≥ 6 escenarios.
7. `pytest -m unit` pasa.

## Riesgos

* **Ancho del tab UPLOAD**: el `width=76` del `render_upload` ya
  acomoda 60 caracteres. Con 30 barras × 2 chars = 60 chars,
  fits. Si el operador achica el terminal por debajo de 80
  columnas, parte del chart se corta — pero pasa con todos los
  tabs igual.
* **Cells de altura ≥ 1 vs altura 0**: para un valor pequeño
  (e.g. 0.5 MB/s sobre cap de 100), el sub-nivel cae en 0 → la
  columna queda toda vacía. **Mitigación**: si `ratio > 0`,
  forzamos al menos 1 sub-nivel (`▁` en la línea inferior) para
  que la barra siempre sea visible. Configurable como
  `min_visible_sub_level=1` interno.
* **Compatibilidad con terminales viejos** (Windows Console pre-Win10
  build 14393): los caracteres Unicode block elements pueden
  fallback a "?" o "□". El sparkline actual ya tenía este riesgo;
  no agregamos uno nuevo.
