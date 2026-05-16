> [← Volver al índice](../INDEX.md) · [ADRs](README.md)

# ADR-008: Textual TUI como interfaz operativa por defecto

- **Estado**: Aceptado y vigente
- **Fecha**: 2026-05-10
- **Spec(s) relacionadas**: 025 (TUI live + worker pool S5 + AIMD), 041 (TUI fix and features), 042 (TUI metrics bleed), 044 (dashboard limpio), 045 (per-chunk + UPLOAD counters), 052 (CHUNKS tab + DETAIL drill-down), 058 (DETAIL fixes), 064 (BUCKET tab), 067 (TUI streaming fixes)
- **Versión donde se shipping**: 0.27.0 (TUI inicial); evolucionó hasta 0.73.0

## Contexto

CMCourier es operado por **personal del banco** durante ventanas de migración — típicamente de noche, en horarios de bajo tráfico. El perfil del operador es un IT senior que sabe terminales pero no necesariamente Python. La pregunta operativa central durante una migración es:

> "¿Está progresando? ¿A qué ritmo? ¿Si hay errores, de qué tipo? ¿Cuánto falta?"

Para responder eso necesita ver **estado vivo**, no logs:

- Cuántos docs procesados / cuántos fallidos / cuántos saltados.
- Throughput actual (docs/segundo, MB/segundo).
- ETA basado en el rate observado.
- Si hay un stage cuello de botella, cuál.
- Si AIMD está ajustando workers, qué decisión está tomando.

La opción default en herramientas Python sería **structured logging a stdout/stderr** — JSON lines, parseable. Eso lo tenemos (Tier 2/3/4 de observability, spec 020), y es el medio correcto para auditoría posterior y para el `analyze` offline (spec 027). Pero como **lectura en vivo, durante un run**, es ilegible: los JSON pasan demasiado rápido, el operador no puede correlacionar mentalmente "S5_DONE txn_num=X" con "qué proporción del total es".

El logging tradicional resuelve el problema "qué pasó, post-mortem". Una TUI resuelve el problema "qué está pasando, ahora".

## Decisión

Adoptamos **Textual** como framework de TUI. La TUI es el **default** (`--tui` activado) para todos los comandos de pipeline. Logs JSON siguen escribiéndose en paralelo a `logs/*.jsonl`.

Arquitectura:

- **Cinco tabs**: PREP (`P`), UPLOAD (`U`), CHUNKS (`C`), BUCKET (`B`, sólo streaming), DETAIL (`D`).
  - PREP: progreso S0–S4, conteos por reason de filtrado/fallo.
  - UPLOAD: progreso S5, throughput MB/s, ETA, sub-bloque LANES cuando heavy/light está activo.
  - CHUNKS: fila por chunk en modo batched, con timer, rate y status.
  - BUCKET: fill level vs cap, throughput PREP-side y UPLOAD-side en ventana 5s, sub-bloque LANES.
  - DETAIL: drill-down por doc dentro de un chunk; `[` y `]` navegan chunks.
- **Refresh 250 ms.** Mid-frecuencia: lo suficiente para sentirse vivo, no tanto como para parpadear o saturar el render thread.
- **TUI en el thread principal; orquestador en worker thread** (`cli/_tui_runner.py`). Esto invierte el setup naive de "orquestador en main thread, TUI en background" — pero Textual requiere que su event loop corra en el thread principal del proceso.
- **Auto-disable en non-TTY.** Cuando stderr no es un TTY (cron, CI, pytest), `--tui` se apaga silenciosamente. Un `--tui` *explícito* en non-TTY exit-ea con código 2 + `ConfigurationError` claro.
- **`background` no acepta `--tui`.** Por definición, unattended.

## Consecuencias

### Positivas

- **Visibilidad operativa real.** El operador puede mirar la pantalla y saber el estado del run sin parsear nada. Cambio cualitativo vs logs JSON streameados.
- **TUI keybindings para navegación rápida.** `P/U/C/B/D` cambian tab al instante. `[/]` paginan chunks. `Q` sale. Diseñado para "operador con la mano en el teclado mientras toma un mate".
- **Logs JSON siguen siendo el canal de auditoría.** `logs/*.jsonl` se escriben pase lo que pase con la TUI. El `analyze` offline + el `compare`/`trends` (spec 027) consumen los mismos archivos. Cero contradicción entre vista en vivo y vista post-mortem.
- **Auto-disable es robusto.** Cron y CI no rompen. Tests tampoco. El operador que corre en un terminal real tiene TUI; el `background` runner no.
- **Cada tab es renderer independiente.** `render_prep`, `render_upload`, `render_chunks`, `render_bucket`, `render_detail` viven en archivos separados (`tui/prep_tab.py`, etc.). Modificar uno no toca los otros. Esto importó al evolucionar la TUI por specs 041 / 044 / 052 / 064.

### Negativas / Tradeoffs

- **Textual es una dependencia adicional** con sus propias quirks. El changelog tiene varias entradas (041, 042, 044, 045, 052, 058, 067) que arreglan bugs específicos de la integración TUI + orquestador. La superficie no es cero.
- **El orquestador corre en thread no-principal.** Esto introduce sutilezas de thread safety en el binding TUI → estado (resueltas en spec 042 y 058). Cualquier feature nueva que toque el data provider tiene que ser thread-safe.
- **Recompose en runtime no soportado.** Textual no permite agregar/quitar tabs después del mount. Por eso PREP, UPLOAD, CHUNKS y DETAIL se montan siempre; BUCKET se monta siempre pero muestra un stub en modo batched. Es la única vía con Textual.
- **No accesible para non-terminal users.** Si en el futuro alguien quiere una vista web o un dashboard en Slack, hay que portear el data provider — no es reutilizable as-is.
- **Refresh 250 ms** está hardcoded. Lo suficiente para producción pero no parametrizable.

### Neutras

- **CHUNKS tab tiene utilidad limitada en streaming.** Spec 064 lo reemplazó con BUCKET para ese modo. CHUNKS sigue presente pero muestra una fila sintética única en streaming — operador acostumbrado a CHUNKS tiene que adaptarse.

## Alternativas consideradas

- **`rich` Console con `Live`.** Lo consideramos antes de elegir Textual. `rich` es excelente para output formateado y soporta `Live` updates. Pero **no maneja keybindings nativamente** ni layout de tabs — habríamos tenido que construir esa capa nosotros. Textual está construido sobre `rich` y resuelve esos dos problemas out-of-the-box.
- **Logs estructurados sin TUI.** Es lo que teníamos antes de la spec 025. Era ilegible en vivo. La TUI fue una mejora operativa concreta pedida durante el dry-run.
- **Web UI separada.** Habría requerido un servidor HTTP, configuración de port + acceso, exposure decisions con seguridad del banco. Deploy overhead alto, sin ganar nada que la TUI no resuelva.
- **`curses` directo.** Más bajo nivel que Textual. Lo que ganamos en control lo perdemos en boilerplate. Textual sobre Textual sobre `curses` — ya está la pila.
- **TUI off por default.** El operador habría tenido que activarla. Default-on cubre el caso común (terminal interactivo) y auto-disable en non-TTY cubre el caso unattended. Default-off habría sido conservador pero peor UX.
- **Polling de SQLite desde la TUI.** Habría desacoplado la TUI del orquestador. Pero introduce latencia de 1+ segundo entre evento real y display, y consume CPU en queries de polling. El binding directo via `TUIDataProvider` lee el estado in-process en O(1) sin query.

## Ver también

- [Spec 025 — TUI live + worker pool S5 + auto-tune AIMD](../../specs/025-tui-workers-autotune/)
- [Spec 052 — CHUNKS tab + DETAIL drill-down](../../specs/052-chunks-tab-rates-timer-drilldown/)
- [Spec 064 — BUCKET tab](../../specs/064-tui-bucket-tab/)
- [Spec 067 — TUI streaming fixes](../../specs/067-streaming-tui-fixes/)
- [Spec 027 — log analyzer (lectura post-mortem)](../../specs/027-log-analyzer/)
- [ADR-004: AIMD auto-tune](004-aimd-auto-tune.md)
- [ADR-003: modo streaming](003-streaming-mode.md)
