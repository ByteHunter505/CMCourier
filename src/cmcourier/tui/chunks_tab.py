"""Renderer del tab CHUNKS (030 — vista live multi-batch, 041 — desglose completo).

Para corridas single-batch (``batches_in_flight=1``) el tab está
vacío (sin `chunk`s). Para ``batches_in_flight=2`` cada `chunk` se
enciende a medida que pasa por QUEUED → PREP → UPLOAD → DONE
(o FAILED), con conteos done/skip/fail por `stage` + wall-clock
elapsed + una fila TOTAL agregada.
"""

from __future__ import annotations

__all__ = ["render_chunks"]

from cmcourier.tui.data_provider import TUISnapshot

_STATUS_GLYPH: dict[str, str] = {
    "QUEUED": "·",
    "PREP": "▶",
    "UPLOAD": "▲",
    "DONE": "✓",
    "FAILED": "✗",
}

# Un `stage` que aún no arrancó renderiza todos sus slots con este guion
# para que la tabla se lea como "todavía no hicimos ese trabajo" en lugar
# de "lo hicimos, cero resultados".
_DASH = "—"


def render_chunks(snap: TUISnapshot, *, width: int = 92) -> str:
    """Devuelve un string multi-línea que describe el estado por-`stage` de cada `chunk`.

    El ``width`` por defecto de 92 cols es más ancho que el resto del TUI
    (~80) porque la tabla de desglose necesita los bloques PREP y UPLOAD
    lado a lado. Los operadores que ven el TUI en una terminal estándar
    de 80 cols ven la tabla wrappeada visualmente — es aceptable: el tab
    CHUNKS es una vista de "acercate a mirar", no una de un vistazo.
    """
    lines: list[str] = []
    lines.append(f"CHUNKS — pipeline {snap.pipeline}")
    lines.append("─" * width)
    chunks = snap.chunks_state
    if not chunks:
        lines.append("  (no chunks yet — orchestrator hasn't acquired triggers)")
        lines.append("")
        return "\n".join(lines)

    counts = {"DONE": 0, "PREP": 0, "UPLOAD": 0, "QUEUED": 0, "FAILED": 0}
    for chunk in chunks:
        status = str(chunk.get("status", "QUEUED"))
        if status in counts:
            counts[status] += 1

    lines.append(
        f"  total {len(chunks)}   done {counts['DONE']}   "
        f"prep {counts['PREP']}   upload {counts['UPLOAD']}   "
        f"queued {counts['QUEUED']}   failed {counts['FAILED']}"
    )
    lines.append("")
    lines.append(
        f"  {'idx':>3}  {'batch_id':<14}  {'docs':>5}  {'MB':>7}  "
        f"{'PREP d/s/f/x (elap)':<22}  {'UPLOAD d/s/f (elap)':<22}  "
        f"{'RATE MB/s·d/s':<16}  {'state':<10}"
    )
    lines.append("  " + "─" * (width - 2))

    totals = {
        "docs": 0,
        "bytes": 0,
        "prep_done": 0,
        "prep_skipped": 0,
        "prep_failed": 0,
        "prep_filtered": 0,
        "prep_elapsed_s": 0.0,
        "upload_done": 0,
        "upload_skipped": 0,
        "upload_failed": 0,
        "upload_elapsed_s": 0.0,
    }
    for chunk in chunks:
        idx = _int(chunk.get("chunk_idx"), -1)
        batch_id = str(chunk.get("batch_id", ""))[:14] or _DASH
        status = str(chunk.get("status", "?"))
        glyph = _STATUS_GLYPH.get(status, "?")
        doc_count = _int(chunk.get("doc_count"), 0)
        total_bytes = _int(chunk.get("total_bytes"), 0)
        mb = total_bytes / 1_048_576.0
        prep_done = _int(chunk.get("prep_done"), 0)
        prep_skipped = _int(chunk.get("prep_skipped"), 0)
        prep_failed = _int(chunk.get("prep_failed"), 0)
        prep_filtered = _int(chunk.get("prep_filtered"), 0)
        prep_elapsed = _float(chunk.get("prep_elapsed_s"), 0.0)
        upload_done = _int(chunk.get("s5_done"), 0)
        upload_skipped = _int(chunk.get("upload_skipped"), 0)
        upload_failed = _int(chunk.get("s5_failed"), 0)
        upload_elapsed = _float(chunk.get("upload_elapsed_s"), 0.0)

        prep_cell = _stage_cell(
            done=prep_done,
            skipped=prep_skipped,
            failed=prep_failed,
            filtered=prep_filtered,
            elapsed_s=prep_elapsed,
            has_started=status in ("PREP", "UPLOAD", "DONE", "FAILED"),
        )
        upload_cell = _stage_cell(
            done=upload_done,
            skipped=upload_skipped,
            failed=upload_failed,
            elapsed_s=upload_elapsed,
            has_started=status in ("UPLOAD", "DONE", "FAILED"),
        )
        # 052: throughput de UPLOAD por `chunk` — bytes/sec y docs/sec.
        rate_cell = _rate_cell(total_bytes, upload_done, upload_elapsed)

        lines.append(
            f"  {idx:>3}  {batch_id:<14}  {doc_count:>5}  {mb:>7.1f}  "
            f"{prep_cell:<22}  {upload_cell:<22}  {rate_cell:<16}  {glyph} {status:<8}"
        )

        # Agrega. Las filas QUEUED contribuyen con su plan (docs/bytes)
        # pero sin resultados — coincide con lo que el operador espera
        # de la fila TOTAL.
        totals["docs"] += doc_count
        totals["bytes"] += total_bytes
        totals["prep_done"] += prep_done
        totals["prep_skipped"] += prep_skipped
        totals["prep_failed"] += prep_failed
        totals["prep_filtered"] += prep_filtered
        totals["prep_elapsed_s"] += prep_elapsed
        totals["upload_done"] += upload_done
        totals["upload_skipped"] += upload_skipped
        totals["upload_failed"] += upload_failed
        totals["upload_elapsed_s"] += upload_elapsed

    lines.append("  " + "─" * (width - 2))
    total_mb = totals["bytes"] / 1_048_576.0
    prep_total_cell = _stage_cell(
        done=int(totals["prep_done"]),
        skipped=int(totals["prep_skipped"]),
        failed=int(totals["prep_failed"]),
        filtered=int(totals["prep_filtered"]),
        elapsed_s=float(totals["prep_elapsed_s"]),
        has_started=any(
            int(totals[k]) > 0
            for k in ("prep_done", "prep_skipped", "prep_failed", "prep_filtered")
        ),
    )
    upload_total_cell = _stage_cell(
        done=int(totals["upload_done"]),
        skipped=int(totals["upload_skipped"]),
        failed=int(totals["upload_failed"]),
        elapsed_s=float(totals["upload_elapsed_s"]),
        has_started=any(
            int(totals[k]) > 0 for k in ("upload_done", "upload_skipped", "upload_failed")
        ),
    )
    total_rate_cell = _rate_cell(
        int(totals["bytes"]), int(totals["upload_done"]), float(totals["upload_elapsed_s"])
    )
    label = f"TOTAL ({len(chunks)} chunks)"
    lines.append(
        f"  {label:<19}  {int(totals['docs']):>5}  {total_mb:>7.1f}  "
        f"{prep_total_cell:<22}  {upload_total_cell:<22}  {total_rate_cell:<16}"
    )
    lines.append("")
    return "\n".join(lines)


def _rate_cell(total_bytes: int, docs: int, elapsed_s: float) -> str:
    """052: formatea la celda de throughput de UPLOAD — ``MB/s · docs/s``.

    Un ``elapsed_s`` no positivo (`stage` no arrancado, o instantáneo)
    renderiza un guion en vez de dividir por cero.
    """
    if elapsed_s <= 0:
        return f"{_DASH} · {_DASH}"
    mbps = (total_bytes / 1_048_576.0) / elapsed_s
    dps = docs / elapsed_s
    return f"{mbps:.1f} · {dps:.1f}"


def _stage_cell(
    *,
    done: int,
    skipped: int,
    failed: int,
    elapsed_s: float,
    has_started: bool,
    filtered: int | None = None,
) -> str:
    """Formatea una celda ``done/skip/fail (elapsed)``.

    Cuando ``has_started`` es False (p.ej. filas QUEUED para el `stage`
    UPLOAD), renderiza guiones para que el operador no confunda
    "todavía no" con "cero".

    051: la celda PREP pasa ``filtered`` (filas RVABREP con código de
    baja excluidas en S1) → la celda renderiza
    ``done/skip/fail/filtered``. La celda UPLOAD lo deja ``None`` → el
    desglose clásico de tres vías.
    """
    if not has_started:
        tail = f"/{_DASH}" if filtered is not None else ""
        return f"{_DASH}/{_DASH}/{_DASH}{tail}   {_DASH}"
    elapsed_str = f"{elapsed_s:.1f}s" if elapsed_s > 0 else _DASH
    counts = (
        f"{done}/{skipped}/{failed}/{filtered}"
        if filtered is not None
        else f"{done}/{skipped}/{failed}"
    )
    return f"{counts}   ({elapsed_str})"


def _int(v: object, default: int) -> int:
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v)
    return default


def _float(v: object, default: float) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    return default
