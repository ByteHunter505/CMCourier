> [← Volver al índice](../INDEX.md) · Reference

# Reference

Material de consulta — tablas, schemas, listas. Está pensado para escaneo rápido, no para lectura lineal. Cada nombre, tipo y default coincide byte a byte con el código fuente.

## Documentos

| Doc | Cuándo abrirlo |
|-----|----------------|
| [`cli.md`](cli.md) | Cuando necesitás recordar el nombre exacto de un comando, una flag o un exit code. |
| [`config-schema.md`](config-schema.md) | Cuando estás escribiendo el YAML y necesitás saber qué keys son válidas, sus defaults y sus rangos. |
| [`tui-keybindings.md`](tui-keybindings.md) | Atajos de teclado de la TUI, una tabla por tab. |
| [`observability-fields.md`](observability-fields.md) | Cada estructura JSON que termina en `logs/` — qué campos lleva, qué unidades, de dónde sale el dato. |
| [`tracking-db-schema.md`](tracking-db-schema.md) | DDL exacto del SQLite (`migration_log`, `migration_batch`, `document_cache`), PRAGMAs y la state machine de `status`. |
| [`error-codes.md`](error-codes.md) | La jerarquía completa de excepciones (`CMCourierError` y subclases) con la acción que debe tomar el operador. |
| [`glossary.md`](glossary.md) | Glosario alfabético — qué quiere decir AIMD, RVABREP, S0–S7, light/heavy lane, etc. |

## Convenciones

- Field names, types, valid values y nombres de excepciones se mantienen en **inglés** dentro de tablas y bloques de código.
- Explicaciones cortas en Rioplatense Spanish (voseo).
- Identificadores en `backticks`.
- Si una fila contradice el código fuente, **gana el código**. Abrí un issue y se corrige.

## Ver también

- [Explanation](../explanation/README.md) — el "por qué" detrás de cada decisión.
- [How-to](../how-to/README.md) — recetas paso a paso para escenarios comunes.
- [`docs/_internal/dossier.md`](../_internal/dossier.md) — la fuente de verdad de la que sale este material.
