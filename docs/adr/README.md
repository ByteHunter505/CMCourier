> [← Volver al índice](../INDEX.md) · ADRs

# Architecture Decision Records (ADRs)

> Documentación orientada al **porqué de las decisiones**. Cada ADR captura una decisión arquitectónica que tomamos, el contexto en el que la tomamos, qué alternativas evaluamos y qué consecuencias aceptamos. Si te encontrás peleando con código que parece arbitrario, probablemente la razón vive acá.

Los ADRs son **append-only**: una decisión no se borra, se *supersede*. Cuando una decisión cambia, escribimos un ADR nuevo y marcamos al anterior con `Superseded by ADR-XXX`. La numeración es continua, sin huecos.

Para el "cómo funciona" (la explicación conceptual), ver [`docs/explanation/`](../explanation/README.md). Para el "qué dice la Constitución" (los 9 principios inmutables), ver [`.specify/memory/constitution.md`](../../.specify/memory/constitution.md).

---

## Lista de ADRs

| # | Título | Estado | Fecha |
|---|--------|--------|-------|
| [ADR-001](001-hexagonal-architecture.md) | Arquitectura hexagonal (Ports & Adapters) | Aceptado y vigente | 2026-05-08 |
| [ADR-002](002-sqlite-tracking-store.md) | SQLite como tracking store local | Aceptado y vigente | 2026-05-10 |
| [ADR-003](003-streaming-mode.md) | Modo `streaming` con bucket acotado | Aceptado y vigente | 2026-05-15 |
| [ADR-004](004-aimd-auto-tune.md) | AIMD multiplicativo para auto-tune del pool S5 | Aceptado y vigente | 2026-05-15 |
| [ADR-005](005-processpool-for-s4.md) | `ProcessPoolExecutor` para ensamblado PDF (S4) | Aceptado y vigente | 2026-05-15 |
| [ADR-006](006-heavy-light-lanes.md) | Lanes heavy/light en el pool de upload | Aceptado y vigente | 2026-05-15 |
| [ADR-007](007-csv-trigger-primary-source.md) | CSV externo como fuente primaria de triggers | Aceptado y vigente | 2026-05-10 |
| [ADR-008](008-textual-tui.md) | Textual TUI como interfaz operativa por defecto | Aceptado y vigente | 2026-05-10 |

## Cómo leer un ADR

Cada documento sigue la misma estructura:

1. **Contexto** — qué problema teníamos, qué restricciones operaban, qué intentamos antes.
2. **Decisión** — qué resolvimos hacer, en términos accionables (no aspiracionales).
3. **Consecuencias** — lo bueno, lo malo y lo neutro que esto trae.
4. **Alternativas consideradas** — los otros caminos que evaluamos y por qué no.
5. **Ver también** — links a la explicación conceptual, a las specs originales y a otros ADRs relacionados.

Si una decisión te parece rara y el ADR no la explica, eso es un bug del ADR — abrí una issue.
