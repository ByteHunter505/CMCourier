# Tunear AIMD para un link lento (o rápido)

> [← Volver al índice](../../INDEX.md) · [How-to](../README.md) · [Operador](README.md)

El AIMD auto-tune (`cmis.auto_tune`) sube y baja el pool de S5 buscando un `target_p95_ms`. Los defaults asumen un link decente. Si el tuyo es lento o muy rápido, los defaults te van a hacer ruido: escalar agresivo en links lentos te tira timeouts, y escalar tímido en links rápidos te subutiliza el ancho de banda.

## Cuándo usarlo

- Vés `Decision halve` repetidamente en `batch_summary` aunque la red no esté saturada → growth muy agresivo.
- Vés `Decision noop` durante minutos con p95 cómodamente bajo el target → growth tímido o `halve_threshold_ratio` insensible.
- Tu link es notoriamente más lento (WAN cross-region) o más rápido (LAN 10 Gb) que el caso default.

## Pre-requisitos

- Auto-tune activado (`cmis.auto_tune.enabled: true`).
- Una corrida previa con logs (`observability.log_dir`) — necesitás datos del AIMD para tunear con sentido.
- Familiaridad con el tab UPLOAD del TUI (sección Auto-tune).

## Pasos

### 1. Medí la línea base

Andá al directorio de logs y abrí `batch_summary` (jsonl rotado por fecha):

```bash
ls sample/logs/
# busque algo como: batch-summary-2026-05-15.jsonl
```

Filtrá las decisiones del AIMD:

```bash
rg '"event":"auto_tune"' sample/logs/batch-summary-2026-05-15.jsonl
```

Te interesan estas variables por decisión:

- `observed_p95_ms` — p95 real medido en la ventana.
- `target_p95_ms` — el objetivo configurado (default 5000 ms).
- `action` — `grow` / `halve` / `noop` / `warmup` / `insufficient_data`.
- `workers_before` / `workers_after`.

Patrón problemático típico para links lentos:

```
action=grow workers 4→5 p95=4800ms
action=grow workers 5→7 p95=5200ms
action=halve workers 7→5 p95=8500ms   ← timeouts/5xx empezaron
action=grow ...
```

Oscilación que no estabiliza = AIMD demasiado agresivo para tu link.

### 2. Ajustes para un link LENTO

Bajá la pendiente de growth y subí la tolerancia antes de halve:

```yaml
cmis:
  auto_tune:
    enabled: true
    target_p95_ms: 8000.0          # default 5000 — más realista para WAN
    growth_factor: 1.10            # default 1.25 — escalá un 10% por step en vez de 25%
    halve_threshold_ratio: 2.0     # default 1.5 — tolerá p95 hasta 2x target antes de halve
    halve_factor: 0.75             # default 0.75 — dejalo, el halve sigue siendo "suave"
    adjustment_interval_s: 60      # default 30 — más ventana para que las decisiones cuenten
    min_samples: 30                # default 20 — más muestras antes de decidir
```

Razonamiento:

- `growth_factor` 1.25 → 1.10: cada step de growth suma ~10% workers en vez de ~25%. Menos pico de carga, menos riesgo de saturar el link.
- `halve_threshold_ratio` 1.5 → 2.0: el halve dispara cuando p95 > 2× target (16 s con target 8 s), no a 1.5× (12 s). Tolerás más latencia transitoria.
- `target_p95_ms` 5000 → 8000: aceptás que tu link genuinamente tiene p95 alto.

### 3. Ajustes para un link RÁPIDO (LAN, intra-DC)

Subí la pendiente de growth:

```yaml
cmis:
  auto_tune:
    enabled: true
    target_p95_ms: 2000.0          # default 5000 — exigís más
    growth_factor: 1.75            # default 1.25 — escalá fuerte
    halve_threshold_ratio: 1.3     # default 1.5 — reaccioná más rápido al deterioro
    max_threads: 80                # default 50 — subí el techo si tu pool puede aguantar
```

Rango válido (del schema): `growth_factor` ∈ [1.0, 4.0], `halve_factor` ∈ [0.05, 1.0], `halve_threshold_ratio` ∈ [1.05, 10.0].

### 4. Verificá en vivo

Re-corré con el TUI abierto, tab UPLOAD (`U`). Sección Auto-tune:

```
Auto-tune:       ON
  target p95:    8,000 ms   observed p95: 6,200 ms
  adjust:        every 60s   next: in 42s
  timeout:       60.0s active   (range 30–600s)
  last move:     grow → workers=12  (28s ago)
```

Patrón sano: `last move` cambia cada uno o dos `adjustment_interval_s`, `observed p95` queda en banda alrededor del target sin oscilar.

### 5. Iterá

Si seguís viendo halves en cascada, bajá `growth_factor` otro escalón (1.10 → 1.05) o subí `target_p95_ms`. Si la corrida queda subutilizando el link (network panel muestra MB/s muy debajo del ancho disponible), subí `growth_factor` o bajá `target_p95_ms`.

## Verificación

Una corrida exitosamente tuneada tiene estas propiedades en `batch_summary`:

```bash
# Conteo de halves: cuantos menos, mejor (idealmente <5% del total de decisions)
rg '"action":"halve"' sample/logs/batch-summary-*.jsonl | wc -l

# Decisiones noop (estabilidad): deberían dominar al final de la corrida
rg '"action":"noop"' sample/logs/batch-summary-*.jsonl | wc -l
```

Throughput sostenido (MB/s en el chart UPLOAD del TUI) sin valles profundos.

## Si algo sale mal

| Síntoma | Diagnóstico | Acción |
|---------|-------------|--------|
| Halves en cascada infinitos | growth todavía agresivo | Bajá `growth_factor` otro escalón |
| `action=insufficient_data` repetido | min_samples muy alto para la corrida | Bajá `min_samples` (mínimo 1) |
| Workers no se mueve nunca | `warmup_seconds` muy alto vs duración total | Bajá `warmup_seconds` (default 60) |
| Timeouts en S5 sin que AIMD ajuste timeout | `timeout_auto_adjust: false` | Ponelo en `true` y revisá `min_timeout_s` / `max_timeout_s` |

## Ver también

- [`configure-heavy-light-lanes.md`](configure-heavy-light-lanes.md) — partir el pool en dos lanes (heavy/light), AIMD controla el total
- [`run-a-streaming-load-against-staging.md`](run-a-streaming-load-against-staging.md) — modo streaming juega bien con AIMD
- [`interpret-the-tui-tabs.md`](interpret-the-tui-tabs.md) — leer el panel auto-tune en el TUI
