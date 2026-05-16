# How to: correr múltiples batches en vuelo (`processing.batches_in_flight`)

> [← Volver al índice](../INDEX.md) · [How-to](README.md)

> Disponible desde el cambio **028** (2026-05-11). Permite que una
> migración larga parta sus triggers en `batch`es y corra el prep
> (S0-S4) de un `batch` superpuesto con el upload (S5) de otro.

---

## TL;DR

```yaml
# config.yaml
processing:
  batches_in_flight: 2     # default — uno preparando, uno subiendo
batch_size: 1000           # tamaño de cada chunk
```

```bash
# Usar el default del YAML (N=2)
cmcourier csv-trigger-pipeline run --config prod.yaml

# Override en el CLI para forzar single-batch (comportamiento legacy)
cmcourier csv-trigger-pipeline run --config prod.yaml --batches-in-flight 1

# --resume siempre fuerza N=1 — resumir un batch específico es un one-shot.
```

---

## Qué cambió

Antes de 028, `pipeline.run()` era one-shot:

```
[acquire 20 000 triggers] → S0 → S1 → S2 → S3 → S4 → S5
                                                       ↑
                                                idle mientras
                                                corría S0-S4
```

Después de 028 con `batches_in_flight=2` y `batch_size=1000`:

```
                  ┌────────────────┐
fuente trigger ──►│   chunker      │  20 chunks de 1 000
                  └────────────────┘
                          │
                          ▼
                  ┌────────────────┐
                  │ thread prep    │  S0–S4 del chunk N+1
                  └────────────────┘
                          │
                          ▼   (queue, capacidad 1)
                  ┌────────────────┐
                  │ thread upload  │  S5 del chunk N
                  └────────────────┘
```

Mientras la red está ocupada subiendo el chunk N, la CPU + la fuente
de triggers + RVABREP + los servicios de metadatos preparan el chunk
N+1. Cada chunk recibe su propio `batch_id` en la DB de tracking y
su propio evento de log `batch_summary`.

## Lo que *no* está en 028

- **N > 2** — solo se aceptan `1` y `2`. `3..5` (el rango aspiracional
  original en POST-MVP §7) necesita un refactor más profundo de la
  semántica del `worker pool` S5 compartido; queda documentado como un
  cambio futuro.
- **Vista multi-batch en TUI** — el TUI actualmente muestra un `batch`
  por vez. Cuando el TUI está encendido (`--tui`),
  `batches_in_flight` se fuerza silenciosamente a 1 para que el operador
  vea datos live coherentes. Las corridas headless (`--no-tui` o una
  shell non-TTY como cron) usan el valor configurado.
- **Cuota de bandwidth por-batch** — eso es POST-MVP §8.

---

## Salida para el operador

Cuando `len(chunks) > 1`, el CLI imprime una línea por chunk más
una línea TOTALS:

```
chunk 1/20  batch_id=AAA  total_docs=1000 s5_done=998  s5_failed=2  elapsed_seconds=42.10
chunk 2/20  batch_id=BBB  total_docs=1000 s5_done=1000 s5_failed=0  elapsed_seconds=39.87
...
TOTALS batch_count=20 total_docs=20000 s5_done=19987 s5_failed=13 failed_chunks=0 elapsed_seconds=812.43
```

Cuando solo corre un chunk (ej. fuente chica, o `N=1`), la salida
es el resumen legacy de una línea — byte-idéntico al comportamiento
pre-028.

## Aislamiento de fallos

Si un chunk crashea durante prep o upload, el orquestador captura la
excepción, la loguea a ERROR, agrega el chunk a `failed_chunks`, y
continúa con los chunks restantes. Exit code:

- `0` — todos los chunks tuvieron éxito.
- `1` — al menos un chunk tuvo `s5_failed > 0` O terminó en
  `failed_chunks`.

## Presupuesto de memoria

Cada chunk preparado en vuelo retiene paths de archivos staged +
metadatos en memoria y PDFs en disco en
`assembly.temp_dir/<batch_id>/`. Con `batch_size=1000` y
~10 MB promedio por archivo staged:

- N=1: ~10 GB pico de disco, MB de un dígito de RAM.
- N=2: ~20 GB pico de disco mientras dos chunks están en vuelo,
  aproximadamente 2× RAM de metadatos.

El pico es breve — el thread de upload consume los chunks preparados
tan rápido como puede.

## Cross-references

- POST-MVP roadmap §7: `docs/roadmap/POST-MVP.md`.
- Spec: `specs/028-multi-batch-orchestrator/`.
- Cambio hermano 025 (`worker pool` S5 + AIMD) — el recurso compartido
  por el cual compiten todos los chunks.
