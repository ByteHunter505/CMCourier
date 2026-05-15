# 068 — Plan

Una sola fase. Cambio de código en 2 archivos + tests.

## Fase 1 — implementación + tests

### `src/cmcourier/config/schema.py`

- Agregar campos `growth_factor`, `halve_factor`,
  `halve_threshold_ratio` a `AutoTuneConfig` con los
  defaults documentados + rangos de validación.

### `src/cmcourier/services/auto_tune.py`

- `decide()`:
  * Reemplazar el hardcoded
    `upper = 1.2 * target_p95_ms` con
    `upper = config.halve_threshold_ratio * config.target_p95_ms`.
  * Reemplazar
    `new_workers = max(current // 2, min_threads)` con
    `max(min_threads, ceil(current * config.halve_factor))`.
  * Reemplazar
    `new_workers = min(current + 1, max_threads)` con
    `min(max(current + 1, ceil(current * config.growth_factor)),
    max_threads)`.
  * Cambiar el label de acción de `"+1"` a `"+N"`.

### Tests

- `tests/unit/services/test_auto_tune.py`
  - Actualizar tests existentes que assertean
    `action == "+1"` para esperar `"+N"`. Verificar que
    el tamaño de paso nuevo es correcto.
  - Test nuevo: `test_grow_uses_growth_factor` —
    current=10, growth_factor=1.25 → new=13 (ceil).
  - Test nuevo: `test_halve_uses_halve_factor` —
    current=50, halve_factor=0.75 → new=38 (ceil).
  - Test nuevo: `test_halve_threshold_ratio_honored` —
    p95=40s, target=30s, ratio=1.2 → halve; ratio=1.5 →
    noop.
  - Test nuevo: `test_grow_floor_plus_one` — current=2,
    growth_factor=1.25 → new=3 (piso `+1`).

- `tests/unit/config/test_schema.py`
  - growth_factor default a 1.25, rechaza <1.0 y >4.0
  - halve_factor default a 0.75, rechaza <=0 y >1.0
  - halve_threshold_ratio default a 1.5, rechaza <=1.0

### Verify

`pytest tests/unit tests/integration -q` verde. ruff + mypy
limpios.

### Commit

```
feat(auto-tune): aggressive growth + soft halve + tolerant threshold (068 Phase 1)
```

## Fase 2 — release

- CHANGELOG `[0.70.0]`
- pyproject 0.69.0 → 0.70.0
- `pip install -e . --no-deps` + chequeo de versión
- Tick en fila de features de README (un bullet)
- FF a main

Commit:
`docs(068): CHANGELOG 0.70.0 + version bump (068 Phase 2)`.
