> [← Volver al índice](../INDEX.md) · Runbooks

# Runbooks de CMCourier

Guías para apagar incendios en producción. Cada runbook arranca por el síntoma observable — el operador llega acá porque algo está roto, no porque quiera aprender la arquitectura. Para eso están las páginas de [`explanation/`](../explanation/README.md).

## Cómo se lee un runbook

1. **Síntoma**: confirmá que es el caso correcto. Si no matchea, salí y buscá otro.
2. **Diagnóstico rápido**: 3–5 comandos para confirmar la hipótesis en menos de 2 minutos.
3. **Mitigación inmediata**: detené el sangrado. No arregla la causa raíz, pero estabiliza.
4. **Resolución**: ataca la causa raíz.
5. **Verificación**: confirmá que volvió la normalidad antes de declarar resuelto.
6. **Post-mortem**: qué documentar y qué prevenir.

## Índice

| Runbook | Severidad | Tiempo estimado |
|---------|-----------|-----------------|
| [`cmis-down.md`](cmis-down.md) — IBM Content Manager devuelve 5xx en oleada | P1 | 15 min |
| [`as400-down.md`](as400-down.md) — AS400 inalcanzable, `TriggerError` o queries colgadas | P1 | 20 min |
| [`disk-full-during-prep.md`](disk-full-during-prep.md) — `OSError: No space left on device` en S4 | P1 | 15 min |
| [`tracking-db-locked.md`](tracking-db-locked.md) — `sqlite3.OperationalError: database is locked` | P2 | 10 min |
| [`migration-stuck-no-progress.md`](migration-stuck-no-progress.md) — 0 docs/s sostenido, queue_depth no baja | P2 | 20 min |

## Convenciones

- **P1**: hay datos en riesgo o producción detenida. Atender ya.
- **P2**: la corrida no avanza pero el estado es recuperable. Atender en el turno.
- **P3**: degradación tolerable. Atender en horario.
- Todos los comandos asumen que tu `cwd` es la raíz del repo y que el config vive en `sample/config.yaml` (ajustá al tuyo).
- `Ctrl+C` siempre es graceful. `kill -9` deja la tracking DB en estado raro — usalo solo como último recurso.

## Ver también

- [How-to operador](../how-to/operator/README.md) — recetas reproducibles (no incendios).
- [Explanation](../explanation/README.md) — por qué la arquitectura es así.
- [`recover-from-a-corrupted-tracking-db.md`](../how-to/operator/recover-from-a-corrupted-tracking-db.md) — receta paso a paso si la DB está irrecuperable.
