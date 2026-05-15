"""Renderer del tab BUCKET (064 — modo `streaming`).

En modo `streaming` la pipeline es un loop continuo de `producer`-
`consumer`: los `worker`s de PREP (S1-S4) empujan docs preparados
dentro de un **`bucket`** acotado del que los `worker`s de S5
drenan. El tab BUCKET le da al operador una vista live de:

* nivel del `bucket` vs cap (indicador de `back-pressure`)
* pico del `bucket` desde el inicio de la corrida
* throughput de PREP (docs/s entrando al `bucket`, ventana
  deslizante de 5s)
* throughput de S5 (docs/s saliendo del `bucket`, ventana
  deslizante de 5s)
* conteo live de `worker`s (PREP busy/configured, S5 configured)
* conteos acumulativos por estado (S5_DONE, S5_FAILED,
  S1_FILTERED, S1_SKIPPED)

En modo `batched` el renderer imprime un stub de una línea
dirigiendo al operador al tab CHUNKS.
"""

from __future__ import annotations

__all__ = ["render_bucket"]

from cmcourier.tui.data_provider import TUISnapshot


def _int_or_zero(value: object) -> int:
    return value if isinstance(value, int) else 0


def _bar(level: int, cap: int, width: int = 30) -> str:
    if cap <= 0:
        return "[" + " " * width + "]"
    filled = max(0, min(width, round((level / cap) * width)))
    return "[" + ("█" * filled) + (" " * (width - filled)) + "]"


def render_bucket(snap: TUISnapshot) -> str:
    if snap.mode != "streaming" or snap.bucket is None:
        return "BUCKET tab is active in streaming mode only — see CHUNKS for batched runs."

    b = snap.bucket
    cumulative = _summarise_chunks(snap)

    lines: list[str] = [
        "BUCKET",
        "──────",
        (
            f"  level  {b.bucket_level:>5d} / {b.bucket_cap:<5d}  "
            f"{_bar(b.bucket_level, b.bucket_cap)}"
        ),
        f"  peak   {b.bucket_peak:>5d} / {b.bucket_cap:<5d}",
        "",
        "THROUGHPUT (5s window)",
        "──────────────────────",
        f"  PREP   {b.prep_docs_per_s:>7.2f} docs/s",
        f"  S5     {b.upload_docs_per_s:>7.2f} docs/s",
        "",
        "WORKERS",
        "───────",
        f"  PREP   {b.prep_in_flight:>3d} in-flight / {b.prep_workers:<3d} configured",
        f"  S5     up to {b.upload_workers:<3d} consumer threads",
    ]
    # 065: bloque por-`lane` cuando heavy/light está activo.
    if b.lane_snapshot is not None:
        lanes = b.lane_snapshot
        lines.extend(
            [
                "",
                "LANES (heavy/light, 065)",
                "────────────────────────",
                (
                    f"  heavy  budget {lanes.heavy.pool_size:<3d}  busy {lanes.heavy.busy:<3d}  "
                    f"queue {lanes.heavy.queue_depth:<4d}"
                ),
                (
                    f"  light  budget {lanes.light.pool_size:<3d}  busy {lanes.light.busy:<3d}  "
                    f"queue {lanes.light.queue_depth:<4d}"
                ),
                f"  total budget {lanes.total_budget:<3d}",
            ]
        )
    lines.extend(
        [
            "",
            "OUTCOMES (cumulative)",
            "─────────────────────",
            f"  S5_DONE     {cumulative['s5_done']:>6d}",
            f"  S5_FAILED   {cumulative['s5_failed']:>6d}",
            f"  S1_FILTERED {cumulative['s1_filtered']:>6d}",
            f"  S1_SKIPPED  {cumulative['s1_skipped']:>6d}",
        ]
    )
    return "\n".join(lines)


def _summarise_chunks(snap: TUISnapshot) -> dict[str, int]:
    """Lee los resultados acumulativos de la única fila sintética de `chunk`."""
    s5_done = 0
    s5_failed = 0
    s1_filtered = snap.s1_filtered
    s1_skipped = 0
    for chunk in snap.chunks_state:
        s5_done += _int_or_zero(chunk.get("s5_done"))
        s5_failed += _int_or_zero(chunk.get("s5_failed"))
        s1_skipped += _int_or_zero(chunk.get("prep_skipped"))
    return {
        "s5_done": s5_done,
        "s5_failed": s5_failed,
        "s1_filtered": s1_filtered,
        "s1_skipped": s1_skipped,
    }
