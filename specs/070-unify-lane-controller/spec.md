# 070 — Unificar el LaneController a través de streaming + batched

## Por qué

Reportado por el operador en el run streaming post-067: el
sub-bloque LANES del tab UPLOAD muestra `queue 0` tanto
para HEAVY como para LIGHT — siempre, nunca se mueve. El
bloque LANES del tab BUCKET muestra valores live correctos
de queue para el mismo run.

Misma data, dos renderers, dos fuentes distintas. Causa
raíz: **hay dos instancias independientes de
`LaneController` en un run streaming con
`heavy_light_lanes.enabled: true`**.

### El bug del dual-controller

`StagedPipeline.__init__` construye su propio
`LaneController` cuando `heavy_light_lanes.enabled=True`
(este era el wiring de 036, para el camino dual-pool de S5
batched):

```python
self._lane_controller: LaneController | None = None
if heavy_light_lanes is not None and heavy_light_lanes.enabled:
    self._lane_controller = LaneController(...)
```

`StreamingOrchestrator.__init__` (065) construye **otro**
`LaneController` — el suyo propio — para el dispatcher de
streaming:

```python
self._lane_controller: LaneController | None = None
if self._lanes_config.enabled:
    self._lane_controller = LaneController(...)
```

Las dos instancias existen concurrentemente en un run en
modo streaming. El dispatcher y consumers de **streaming**
llaman a `set_queue_depth(...)` sobre el controller del
**orchestrator**. El controller **batched** (sentado idle
en el pipeline) nunca recibe ningún update.

El wiring de TUI (`cli/app.py` línea 689):

```python
data_provider = TUIDataProvider(
    ...
    lane_controller=pipeline.lane_controller,
    ...
)
```

lee el controller del pipeline — el muerto en streaming. El
tab BUCKET (064) lee a través de un callable
`bucket_provider` separado que devuelve
`orch.streaming_snapshot()` con
`lane_snapshot=self._lane_controller.snapshot()` del
controller del orchestrator — ese está vivo.

Resultado: tab BUCKET correcto, tab UPLOAD muerto.

Más allá del bug de visibilidad, esto también significa
que **AIMD no puede hablarle al lane controller en modo
streaming**. El `set_total_budget` de AIMD pasa a través
de `StagedPipeline._on_pool_resize`:

```python
def _on_pool_resize(self, new_total: int) -> None:
    if self._lane_controller is not None:
        self._lane_controller.set_total_budget(new_total)
    else:
        self._concurrency_limit.set_capacity(new_total)
```

Eso setea el budget sobre el controller (idle) del
**pipeline**. El controller de streaming — el que realmente
gateea la concurrencia per-lane en el run — no recibe
nada. El crecimiento de AIMD en streaming + heavy/light
estuvo silenciosamente roto desde 065.

## Qué

**Un LaneController por run.** El `StagedPipeline` es
dueño de su construcción (como en 036). El
`StreamingOrchestrator` reusa
`self._pipeline.lane_controller` en vez de construir el
suyo propio.

### Cambios en `StreamingOrchestrator`

* Descartar el bloque del constructor que construye
  `self._lane_controller = LaneController(...)`.
* Reemplazar las lecturas de `self._lane_controller` con
  `self._pipeline.lane_controller` (la instancia del
  pipeline).
* La propiedad `lane_controller` ya expuesta para la TUI
  ahora forwardea: `return self._pipeline.lane_controller`.
* Mantener
  `self._lanes_config = config.processing.heavy_light_lanes`
  para el lookup del threshold del dispatcher y la rama
  enabled / disabled.

### Por qué es correcto

* `StagedPipeline._lane_controller` existe solo cuando
  `heavy_light_lanes.enabled=True`. El árbol de decisión de
  same-config del orchestrator de streaming dispara sobre
  el mismo boolean, así que los dos están siempre en
  sync.
* El controller del pipeline está sin usar por el camino
  batched de S5 *porque ese camino no corre en modo
  streaming*. No estamos contendiendo — estamos ocupando
  el slot previamente-vacío.
* El `_on_pool_resize → pipeline.lane_controller.set_total_budget`
  de AIMD ahora steerea correctamente los budgets de lane
  del dispatcher de streaming.
* El wiring de TUI (`cli/app.py`) queda exactamente igual.
  Tanto `pipeline.lane_controller` (tab UPLOAD) como
  `orch.streaming_snapshot().lane_snapshot` (tab BUCKET)
  leen la misma instancia.

### Qué pasa en `lane_controller.start()` / `stop()`

Tanto el camino batched como el camino streaming llaman
`start()` / `stop()` al controller alrededor del trabajo
de S5. Con el controller unificado:

* En modo batched, `_stage_5_dual` ya lo
  arranca/detiene. Sin cambios.
* En modo streaming, `StreamingOrchestrator.run` ya
  arranca/detiene `self._lane_controller` — que ahora es
  la misma instancia del pipeline. Sin cambio de código;
  solo el target se corre.

`LaneController.start()` es idempotente (la
implementación existente se guarda contra
`self._thread is not None`), así que aunque ambos caminos
lo llamaran accidentalmente, no pasa nada.

## Fuera de alcance

- Migrar el camino batched de S5 a compartir la forma del
  dispatcher de streaming. Eso es una spec de
  unificación — no está en alcance acá.
- Agregar una flag CLI para deshabilitar lanes per-modo.
  Los operadores ya pueden hacer eso con
  `heavy_light_lanes.enabled: false` en YAML.

## Criterios de aceptación

- `StreamingOrchestrator` ya no construye un
  `LaneController` en `__init__`. Lee de
  `self._pipeline.lane_controller`.
- La propiedad
  `StreamingOrchestrator.lane_controller` devuelve
  `self._pipeline.lane_controller`.
- El sub-bloque LANES del tab UPLOAD muestra `queue`,
  `in-use`, etc. en vivo matcheando el bloque LANES del
  tab BUCKET (misma fuente de data).
- El `set_total_budget` triggereado por AIMD llega al
  split de semáforo per-lane del dispatcher de
  streaming.
- Todos los tests unitarios existentes pasan
  (incluyendo
  `test_streaming_snapshot_carries_lane_snapshot_when_enabled`
  y `test_lane_queue_depth_never_exceeds_bucket_size` de
  067).
- Test nuevo clavando la unificación: en modo streaming
  + lanes, `pipeline.lane_controller is orch.lane_controller`.
- mypy + ruff limpios.
- CHANGELOG `[0.72.0]`; pyproject 0.71.0 → 0.72.0.

## Notas sobre impacto

* Sin cambios de comportamiento para modo batched.
* Sin cambios de comportamiento para streaming
  single-lane (lanes deshabilitado).
* En modo streaming + lanes:
  - El bloque LANES del tab UPLOAD pasa a estar live.
  - El rebalance de lane impulsado por AIMD pasa a ser
    efectivo (estaba silenciosamente roto pre-070, ver
    "Por qué" arriba).
