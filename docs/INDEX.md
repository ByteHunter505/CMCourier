# CMCourier — Índice de Documentación

> El único mapa de cada documento del proyecto. Elegí el cuadrante que coincida con tu intención y entrá.

Este índice es **canónico**: cada artefacto de documentación del repositorio aparece acá. Los READMEs de subdirectorios (bajo `docs/how-to/`, `docs/explanation/`) linkean de vuelta a esta página para la navegación.

La estructura sigue el [framework Diátaxis](https://diataxis.fr): la documentación está dividida por *propósito* (aprender / resolver / consultar / entender) en lugar de por tema.

---

## Para todos

| Documento | Propósito |
|----------|---------|
| [`README.md`](../README.md) | Overview del proyecto, estado actual, cómo empezar |
| [`CHANGELOG.md`](../CHANGELOG.md) | Historia versionada (formato Keep a Changelog) |
| [`CONTRIBUTING.md`](../CONTRIBUTING.md) | Workflow, estándares de commit, reglas de PR, disciplina SDD |

## Ley de ingeniería

| Documento | Propósito |
|----------|---------|
| [`.specify/memory/constitution.md`](../.specify/memory/constitution.md) | Los 9 principios inmutables. Specs y código que los violan son rechazados sin debate |

## Verdad de dominio

| Documento | Propósito |
|----------|---------|
| la spec de dominio del proyecto | Especificación de dominio completa — sistema fuente RVI, sistema destino CMIS, esquema RVABREP, arquitectura de stages, resolución de metadatos, ensamblado de archivos, idempotencia, niveles de observabilidad |

## Planificación del proyecto

| Documento | Propósito |
|----------|---------|
| [`docs/roadmap/POST-MVP.md`](roadmap/POST-MVP.md) | Cada feature diferida más allá del MVP, con intención + diseño + criterios de aceptación |
| `specs/<NNN-feature-slug>/` | Artefactos SDD por cambio (`spec.md`, `plan.md`, `tasks.md`, opcionalmente `research.md` y `data-model.md`). Una carpeta por cambio, numeración append-only |

## Datos de referencia (samples del proyecto legacy)

| Documento | Propósito |
|----------|---------|
| [`docs/samples/csv/`](samples/csv/) | CSVs sample: `MapeoRVI_CM.csv` (Modelo Documental), `MetadatosCM.csv` (definiciones de metadatos por clase), `TriggerExample.csv` (forma de la lista de triggers), y samples de metadatos por fuente (`metadata_clients.csv`, `metadata_accounts.csv`, etc.) |
| [`docs/samples/excel/RVILIB_RVABREP.xlsx`](samples/excel/RVILIB_RVABREP.xlsx) | Volcado real de tabla RVABREP — forma de columnas y filas de ejemplo |
| [`docs/samples/responses/EjemploRespuestaCMIS.txt`](samples/responses/EjemploRespuestaCMIS.txt) | Ejemplo real de respuesta CMIS Browser Binding — útil al implementar el adapter de upload |

## Cómo usar (recetas — orientado a problemas)

Ver [`docs/how-to/README.md`](how-to/README.md) para el índice de guías how-to y la convención de nombres.

- *(ninguna todavía — esta sección crece a medida que pipelines, el comando doctor, y workflows de operador se shippean)*

## Cómo funciona (explicaciones — orientado a entendimiento)

Ver [`docs/explanation/README.md`](explanation/README.md) para el índice de explicaciones y la convención de nombres.

- *(ninguna todavía — esta sección crece a medida que conceptos arquitectónicos reciban walkthroughs standalone; la explicación comprensiva vive en la spec de dominio del proyecto)*
- Futuro: `docs/explanation/tabular-data-source.md` (diferido — la spec/plan en `specs/003-tabular-data-source-adapter/` es suficiente por ahora)

---

## Mantenimiento

Este archivo se actualiza con **cada cambio** que agregue, mueva o renombre un artefacto de documentación. El `tasks.md` del cambio incluye una tarea para actualizar este índice. CONTRIBUTING.md documenta esa responsabilidad.

Cuadrantes futuros (diferidos hasta que aparezca contenido natural):

- **`docs/tutorials/`** — orientado al aprendizaje. Creado cuando exista el primer walkthrough de punta a punta (probablemente cuando shippee `rvabrep-pipeline`).
- **`docs/reference/`** — orientado a información. Creado cuando la superficie de comandos CLI y el schema de config se estabilicen (post-MVP).
