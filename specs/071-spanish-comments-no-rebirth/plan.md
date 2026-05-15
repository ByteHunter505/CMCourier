# 071 — Plan

## Fase 1 — Quitar el code-name antiguo

* Listar todos los archivos con menciones (case-insensitive grep)
  en `src/`, `tests/`, `specs/`, `CHANGELOG.md`, `README.md`,
  `docs/`.
* Para cada archivo, reemplazar las menciones:
  * `<code-name antiguo> §X.Y` → eliminar la referencia (o
    reemplazar por contexto útil cuando la oración la necesita).
  * Enlace al `.md` del code-name → quitar enlace; si el contexto
    pide una referencia genérica, "el spec arquitectónico".
* Verificar: grep case-insensitive retorna cero.
* Commit: `refactor: remove legacy code-name references (071 Phase 1)`.

## Fase 2 — Traducir `orchestrators/` + `adapters/` (yo, en serie)

Archivos (en este orden):

* `src/cmcourier/orchestrators/__init__.py`
* `src/cmcourier/orchestrators/chunked.py`
* `src/cmcourier/orchestrators/staged.py` (el más grande)
* `src/cmcourier/orchestrators/multi_batch.py`
* `src/cmcourier/orchestrators/streaming.py`
* `src/cmcourier/adapters/assembly/__init__.py`
* `src/cmcourier/adapters/assembly/pdf_assembler.py`
* `src/cmcourier/adapters/assembly/pool.py`
* `src/cmcourier/adapters/upload/__init__.py`
* `src/cmcourier/adapters/upload/cmis_uploader.py`
* `src/cmcourier/adapters/sources/__init__.py`
* `src/cmcourier/adapters/sources/tabular.py`
* `src/cmcourier/adapters/sources/as400.py`
* `src/cmcourier/adapters/tracking/__init__.py`
* `src/cmcourier/adapters/tracking/sqlite.py`
* `src/cmcourier/adapters/tracking/as400_niarvilog.py`
* `src/cmcourier/adapters/tracking/document_cache.py`

Cada archivo: traducir docstrings de módulo, clase, función,
y comentarios `#`. Aplicar convenciones de la spec (backticks
para términos técnicos, nombres en inglés).

Commit: `refactor: translate orchestrators + adapters to Spanish (071 Phase 2)`.

## Fase 3 — Sub-agentes paralelo: `services/` + `domain/` + `config/` + `cli/` + `tui/` + `observability/`

Spawn 6 sub-agentes simultáneos. Cada uno toma un módulo
completo y traduce. Instrucciones idénticas a cada uno (estilo,
convenciones, lo que NO se toca).

Verificación post-spawn: `ruff check` + `mypy src` + spot-check
visual de 1-2 archivos por módulo.

Commit (por módulo o consolidado):
`refactor: translate <module> to Spanish (071 Phase 3)`.

## Fase 4 — Sub-agentes paralelo: `tests/`

Spawn 2 sub-agentes:

* Uno para `tests/unit/`.
* Otro para `tests/integration/`.

Tests tienen muchos comentarios in-line + docstrings cortos
en cada test. Misma convención.

Commit: `refactor: translate tests to Spanish (071 Phase 4)`.

## Fase 5 — Sub-agente: `specs/` + `CHANGELOG.md` + `README.md`

Un solo sub-agente con tres tareas:

* Traducir todos los specs bajo `specs/`. Mantener estructura
  Markdown (encabezados, listas, code blocks).
* Traducir `CHANGELOG.md` entrada por entrada (no consolidar,
  no reordenar).
* Traducir `README.md`.

Commit: `docs: translate specs + CHANGELOG + README to Spanish (071 Phase 5)`.

## Fase 6 — Verificación + release

* Grep case-insensitive del code-name antiguo → cero hits.
* `pytest tests/unit tests/integration -q` → verde.
* `ruff check src tests` → limpio.
* `ruff format src tests --check` → limpio.
* `mypy src` → limpio.
* Agregar entrada `[0.73.0]` al CHANGELOG (ya en español si
  Fase 5 ya pasó por ahí — sino lo escribo yo en español).
* `pyproject.toml` 0.72.0 → 0.73.0.
* `pip install -e . --no-deps` + `cmcourier --version` confirma.
* README feature row tick.
* Commit final + FF a main.
