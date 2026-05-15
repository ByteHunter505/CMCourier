# 055 — Plan

Dos fases (~1.25 h total).

## Fase 1 — Pasar batch_id a través del camino de upload + tests (~55 min)

### Archivos

- `src/cmcourier/domain/ports.py`
  - `IUploader.upload` — agregar `*, batch_id: str` (keyword-only,
    requerido) a la firma abstracta + línea del docstring.

- `src/cmcourier/adapters/upload/cmis_uploader.py`
  - `CmisUploader.upload` — agregar `*, batch_id: str`; pasarlo
    a `_emit_upload_attempt`, `_post_with_retries`,
    `_emit_upload_failed`.
  - `_post_with_retries(self, url, data, headers, txn_num, kind="cmis_post", *, batch_id: str)`
    — pasar `batch_id` a las tres llamadas de `_emit_network`.
  - `_emit_network(kind, t0, status, size_bytes, url, batch_id)`
    — `extra["batch_id"] = batch_id`. (Sigue siendo un
    `@staticmethod`.)
  - `_emit_upload_attempt` / `_emit_upload_failed` — agregar
    keyword `batch_id: str`, `extra["batch_id"] = batch_id`.

- `src/cmcourier/orchestrators/staged.py`
  - La llamada `self._uploader.upload(...)` (~línea 916,
    adentro del bloque `StageTimer` de S5) — agregar
    `batch_id=batch_id`. `batch_id` ya está en scope ahí.

### Tests

- `tests/integration/adapters/test_cmis_uploader.py`
  - Los 10 call sites de `uploader.upload(...)` — agregar
    `batch_id="..."` (un literal por test está bien).
  - **Nuevo test de regresión**
    `test_upload_event_reaches_bandwidth_and_slowop_handlers`:
    construir un `MetricsRecorder`,
    `start_batch(batch_id="B1")`, correr un
    `CmisUploader.upload(..., batch_id="B1")` mockeado,
    assertear `recorder.bandwidth.peak_mbps() > 0` /
    `cumulative_bytes() > 0` y
    `recorder.aggregator_snapshot()` no-vacío. La aserción de
    slow-op necesita el recorder construido con
    `slow_op_threshold_ms=0.0` y el logger
    `cmcourier.metrics.network` en INFO. Este es el test que
    ejercita el `_emit_network` *real*.
  - **Nuevo** `test_emit_network_record_carries_batch_id`:
    una aserción más liviana vía `caplog` (o un handler
    captador) de que el record `cmis_upload` tiene
    `record.batch_id == "B1"`.

- Escanear otros call sites: `grep -rn "\.upload(" tests/ src/`
  — solo `staged.py` (cubierto) y `test_cmis_uploader.py`
  (cubierto). Los tests del staged pipeline mockean el uploader
  con `MagicMock`, lo cual no valida la firma — pero correr la
  suite completa para confirmar que nada pasa un posicional
  que ahora colisiona con el marcador keyword-only.

### Verify

Suite completa unit + integration + ruff + mypy. El keyword
requerido hace que `mypy` flagee cualquier call site
perdido.

### Commit

```
fix(s5): thread batch_id through the upload path so network events reach the bandwidth + slow-op handlers (055 Phase 1)
```

## Fase 2 — CHANGELOG 0.58.0 + bump de versión + README + FF (~20 min)

### Archivos

- `CHANGELOG.md` `[0.58.0]` — Fixed (cada evento de red
  `cmis_upload` se descartaba por los handlers per-batch de
  bandwidth + slow-op porque `_emit_network` nunca seteaba
  `batch_id`; el tab UPLOAD mostraba 0 bandwidth / sparkline
  en blanco / sin slow ops en cada run desde 042).
- `pyproject.toml` 0.57.0 → 0.58.0.
- Tick en fila de features de `README.md`.

### Release dance

```bash
.venv/bin/pip install -e . --no-deps
.venv/bin/cmcourier --version    # esperar 0.58.0
```

### Commit

```
docs(055): CHANGELOG 0.58.0 + version bump (055 Phase 2)
```

### FF a main.
