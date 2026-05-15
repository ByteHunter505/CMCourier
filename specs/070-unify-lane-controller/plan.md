# 070 — Plan

Una sola fase. Refactor de toque mínimo.

## Fase 1 — código + tests

### `src/cmcourier/orchestrators/streaming.py`

* `__init__`: descartar el bloque de construcción
  `LaneController(...)`. Mantener
  `self._lanes_config = config.processing.heavy_light_lanes`
  (el dispatcher necesita el threshold).
* Descartar el campo `self._lane_controller` — usar una
  propiedad:

```python
@property
def lane_controller(self) -> LaneController | None:
    """070: un solo LaneController por run, en propiedad de StagedPipeline."""
    return self._pipeline.lane_controller
```

* Cada referencia a `self._lane_controller` lee a través
  de la propiedad (sin necesidad de renombrar en los call
  sites dado que el patrón de acceso a atributo matchea).
* El bloque de `run()` que llama
  `self._lane_controller.start()` / `.stop()` y el
  código del dispatcher / consumer se quedan como están;
  solo que ahora pegan la instancia del pipeline.

### Tests

`tests/unit/orchestrators/test_streaming.py`:

* Test nuevo
  `test_streaming_reuses_pipeline_lane_controller`:
  - Construir un `_FakePipeline` con un campo
    `_lane_controller` sintético (instancia real de
    `LaneController`).
  - Construir el orchestrator con lanes_enabled=True.
  - Assertear
    `orch.lane_controller is pipeline.lane_controller`.

* Actualizar `_FakePipeline` para exponer un atributo
  `lane_controller` matcheando el contrato.

### Verify

`pytest tests/unit tests/integration -q` verde. ruff +
mypy limpios.

### Commit

```
fix(streaming): unify LaneController with pipeline — UPLOAD-tab LANES live (070 Phase 1)
```

## Fase 2 — release

- CHANGELOG `[0.72.0]`
- pyproject 0.71.0 → 0.72.0
- `pip install -e . --no-deps` + chequeo de versión
- Tick en fila de features de README
- FF a main

Commit:
`docs(070): CHANGELOG 0.72.0 + version bump (070 Phase 2)`.
