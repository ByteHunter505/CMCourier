# Explicaciones — Cómo Funciona CMCourier

> Documentación orientada al entendimiento. **"¿Cómo funciona esto y por qué?"**

Un documento de explicación es para el lector que ya sabe *qué* hace CMCourier y ahora quiere entender *cómo* y *por qué*. Puede incluir racional de diseño, diagramas arquitectónicos, comparaciones con alternativas, y contexto histórico. Es el lugar para discutir tradeoffs y el razonamiento detrás de las decisiones.

Si querés instrucciones prácticas paso a paso, ver [`../how-to/README.md`](../how-to/README.md). Si estás buscando un dato específico (un nombre de columna, un campo de config), el futuro directorio `docs/reference/` es el lugar.

---

## Explicación canónica de dominio

El documento de explicación más importante está **fuera** de este directorio:

- **la spec de dominio del proyecto** — especificación comprensiva de los sistemas fuente y destino, el esquema RVABREP, la arquitectura de pipeline basada en stages, la cascada de resolución de metadatos, las particularidades de CMIS, el modelo de idempotencia, y los niveles de observabilidad.

Se queda donde está porque moverlo invalidaría cross-references en artefactos ya shippeados (la constitución, CONTRIBUTING, plans). Tratalo como canónico cuando no exista una explicación más chica para el tema que te interesa.

---

## Convención de nombres

Los archivos de este directorio se llaman `<concept-slug>.md`. Los slugs son kebab-case, descriptivos y estables. Renombrar es un cambio breaking para links externos — bumpear `CHANGELOG.md`.

Ejemplos (ilustrativos, no shippeados actualmente):

- `stage-architecture.md`
- `metadata-resolution-cascade.md`
- `cmis-session-warmup.md`
- `cyymmdd-date-format.md`
- `idempotency-and-the-tracking-store.md`
- `heavy-light-upload-lanes.md` *(post-MVP)*

---

## Explicaciones disponibles

*(ninguna todavía — esta sección crece a medida que conceptos arquitectónicos merezcan walkthroughs standalone más allá de la spec de dominio)*

| Explicación | Concepto | Profundidad |
|-------------|---------|-------|
| — | — | — |
---

## Escribir una nueva explicación

Al agregar una explicación:

1. Elegí un slug de concepto-sustantivo. El lector pregunta "¿cómo funciona X?".
2. Abrí con el *problema* que el concepto resuelve. ¿Por qué existe?
3. Recorré el concepto, construyendo desde los primeros principios. Diagramas, tablas, fragmentos de código bienvenidos.
4. Compará con alternativas donde sea útil. ¿Por qué este diseño y no otro?
5. Cross-linkeá con la sección relevante de la constitución, la spec de dominio, o las specs que codifican el concepto.
6. Agregá la explicación a la tabla de arriba y a `docs/INDEX.md`.

Una explicación **no** es un tutorial (sin walkthrough curado), **no** es una how-to (sin pasos prácticos), **no** es una referencia (no una lista seca de hechos). Es razonamiento, expresado como prosa que el lector piensa al lado.

---

## Cross-references

- [`docs/INDEX.md`](../INDEX.md) — mapa canónico de toda la documentación
- [`docs/how-to/README.md`](../how-to/README.md) — para recetas prácticas
- la spec de dominio del proyecto — explicación canónica de dominio
- [`.specify/memory/constitution.md`](../../.specify/memory/constitution.md) — ley de ingeniería (el *por qué* detrás de cada regla arquitectónica)
