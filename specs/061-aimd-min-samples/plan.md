# 061 — Plan

Tres fases. La Fase 1 lleva la ingeniería; 2 y 3 son config +
release.

## Fase 1 — Guard min_samples del AIMD + provider tupla + tests (~40 min)

### Archivos

- `src/cmcourier/config/schema.py`
  - `AutoTuneConfig.min_samples: int = Field(default=20, ge=1)`.

- `src/cmcourier/services/auto_tune.py`
  - `decide(...)` gana keyword `sample_count: int`. Antes de
    la comparación de banda: si
    `sample_count < config.min_samples`, devolver
    `Decision(action="insufficient_data", workers=current_workers,
    timeout_s=current_timeout_s)`.
  - Doc-comment de `Decision.action` actualizado para incluir
    el valor nuevo.
  - `AutoTuneController.__init__` — `p95_provider: Callable[[],
    tuple[float, int]]`.
  - `set_p95_provider` — mismo update de firma.
  - `_tick` — desempacar `(p95, count) = self._p95_provider()`;
    pasar `sample_count=count` a `decide`. Tratar
    `"insufficient_data"` como `"warmup"`: no actualizar
    `last_decision`, no llamar a los callbacks de
    resize/timeout (workers / timeout se quedan iguales).

- `src/cmcourier/observability/metrics.py`
  - `MetricsRecorder.current_stage_p95_with_count(stage: str) -> tuple[float, int]`
    — lee `summary()` una vez, devuelve `(p95_ms, count)`. El
    `current_stage_p95` existente se queda (TUI + analyzer lo
    llaman).

- `src/cmcourier/orchestrators/staged.py`
  - `_build_auto_tune_controller` — cambiar la lambda
    `p95_provider` a
    `lambda: self._metrics.current_stage_p95_with_count("S5")`.

- `src/cmcourier/orchestrators/multi_batch.py`
  - `_upload_p95_observer(self) -> tuple[float, int]` —
    devuelve `(0.0, 0)` cuando no hay upload-active recorder;
    sino lee `rec.current_stage_p95_with_count("S5")`.

### Tests

- `tests/unit/services/test_auto_tune.py`
  - Actualizar cada call site de `decide(...)` existente para
    pasar `sample_count=100` (bien por encima del default 20
    — preserva las aserciones viejas).
  - Nuevo: `test_insufficient_data_when_below_min_samples` —
    `decide(config(min_samples=20), observed_p95_ms=12000.0,
    sample_count=5, current_workers=6,
    current_timeout_s=300.0)` →
    `action == "insufficient_data"`, `workers == 6` (sin
    cambios).
  - Nuevo: `test_min_samples_guard_off_when_count_meets_floor`
    — misma llamada con `sample_count=20` →
    `action == "halve"`.
  - Nuevo: `test_controller_unpacks_tuple_provider` —
    controlador construido con un provider
    `lambda: (12000.0, 5)`; `_tick(60.1)` deja
    `last_decision is None` (insufficient_data está gateado,
    igual que warmup).
  - Actualizar `test_swap_takes_effect_on_next_tick` etc.
    para usar el provider tupla.

- `tests/unit/config/test_schema.py`
  - `AutoTuneConfig().min_samples == 20` (default).
  - `AutoTuneConfig(min_samples=0)` levanta
    `ValidationError`.

- `tests/unit/observability/test_metrics.py` (o donde vivan
  los tests del recorder)
  - `current_stage_p95_with_count("S5")` sobre stage vacío →
    `(0.0, 0)`.
  - Después de grabar 3 muestras (100, 200, 300) →
    `(300.0, 3)`.

### Verify

`pytest tests/unit -q` primero (feedback rápido), después
suite completa + ruff + mypy.

### Commit

```
feat(auto-tune): min_samples guard prevents halve on outlier-with-few-samples (061 Phase 1)
```

## Fase 2 — YAMLs de staging (~10 min)

### Archivos

- `sample/config-staging-rvabrep.yaml`
- `sample/config-staging-rvabrep-mega-heavy.yaml`
- `sample/config-staging-rvabrep-frequent-heavy-lanes.yaml`

Agregar bajo `cmis.auto_tune`:

```yaml
    # 061: no actuar bajo menos de min_samples uploads — protege
    # contra que el p95 nearest-rank quede dominado por un solo
    # outlier de conexión fría en el primer chunk (que solía
    # disparar un halve espurio).
    min_samples: 20
```

### Verify

`.venv/bin/python -c "import yaml; from cmcourier.config.schema import CmisConfigModel; ..."`
para cada YAML — parsea limpio, `min_samples == 20`.

### Commit

```
config(staging): add auto_tune.min_samples to all three staging YAMLs (061 Phase 2)
```

## Fase 3 — CHANGELOG 0.63.0 + version + README + config-ref + FF (~15 min)

### Archivos

- `CHANGELOG.md` `[0.63.0]` — Fixed (AIMD halveaba ante
  outlier-con-pocas-muestras en el primer chunk porque el p95
  nearest-rank está dominado por una sola muestra grande
  cuando N es chico; agregado guard `min_samples`).
- `pyproject.toml` 0.62.0 → 0.63.0.
- Tick en fila de features de `README.md`.
- `docs/samples/config-reference.yaml` documenta
  `cmis.auto_tune.min_samples`.

### Release dance

```bash
.venv/bin/pip install -e . --no-deps
.venv/bin/cmcourier --version    # esperar 0.63.0
```

### Commit

```
docs(061): CHANGELOG 0.63.0 + version bump + min_samples docs (061 Phase 3)
```

### FF a main.
