# 053 — Clasificador de cuellos de botella: stage-aware + asociación de logs por ventana de tiempo

## Por qué

`cmcourier analyze batch <id>` se supone que le dice al operador
*dónde se fue el tiempo* y *si el cuello de botella está adentro
del programa o afuera de él*. En un run de staging real de 95
docs — donde S5 (upload) fue **26× el siguiente stage** (S5 p50
635 ms vs S4 p50 24 ms) — reportó:

> **Bottleneck: under-utilized (confidence 1.00)** — "no
> bottleneck class crossed its threshold"

Exactamente al revés. Tres bugs concretos, todos en
`services/analyze.py`:

1. **El clasificador ignora `stage_summary`.** `classify_bottleneck`
   *recibe* el desglose por-stage pero está marcado
   `# noqa: ARG001 — reserved for future heuristics` — sin uso.
   La señal de cuello de botella más clara — "qué stage domina
   el tiempo per-doc" — está justo ahí, batch-tagged y exacta.
2. **Los records de red & sistema no se asocian con el batch.**
   `LogReader._read_filtered` los filtra por
   `rec["batch_id"] == batch_id`, pero esos records no llevan
   **ningún `batch_id`** (solo un timestamp). Así que
   `network_summary` queda vacío y `system_summary` queda
   `None` — el clasificador queda ciego a sus dos tiers
   non-stage.
3. **Thresholds absolutos, sin razonamiento relativo.** Incluso
   con data de sistema: la detección `network-bound` está
   muerta cada vez que `cmis_max_bandwidth_mbps == 0` (el
   default — sin tope configurado); `worker-saturated` (rank 0)
   *enmascara* `network-bound` (rank 4) aunque la saturación es
   un *síntoma* de uploads lentos, no una causa; y el gate
   absoluto fallback `cmis_upload p95 > 5000 ms` nunca dispara
   para un run cuyo S5 domina por 26× pero cuyo p95 es "solo"
   1139 ms.

## Qué

### 1. Hacer el desglose de stages la señal PRIMARIA

Reescribir `classify_bottleneck` para liderar con
`stage_summary` — siempre está presente (el record
`batch_summary` es batch-tagged) y es la señal más directa de
cuello de botella.

- Sumar el `sum_ms` de cada stage (tiempo total a través de
  todos los docs en ese stage). El **stage dominante** es el
  que tiene la share más grande.
- Cuando la share del stage dominante sobre el tiempo total de
  stages cruza un umbral (`_STAGE_DOMINANCE = 0.45`), clasificar
  por stage:
  - **S5** → `upload-bound` — el server CMIS + red. *Afuera del
    programa* — el cliente solo puede empujar más
    concurrencia.
  - **S4** → `assembly-bound` — CPU de armado de PDF.
    *Adentro* — nuestro.
  - **S3** → `metadata-bound` — resolución de metadata.
    *Adentro.*
  - **S2** → `mapping-bound`; **S1** → `indexing-bound`;
    **S0** → `trigger-bound`. *Adentro.*
- `confidence` = la share dominante. `reasons` nombra el stage,
  su share, su p50/p95, y si está adentro o afuera del programa
  — así el operador recibe la *respuesta a su pregunta*, no
  solo un label.

### 2. Las métricas de sistema REFINAN, no son gates

Cuando `system_summary` está presente (después del fix #3
abajo), las señales cpu/mem/disk pasan a ser **razones
corroborantes** apendizadas al veredicto del stage — p. ej.
`assembly-bound` + "confirmado: process_cpu > 80% en 70% de
las muestras". `worker-saturated` se reporta como **razón de
síntoma** junto al veredicto (típicamente junto a
`upload-bound`), nunca *en lugar de* él. La señal de fracción
de muestras `network-bound` todavía contribuye cuando hay un
tope de banda configurado, pero su ausencia ya no esconde un
veredicto `upload-bound` — el desglose de stages lleva eso.

`under-utilized` solo se devuelve cuando **ningún** stage
domina **y** ninguna señal de sistema dispara — un run
genuinamente idle.

### 3. Asociar records de red/sistema por ventana de tiempo

`LogReader.read_batch` ya lee primero el `metrics-*.jsonl`
batch-tagged. Desde el `batch_summary` deriva la ventana del
batch — `[ts − elapsed_s, ts]` — y filtra `network-*.jsonl`
(campo timestamp `ts`) y `system-*.jsonl` (campo timestamp
`ts_iso`) a esa ventana en vez de por el `batch_id` ausente.
Sin cambios de emitter — los records ya llevan timestamps.

## Fuera de alcance

- Taguear records de red/sistema con un `batch_id` real
  (plomería de contextvar a través del worker pool de S5). La
  asociación por ventana de tiempo es exacta para runs
  single-batch; para runs **overlapped (N=2)** las ventanas se
  solapan y un record de red/sistema en el solape puede
  atribuirse a cualquiera de los dos batches — documentado
  como limitación conocida. El desglose por-stage (batch-tagged,
  exacto) es la señal primaria y no se ve afectado.
- Heurísticas de `analyze compare` / `analyze trends` — sin
  cambios; ya usan la data de stage directamente.
- Nuevo surface en la TUI — `analyze` es la herramienta CLI;
  la TUI ya tiene su propia view por-stage.

## Criterios de aceptación

- `classify_bottleneck` sobre un desglose de stages donde el
  `sum_ms` de S5 domina devuelve `upload-bound` con una razón
  nombrando S5, su share, y "afuera del programa" — un test
  reproduce la forma del run de 95 docs y lo assertea (el caso
  de regresión).
- Un desglose S4-dominante devuelve `assembly-bound` ("adentro
  del programa"); un desglose balanceado sin stage dominante
  devuelve `under-utilized`.
- La data de sistema `worker-saturated` ya no sobrescribe un
  veredicto de stage — aparece como una línea de razón, no como
  la clasificación.
- `network-bound` se reporta para un run S5-dominante **incluso
  cuando `cmis_max_bandwidth_mbps == 0`** (vía la señal de
  stage) — un test assertea que la regresión vieja
  "under-utilized" se fue.
- `LogReader.read_batch` puebla `network_summary` /
  `system_summary` desde records que no tienen `batch_id`,
  filtrados a la ventana de tiempo del batch — un test con
  fixtures windoweados lo assertea.
- Suite completa unit + integration verde; mypy + ruff limpios.
- `CHANGELOG.md [0.56.0]`; `pyproject.toml` 0.55.0 → 0.56.0.

## Notas sobre estrategia de tests

`classify_bottleneck` es una función pura — los tests le
alimentan resúmenes de stage / network / sistema y assertean la
clasificación + razones, incluyendo la **forma exacta del run
de 95 docs** como el test de regresión nombrado. La asociación
por ventana de tiempo del `LogReader` se testea con fixtures
JSONL cuyos timestamps cruzan la ventana del batch. La suite
existente `test_analyze*.py` es el gate de regresión.
