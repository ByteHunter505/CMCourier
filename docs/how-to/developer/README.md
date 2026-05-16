# How-to para Desarrolladores

> [← Volver al índice](../../INDEX.md) · [How-to](../README.md)

Recetas para los que tocan código de CMCourier: agregar campos de configuración, extender el modelo de metadata, sumar una fuente de datos nueva, correr la batería de tests, o cazar un cuello de botella. Cada guía es **una tarea, un objetivo, copy-paste**.

## Convenciones

- **Pre-requisitos** asumen siempre: Python 3.11+, repo clonado, `uv pip install -e ".[dev]"` ejecutado, `pre-commit install` corrido. Los hooks (`ruff`, `ruff format`, `mypy`) son no negociables — `--no-verify` está prohibido por Constitución.
- **Identificadores** (clases, módulos, flags, columnas YAML) van en inglés. La narrativa, en castellano rioplatense.
- Antes de abrir un PR, corré `pytest -m "not slow"` y revisá la coverage (`fail_under = 80`).
- Stack: Python 3.11+, Pydantic v2 (`frozen=True`, `extra="forbid"`), Click, httpx HTTP/2, pyodbc, pandas, textual, pytest.
- Arquitectura: hexagonal estricta — CLI → Orchestrators → Services → Domain ← Adapters. La dirección de dependencias no se rompe.

## Recetas disponibles

| Receta | Cuándo te sirve |
|--------|-----------------|
| [`add-a-new-config-field.md`](add-a-new-config-field.md) | Necesitás exponer una nueva perilla en el YAML del pipeline |
| [`add-a-new-cmis-property.md`](add-a-new-cmis-property.md) | El banco pide un metadato CMIS nuevo que hoy no se resuelve |
| [`add-a-new-source-system.md`](add-a-new-source-system.md) | Querés leer triggers o metadata desde algo que no es CSV ni AS400 (ej. PostgreSQL) |
| [`run-the-test-suite.md`](run-the-test-suite.md) | Catálogo de comandos `pytest` por marcador, cobertura y fixtures clave |
| [`profile-a-bottleneck.md`](profile-a-bottleneck.md) | El pipeline va lento y no sabés en qué stage se va el tiempo |

## Ver también

- [`../../INDEX.md`](../../INDEX.md) — mapa canónico de toda la documentación
- [`../operator/`](../operator/) — recetas orientadas a operación
- [`../../reference/config-schema.md`](../../reference/config-schema.md) — el catálogo declarativo de campos de configuración
- [`../../reference/cli.md`](../../reference/cli.md) — superficie completa de CLI
- [`../../../CONTRIBUTING.md`](../../../CONTRIBUTING.md) — workflow, convenciones, conventional commits
- `.specify/memory/constitution.md` — los 9 principios de arquitectura del proyecto
