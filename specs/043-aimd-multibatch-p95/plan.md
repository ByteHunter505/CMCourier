# 043 — Plan

Tres fases (~1.5 h total).

## Fase 1 — ``AutoTuneController.set_p95_provider`` (~30 min)

### Archivos

- `src/cmcourier/services/auto_tune.py`
  - Nuevo método público ``set_p95_provider(provider)`` que cambia
    atómicamente ``self._p95_provider``. El ``_tick`` existente lee
    vía el atributo, así que un swap toma efecto en el siguiente
    intervalo de 15 s sin reiniciar el thread del controlador.

### Tests

- `tests/unit/services/test_auto_tune.py` (o donde vivan los tests del
  controlador):
  - ``test_set_p95_provider_takes_effect_next_tick`` — arrancar con un
    provider que devuelve 100, swapear a uno que devuelve 5000, correr
    un tick, assertear que el ``observed_p95`` registrado matchea el
    nuevo provider.
  - ``test_set_p95_provider_swap_is_atomic`` — chequeo básico de
    asignación race-free (sin half-state).

### Commit

```
feat(services): AutoTuneController.set_p95_provider swap hook (043 Phase 1)
```

## Fase 2 — El orchestrator multi-batch wirea la fuente de p95 del upload-recorder (~30 min)

### Archivos

- `src/cmcourier/orchestrators/multi_batch.py`
  - Agregar método ``_upload_p95_observer()`` en el orchestrator que
    lee desde ``self.upload_recorder()`` (el slot que introdujo 042)
    y devuelve su ``current_stage_p95("S5")``. Hace fallback a
    ``0.0`` cuando ningún chunk está todavía en UPLOAD.
  - En ``_run_overlapped._upload_loop``, antes de
    ``controller.start()``, llamar
    ``controller.set_p95_provider(self._upload_p95_observer)``.

### Tests

- `tests/unit/orchestrators/test_multi_batch.py`:
  - ``test_overlapped_run_wires_upload_p95_observer`` — correr un
    multi-batch chico con un MetricsRecorder real + un controlador
    falso que captura el provider asignado; assertear que el
    provider es el del lado upload (no el del recorder original del
    pipeline).

### Commit

```
fix(orchestrators): multi-batch AIMD reads p95 from upload-active recorder (043 Phase 2)
```

## Fase 3 — Docs + CHANGELOG 0.46.0 + bump de versión + re-verify F.4 + FF (~30 min)

### Archivos

- `CHANGELOG.md` — ``[0.46.0]`` Fixed (read path de p95 de AIMD
  multi-batch), Changed (AutoTuneController gana
  ``set_p95_provider``), sin Added/Removed.
- `pyproject.toml` 0.45.0 → 0.46.0.
- Tick en fila de features de `README.md`.

### Release dance

```bash
.venv/bin/pip install -e . --no-deps
.venv/bin/cmcourier --version    # esperar 0.46.0
```

### Re-verificación en vivo

Re-correr §F.4:

```bash
.venv/bin/cmcourier rvabrep-pipeline run \
  --config sample/config-staging-rvabrep.yaml \
  --total 200 --batches-in-flight 2 --no-tui
```

Después:

```bash
rg auto_tune_decision sample/logs/app-*.log | python3 -c "
import json, sys
events = [json.loads(l) for l in sys.stdin]
nonzero = [e for e in events if float(e.get('p95_observed_ms', 0)) > 0]
decreases = [e for e in events if e.get('action') == '-1']
print(f'total events: {len(events)}')
print(f'with p95>0: {len(nonzero)}')
print(f'with action -1: {len(decreases)}')
"
```

Aceptación: ``with p95>0`` debe ser ≥ 1, demostrando que AIMD ahora
ve latencia real de S5 en modo multi-batch.

### Commit

```
docs(043): CHANGELOG 0.46.0 + version bump + AIMD live re-verify (043 Phase 3)
```

### FF a main.
