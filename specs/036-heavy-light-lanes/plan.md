# 036 — Plan

El ritmo de fases coincide con cambios multifase previos: RED →
GREEN por fase, commit por fase, FF en el último commit. Total
estimado ~10-12h.

## Fase 1 — Esquema + LaneSplitter (~2h)

### Archivos

- `src/cmcourier/config/schema.py`
  - Nuevo `HeavyLightLanesConfig` (frozen, extra=forbid).
  - `ProcessingConfig.heavy_light_lanes: HeavyLightLanesConfig =
    Field(default_factory=...)`.
  - Validadores: `heavy_initial_ratio` en `[0.0, 1.0]`, todos los
    campos de duración `gt=0`, threshold `> 0`, min_batch `>= 1`.

- `src/cmcourier/services/lane_splitter.py` (nuevo)
  - `Lane = Literal["heavy", "light"]`
  - `@dataclass(frozen=True) class LaneAssignment: heavy: tuple[T,...]; light: tuple[T,...]; is_single_lane: bool`
  - `def split(items, threshold_bytes, min_batch, *, size_of) -> LaneAssignment`
  - Función pura (sin logs, sin I/O).

### Tests

- `tests/unit/config/test_schema.py::TestHeavyLightLanesConfig`
  - Valores por defecto.
  - Los validadores rechazan valores negativos / fuera de rango.
- `tests/unit/services/test_lane_splitter.py` (nuevo)
  - `Batch` pequeño → todos `light`.
  - `Batch` bimodal → división correcta.
  - Todos pequeños → degenerado, único `lane`.
  - Todos grandes → degenerado, único `lane`.
  - Orden preservado dentro de cada `lane`.
  - `accessor` `size_of` custom para distintos tipos de ítem.

### Commit

```
feat(config,services): HeavyLightLanesConfig + LaneSplitter (036 Phase 1)
```

## Fase 2 — LaneController + S5 con pool dual (~4h)

### Archivos

- `src/cmcourier/services/lane_controller.py` (nuevo)
  - `class LaneController`:
    - Posee `heavy_sem: ResizableSemaphore`,
      `light_sem: ResizableSemaphore`.
    - Posee `WorkerPoolStats` por `lane` (o un envoltorio pequeño
      que reutilice la clase existente dos veces).
    - `start(rebalance_interval_s, idle_threshold_s)` — lanza el
      `thread` daemon de `rebalance`.
    - `stop()` — detiene + hace `join`.
    - `set_total_budget(total: int)` — `hook` de `AIMD`,
      redistribuye proporcionalmente.
    - `acquire(lane: Lane)` / `release(lane: Lane)`.
    - `mark_queue_depth(lane, n)` — el `splitter` alimenta esto una
      vez.
    - Loggea eventos estructurados `lane_rebalance`.

- `src/cmcourier/orchestrators/staged.py`
  - En `__init__`: cuando `heavy_light_lanes.enabled`, construir un
    `LaneController` en lugar de (o junto con) el único
    `ResizableSemaphore`.
  - En `_stage_5`: cuando el modo dual está activo Y el `splitter`
    dice "no es único `lane`", enviar cada ítem con su etiqueta de
    `lane`; `_upload_one` adquiere el `semaphore` del `lane` en
    lugar del `concurrency_limit` global.
  - `on_workers_change` de `AIMD`: cuando el modo dual está activo,
    reenviar a `LaneController.set_total_budget(new)` en lugar de
    redimensionar el `semaphore` único.

### Tests

- `tests/unit/services/test_lane_controller.py` (nuevo)
  - La asignación inicial respeta `heavy_initial_ratio`.
  - `set_total_budget` preserva el ratio.
  - `set_total_budget` fuerza `≥1` por `lane` cuando `total ≥ 2`.
  - La detección de drenado migra `worker`s (con `time` mockeado).
  - `acquire`/`release` topean correctamente la concurrencia por
    `lane`.
  - Los eventos de `rebalance` loggeados son estructuralmente
    correctos.
- `tests/integration/pipeline/test_dual_lane_s5.py` (nuevo)
  - `Batch` bimodal + uploader CMIS `mock`. Verificar que todos los
    documentos suben, las divisiones se respetan, no hay deadlocks.
  - Regresión: con `enabled=False`, resultados idénticos al fixture
    de referencia de único `lane`.

### Commit

```
feat(pipeline): LaneController + dual-lane S5 (AIMD-coupled) (036 Phase 2)
```

## Fase 3 — Sub-paneles duales de TUI + eventos estructurados (~2h)

### Archivos

- `src/cmcourier/tui/data_provider.py`
  - Exponer snapshot `lane_controller: LaneController | None` —
    `LaneSnapshot(heavy=PoolSnapshot, light=PoolSnapshot)`.
- `src/cmcourier/tui/widgets/upload.py` (o ubicación actual)
  - Cuando `LaneSnapshot is not None`: renderizar sub-paneles
    HEAVY/LIGHT lado a lado. De lo contrario, renderizar el panel
    único legado.
- Evento de `rebalance` → notificación de TUI (Textual `notify`).

### Tests

- `tests/integration/tui/test_dual_lane_panels.py` (nuevo)
  - Manejar un `LaneSnapshot` falso y tomar `snapshot` del widget
    renderizado.
  - Verificar que el modo de panel único sigue renderizando sin
    cambios.

### Commit

```
feat(tui): dual heavy/light UPLOAD sub-panels + rebalance notifications (036 Phase 3)
```

## Fase 4 — Prueba de throughput + property test de ancho de banda + docs + FF (~3h)

### Archivos

- `tests/integration/pipeline/test_dual_lane_throughput.py` (nuevo)
  - `Batch` sintético de 30 × 1 MB + 5 × 50 MB.
  - Uploader `mock` duerme 0.05 s/MB.
  - Correr un único `lane` → tiempo total T1.
  - Correr dual-`lane` → tiempo total T2.
  - Verificar `T2 ≤ T1 * 0.7`.
  - `@pytest.mark.slow` si es necesario.

- `tests/property/test_bandwidth_dual_lane.py` (nuevo)
  - Hypothesis: `batches` bimodales aleatorios, presupuestos de
    `worker` aleatorios.
  - Suma de bytes/seg registrados entre ambos `lane`s ≤
    `cmis.max_bandwidth_mbps` en cualquier ventana de 1 segundo.

- `docs/how-to/heavy-light-lanes.md` (nuevo)
  - Cuándo habilitar, `trade-offs` de las perillas, cómo leer el
    panel dual de TUI, cómo leer eventos `lane_rebalance` en
    análisis de logs offline.

- `CHANGELOG.md` `[0.37.0]`, tilde del README, POST-MVP §1 marcado
  como SHIPPED.

### Merge FF

```
git checkout main
git merge --ff-only feat/036-heavy-light-lanes
git branch -d feat/036-heavy-light-lanes
```
