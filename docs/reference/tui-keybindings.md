> [← Volver al índice](../INDEX.md) · [Reference](README.md)

# TUI keybindings

La TUI (Textual) levanta cuando se corre cualquier `*-pipeline run` con `--tui` (default). Refresh interval: **250 ms**. Render en el thread principal; el orchestrator corre en un worker thread (`cli/_tui_runner.py`).

Si stderr no es TTY, la TUI se autodesactiva (REQ-034). Forzarla con `--tui` en headless es un `ConfigurationError` (exit 2).

## Tabs

| Tab | Key | Renderer | Purpose |
|-----|-----|----------|---------|
| PREP | `P` | `tui/prep_tab.py:render_prep` | S0–S4: docs procesados, filtrados, fallados por razón. |
| UPLOAD | `U` | `tui/upload_tab.py:render_upload` | S5: done/failed, throughput (MB/s), ETA, sub-bloque LANES. |
| CHUNKS | `C` | `tui/chunks_tab.py:render_chunks` | Multi-batch: una fila por chunk. |
| BUCKET | `B` | `tui/bucket_tab.py:render_bucket` | Sólo en modo streaming: ocupación del bucket, docs/s prep y upload, LANES. |
| DETAIL | `D` | `tui/detail_tab.py:render_detail` | Drill-down por chunk: tabla de documentos individuales. |

## Atajos globales

| Key | Action |
|-----|--------|
| `P` | Saltar a tab PREP. |
| `U` | Saltar a tab UPLOAD. |
| `C` | Saltar a tab CHUNKS. |
| `B` | Saltar a tab BUCKET. |
| `D` | Saltar a tab DETAIL. |
| `[` | DETAIL — chunk anterior. |
| `]` | DETAIL — chunk siguiente. |
| `Q` | Quit (aborta la corrida y libera locks). |

## Thread model

- **Main thread** — Textual app + render loop.
- **Worker thread** — `MultiBatchOrchestrator` o `StreamingOrchestrator` (`cli/_tui_runner.py:run_orchestrator_with_tui`).
- **Bandwidth sampler thread** (implícito) — alimentado por el logger `cmcourier.metrics.network` vía `_BandwidthHandler`.
- **System metrics daemon** — psutil sampler, 1 por proceso.

El cableado live (TUI ↔ orchestrator) pasa por `TUIDataProvider` (`tui/data_provider.py`), que toma callbacks:
- `recorder_provider` → `active_recorder()` del orchestrator.
- `upload_recorder_provider` → idem (binding independiente para UPLOAD).
- `chunks_provider` → `chunks_snapshot()`.
- `bucket_provider` → `streaming_snapshot()` (sólo `StreamingOrchestrator`).
- `lane_controller` → `pipeline.lane_controller` (070 unificó el binding).

## Ver también

- [`observability-fields.md`](observability-fields.md) — qué snapshots alimentan cada tab.
- [How-to: multi-batch](../how-to/multi-batch.md) — cómo leer la tab CHUNKS.
- [Explanation: streaming vs batched](../explanation/streaming-vs-batched.md) — cómo leer la tab BUCKET.
