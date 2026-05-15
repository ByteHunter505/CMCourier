# 068 — Crecimiento agresivo de AIMD + halve suave para cargas de archivos pesados

## Por qué

Reportado por el operador durante un run de streaming con
`mockfiles-mixed` (50 KB → 30 MB) contra el staging de
Alfresco: bandwidth pico `<20 MB/s` contra un link de
internet de 300 Mbps (= 37.5 MB/s máximo teórico). El tab
UPLOAD mostró `pool capacity 4-8` para todo el run a pesar
de `max_threads: 50` en YAML. AIMD nunca alcanzó su techo.

Matemática del AIMD existente (`services/auto_tune.decide`):

| Resultado del tick | Acción |
|---|---|
| `p95 < 0.8 × target` | `workers + 1` |
| `p95 > 1.2 × target` | `workers // 2` |
| sino | noop |

Con `adjustment_interval_s: 15` y
`target_p95_ms: 30000`:

* Crecimiento: `+1` por tick de 15 s → 6 → 50 workers
  toma 44 ticks = **11 minutos** de observaciones "en
  slack" ininterrumpidas.
* Trigger de halve: cualquier tick donde `p95 > 36 s`. Con
  archivos de 30 MB cuyo tiempo de upload tiene varianza
  natural (commit del server, re-handshake TLS sobre una
  conexión caída, pausa de GC), `p95 > 36 s` con N=20
  muestras es **fácil de pegar**. Un solo tick malo halvea
  los workers → pierde ~6 min de crecimiento.
* El piso del halve es `min_threads` (default 2). El
  operador puede acotar el fondo, pero la *oscilación*
  mantiene la capacity clavada en ~4-8 todo el run.

El throughput por-upload contra Alfresco es ~2-5 MB/s para
archivos de 30 MB (TLS + multipart + commit del server).
Con 4-8 workers × ~3 MB/s cada uno = 12-24 MB/s agregado.
Matchea el pico observado.

La forma del AIMD es correcta para uploads **chicos,
latency-sensitive** (su diseño viene de la spec, antes de
que 030 introdujera cargas batched de archivos pesados).
Para archivos de 30 MB, el crecimiento es muy lento y el
halve muy agresivo.

## Qué

Tres palancas tunables en `cmis.auto_tune` cambian el AIMD
de "+1 aditivo / ÷2 multiplicativo" a
"multiplicativo-por-tick / halve suave", con umbrales
tunables por el operador.

### Nuevos campos de `AutoTuneConfig`

```python
class AutoTuneConfig(BaseModel):
    ...
    # 068: crecimiento y halve pasan a ser tunables. Pre-068 estaba
    # hardcoded a crecimiento aditivo +1, halve divide-por-2,
    # umbral de halve en 1.2 × target_p95_ms.
    growth_factor: float = Field(default=1.25, ge=1.0, le=4.0)
    halve_factor: float = Field(default=0.75, ge=0.05, le=1.0)
    halve_threshold_ratio: float = Field(default=1.5, ge=1.05, le=10.0)
```

* `growth_factor` ≥ 1.0. Cada tick "grow" incrementa
  workers en `max(current + 1, ceil(current * growth_factor))`.
  El piso `+1` garantiza progreso incluso con `current`
  chico. Con default 1.25: 6 → 8 → 10 → 13 → 17 → 22 →
  28 → 35 → 44 → 50 en **10 ticks (~2.5 min a 15s/tick)**.
* `halve_factor` ≤ 1.0. Cada tick "halve" reduce workers
  en `max(min_threads, ceil(current * halve_factor))`. Con
  default 0.75: 50 → 38, no 50 → 25. La recuperación de un
  halve por falso-positivo es mucho más barata.
* `halve_threshold_ratio` es el multiplicador de bound
  superior. Halve dispara cuando
  `p95 > halve_threshold_ratio × target_p95_ms`. Con
  default 1.5 y `target_p95_ms: 30000`: halve en 45 s, no
  en 36 s. Más tolerancia para varianza natural con
  archivos pesados.

### Lógica `decide()` actualizada

```python
upper = config.halve_threshold_ratio * config.target_p95_ms
lower = 0.8 * config.target_p95_ms  # umbral de crecimiento sin cambios

if observed_p95_ms > upper:
    halved = math.ceil(current_workers * config.halve_factor)
    new_workers = max(halved, config.min_threads)
    return Decision(action="halve", workers=new_workers, ...)

if observed_p95_ms < lower:
    grown = math.ceil(current_workers * config.growth_factor)
    new_workers = min(max(current_workers + 1, grown), config.max_threads)
    return Decision(action="+N", workers=new_workers, ...)
return Decision(action="noop", ...)
```

El label de acción cambia de `"+1"` a `"+N"` para reflejar
que el paso ya no es siempre 1. Los diagnósticos + tests
existentes deben actualizarse.

### Compatibilidad backwards

Los defaults se eligen así un YAML con
`auto_tune.enabled: true` y ninguna de las palancas nuevas
**sí** ve el comportamiento nuevo. Los operadores que
explícitamente quieren la forma pre-068 pueden setear:

```yaml
auto_tune:
  growth_factor: 1.0           # solo aditivo (degenera a +1)
  halve_factor: 0.5            # /2
  halve_threshold_ratio: 1.2   # umbral original
```

Esto está documentado en el CHANGELOG. El default es la
forma nueva porque la forma pre-068 estaba empíricamente
mal para la carga de producción de archivos grandes.

## Fuera de alcance

- Halve reactivo basado en **tasas de error** (conteos
  5xx, retries). Fuera de alcance acá; AIMD solo mira p95
  de latencia.
- AIMD per-lane (lane heavy vs lane light con crecimiento
  independiente). El rebalance por drain del lane
  controller ya hace esto para *capacity* per-lane una
  vez que existe el budget total. AIMD es dueño del
  budget total — set único de palancas.
- target_p95_ms file-size-aware (escalar el target con el
  tamaño promedio de archivo). Una spec futura puede
  plomear esto si el mix de tamaños de archivo del
  operador varía significativamente per run.

## Criterios de aceptación

- `cmis.auto_tune.growth_factor` default a 1.25, rango
  [1.0, 4.0].
- `cmis.auto_tune.halve_factor` default a 0.75, rango
  [0.05, 1.0].
- `cmis.auto_tune.halve_threshold_ratio` default a 1.5,
  rango [1.05, 10.0].
- `decide()`:
  * Paso de crecimiento usa
    `max(current + 1, ceil(current * growth_factor))`.
  * Paso de halve usa
    `max(min_threads, ceil(current * halve_factor))`.
  * Halve dispara cuando
    `p95 > halve_threshold_ratio × target_p95_ms`.
- Todos los tests unitarios pre-068 de AIMD todavía pasan
  después de actualizar los valores esperados a los
  defaults nuevos.
- Tests nuevos cubren: el crecimiento default alcanza max
  en el conteo esperado de ticks; el halve preserva más
  del 50% de capacity; el umbral del halve honra
  `halve_threshold_ratio`.
- El display existente de la TUI de
  `auto_tune_last_action` ("+1") funciona con el nuevo
  label `"+N"`.
- mypy + ruff limpios.
- CHANGELOG `[0.70.0]`; pyproject 0.69.0 → 0.70.0.

## Impacto esperado para el operador

* De 6 → 50 workers en ~2.5 min (10 ticks) vs pre-068 11
  min.
* Un solo outlier de p95 de 45+ s cuesta
  `ceil(current × 0.25)` workers en vez de la mitad. La
  recuperación es `+25%/tick`.
* Para tu carga `mockfiles-mixed` de 30 MB: la capacity
  debería alcanzar el techo de 50 threads dentro de los
  primeros 3 minutos y quedarse ahí. El bandwidth agregado
  debería subir de pico `<20 MB/s` hacia lo que sea que
  Alfresco + tu router de 300 Mbps puedan sostener —
  típicamente en algún lugar en el rango 30-150 MB/s
  dependiendo del tiempo de commit per-request de
  Alfresco.
