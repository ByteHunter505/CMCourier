# 061 — Tasks

## Fase 1 — Guard min_samples del AIMD + provider tupla + tests

- [ ] 1.1 `schema.py`: `AutoTuneConfig.min_samples: int = Field(default=20, ge=1)`.
- [ ] 1.2 `auto_tune.py`: `decide(...)` gana keyword
      `sample_count`; cortocircuita con
      `action="insufficient_data"` cuando está por debajo del
      piso.
- [ ] 1.3 `auto_tune.py`: firma del provider →
      `Callable[[], tuple[float, int]]`; `_tick` desempaca.
- [ ] 1.4 `auto_tune.py`: `_tick` trata `insufficient_data`
      como `warmup` (sin update de `last_decision`, sin
      callbacks).
- [ ] 1.5 `metrics.py`:
      `MetricsRecorder.current_stage_p95_with_count` devuelve
      `(p95_ms, count)`.
- [ ] 1.6 `staged.py`: la lambda `p95_provider` de AIMD usa la
      API tupla.
- [ ] 1.7 `multi_batch.py`: `_upload_p95_observer` devuelve
      tupla.
- [ ] 1.8 Tests: `decide` con `sample_count < min` →
      insufficient_data; con `sample_count >= min` → acción
      real (regresión).
- [ ] 1.9 Tests: los call sites existentes de `decide` pasan
      `sample_count=100`.
- [ ] 1.10 Tests: `current_stage_p95_with_count` para vacío +
      poblado.
- [ ] 1.11 Tests: default + validator de
      `AutoTuneConfig.min_samples`.
- [ ] 1.12 Suite completa unit + integration verde; ruff +
      mypy limpios.
- [ ] 1.13 Commit
      `feat(auto-tune): min_samples guard prevents halve on outlier-with-few-samples (061 Phase 1)`.

## Fase 2 — YAMLs de staging

- [ ] 2.1 `sample/config-staging-rvabrep.yaml` —
      `min_samples: 20`.
- [ ] 2.2 `sample/config-staging-rvabrep-mega-heavy.yaml` —
      ídem.
- [ ] 2.3 `sample/config-staging-rvabrep-frequent-heavy-lanes.yaml`
      — ídem.
- [ ] 2.4 Schema-parsear cada YAML para confirmar.
- [ ] 2.5 Commit
      `config(staging): add auto_tune.min_samples to all three staging YAMLs (061 Phase 2)`.

## Fase 3 — CHANGELOG 0.63.0 + version + README + config-ref + FF

- [ ] 3.1 `CHANGELOG.md [0.63.0]` — Fixed.
- [ ] 3.2 `pyproject.toml` 0.62.0 → 0.63.0.
- [ ] 3.3 `.venv/bin/pip install -e . --no-deps`.
- [ ] 3.4 `cmcourier --version` reporta 0.63.0.
- [ ] 3.5 Tick en fila de features de `README.md`.
- [ ] 3.6 `docs/samples/config-reference.yaml` documenta
      `min_samples`.
- [ ] 3.7 Suite completa + ruff + mypy limpios.
- [ ] 3.8 Commit
      `docs(061): CHANGELOG 0.63.0 + version bump + min_samples docs (061 Phase 3)`.
- [ ] 3.9 FF a main.
