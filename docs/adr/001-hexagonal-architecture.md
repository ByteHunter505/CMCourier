> [← Volver al índice](../INDEX.md) · [ADRs](README.md)

# ADR-001: Arquitectura hexagonal (Ports & Adapters)

- **Estado**: Aceptado y vigente
- **Fecha**: 2026-05-08
- **Spec(s) relacionadas**: ratificada por la Constitución, [Principio I](../../.specify/memory/constitution.md). Implementada incrementalmente desde la spec 001 (`specs/001-bootstrap-python-skeleton/`) y 002 (`specs/002-domain-models-and-ports/`).
- **Versión donde se shipping**: 0.1.0 (bootstrap del skeleton)

## Contexto

CMCourier es el rewrite de `RVIMigration`, una herramienta que migraba documentos del sistema legacy IBM RVI sobre AS400 a IBM Content Manager. El original funcionaba — hasta que dejó de funcionar. La causa raíz no fue un bug puntual: fue que el archivo central, `pipeline.py`, había crecido a **1341 líneas** mezclando llamadas HTTP CMIS, escrituras SQLite, queries pyodbc a AS400, threading, configuración hardcodeada y reglas de negocio en un mismo cuerpo. Era un **God Object** en el sentido literal: un objeto al que todo le tocaba.

Las consecuencias eran ortodoxas: imposible testear sin parar todo el ecosistema (AS400 real, CMIS real, SQLite real). Cualquier cambio en una zona regresionaba otra. El método `run()` tenía paths muertos. Bugs como "una llamada `scan_and_resolve` insertada en medio de otro método" o "una columna inexistente `preprocessed_at` en un UPDATE" sobrevivían meses porque no había manera barata de aislar componentes.

El rewrite tenía que romper esta dinámica desde el día cero. La arquitectura no podía ser una decisión posterior — tenía que ser **la primera línea de código**.

## Decisión

Adoptamos **Ports & Adapters** (hexagonal) como arquitectura no-negociable, con cuatro capas y dirección de dependencia estricta:

```
CLI → Orchestrators → Services → Domain ← Adapters
```

Cada capa tiene un contrato claro:

- **`domain/`** — modelos, puertos (interfaces abstractas) y excepciones. **Cero dependencias externas.** Solo stdlib de Python. No `httpx`, no `pyodbc`, no `pandas`, no `pydantic`. Si necesitás importar algo de afuera, no va acá.
- **`adapters/`** — implementaciones concretas de los puertos. Es el **único** lugar donde vive el I/O (red, disco, base de datos).
- **`services/`** — lógica de negocio. Depende de puertos, nunca de adapters concretos.
- **`orchestrators/`** — coordinan services. Sin lógica de negocio, sin I/O directo.
- **`cli/`** — inyecta dependencias. Sin lógica de negocio.

Esta separación está codificada en la Constitución (Principio I) y se enforce en revisión: importar `httpx` en un service o instanciar un adapter dentro de business logic es un rechazo automático.

## Consecuencias

### Positivas

- **Testabilidad por capa.** Los services se testean unitariamente mockeando los puertos (`@pytest.mark.unit`, < 1 s cada uno). Los adapters se testean con integración real (SQLite file, CSV files, Alfresco en Docker). El test pyramid del Principio VI es estructural, no aspiracional.
- **Dominio puro como contrato estable.** Cambiar de `requests` a `httpx` (spec 060) o de `requests-toolbelt.MultipartEncoder` a `httpx` nativo fue un cambio puntual en `adapters/upload/`. Cero líneas tocadas en `domain/` o `services/`. Eso es justamente la promesa del patrón.
- **Adapters intercambiables.** `IDataSource` tiene implementaciones `TabularDataSource` (CSV, pandas) y `As400DataSource` (pyodbc). El mismo servicio de indexing (`IndexingService`) corre contra cualquiera de las dos sin un solo `if` en su código.
- **Refactor por adapter sin tocar lógica.** El `SQLiteTrackingStore` agregó un writer thread + WAL en spec 007, después un `document_cache` en spec 037, después se compuso con `As400NiarvilogStore` vía `IdempotencyCoordinator` en spec 034. Cada cambio quedó contenido en su adapter.

### Negativas / Tradeoffs

- **Más ceremonia upfront.** Cada feature nueva requiere pensar la división puerto/adapter/service antes de escribir código. Para cambios chicos puede sentirse pesado. La Constitución acepta el costo: el alternativo histórico fue `pipeline.py:1341`.
- **Indirection cuesta navegación.** Para entender qué hace una llamada a `IDataSource.query_stream`, hay que ir al puerto y después saltar al adapter que corresponda. IDEs modernos lo manejan, pero es un salto extra vs leer un método monolítico.
- **Wiring no es gratis.** El paso de inyección de dependencias está concentrado en `config/wiring.py`. Es un archivo conocido y largo (no God Object — su única responsabilidad es ensamblar). Cualquier feature nueva pasa por ahí.

### Neutras

- **No hay framework de DI.** Inyectamos por constructor a mano. Esto mantiene el código rastreable con `grep` y sin magia, al costo de unas pocas decenas de líneas de boilerplate.

## Alternativas consideradas

- **MVC clásico.** Inadecuado: no es un problema de presentación/datos/control sino de coordinación entre adaptadores de I/O heterogéneos. MVC habría empujado todo a "controllers gordos", reproduciendo el problema original.
- **Layered architecture tradicional (presentation/business/data).** Funciona para CRUD pero asume una sola "data layer". Acá tenemos cuatro: AS400 (pyodbc), CMIS (HTTP), SQLite local y filesystem. Forzar una única capa de datos significaba volver a mezclar responsabilidades.
- **Clean Architecture (entities/use-cases/interfaces/frameworks).** Más cercano a lo que adoptamos, pero la variante Ports & Adapters es más liviana y más estándar en el ecosistema Python. La diferencia es semántica más que mecánica.
- **Mantener `pipeline.py` y refactorear incrementalmente.** Descartado: la deuda estaba en la estructura, no en el código. Refactorear desde dentro no resolvía la dirección de dependencia.

## Ver también

- [Explanation: arquitectura hexagonal en CMCourier](../explanation/architecture-overview.md) — el "cómo funciona" en prosa.
- [Constitution — Principio I](../../.specify/memory/constitution.md)
- [Spec 001 — bootstrap del skeleton Python](../../specs/001-bootstrap-python-skeleton/)
- [Spec 002 — modelos de dominio y puertos](../../specs/002-domain-models-and-ports/)
- [Spec 019 — port hygiene](../../specs/019-port-hygiene/) — el refinamiento posterior de los contratos.
