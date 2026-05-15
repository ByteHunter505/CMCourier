# Guías How-to — Recetas para Tareas Específicas

> Documentación orientada a problemas. **"¿Cómo hago para…"**

Una guía how-to asume que ya sabés qué es CMCourier y querés lograr un objetivo específico. Es una secuencia de pasos prácticos — sin narrativa, sin explicaciones profundas, sin teoría. Si querés *entender* cómo funciona algo, ver [`../explanation/README.md`](../explanation/README.md). Si sos completamente nuevo en el proyecto, empezá por el [README principal](../../README.md) y el [INDEX](../INDEX.md).

---

## Convención de nombres

Los archivos de este directorio se llaman `how-to-<task-slug>.md` o simplemente `<task-slug>.md` si el verbo es implícito. Los slugs son kebab-case, descriptivos y estables. Renombrar una guía existente es un cambio breaking para links externos — bumpear `CHANGELOG.md`.

Ejemplos (ilustrativos, no shippeados actualmente):

- `run-rvabrep-pipeline.md`
- `configure-cmis-credentials.md`
- `recover-from-failed-batch.md`
- `add-a-new-trigger-source.md`
- `tune-worker-count-for-throughput.md`

---

## Guías disponibles

*(ninguna todavía — esta sección crece a medida que los primeros comandos y pipelines se shippean)*

| Guía | Objetivo | Audiencia |
|-------|------|----------|
| — | — | — |
---

## Escribir una nueva how-to

Al agregar una guía:

1. Elegí un slug preciso basado en verbo. El lector está leyendo esto porque quiere *hacer* algo.
2. Abrí con una oración que dice qué va a lograr el lector.
3. Listá prerrequisitos (herramientas instaladas, env vars seteadas, rol / permisos).
4. Proveé los pasos como lista numerada con comandos copy-pasteables.
5. Cerrá con un paso de verificación — ¿cómo sabe el lector que funcionó?
6. Agregá la guía a la tabla de arriba y a `docs/INDEX.md`.

Una how-to **no** es un tutorial. Los tutoriales enseñan un concepto guiando al lector por un ejemplo curado. Las how-tos resuelven un problema del mundo real que el lector ya tiene.

---

## Cross-references

- [`docs/INDEX.md`](../INDEX.md) — mapa canónico de toda la documentación
- [`docs/explanation/README.md`](../explanation/README.md) — para "cómo funciona"
- la spec de dominio del proyecto — verdad de dominio
- [`CONTRIBUTING.md`](../../CONTRIBUTING.md) — convenciones de workflow
