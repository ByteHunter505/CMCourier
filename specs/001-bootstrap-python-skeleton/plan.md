# Plan — 001-bootstrap-python-skeleton

**Status**: Borrador (en revisión)
**Creado**: 2026-05-08
**Referencia al spec**: `specs/001-bootstrap-python-skeleton/spec.md`
**Versión de la constitución al momento del borrador**: v1.0.0

> El **cómo** de este cambio. Describe decisiones de arquitectura, elecciones de librerías y el layout final. El desglose de implementación vive en `tasks.md`.

---

## 1. Resumen del Enfoque

Un único `pyproject.toml` (PEP 621) declara todo el `build`, dependencias y configuración del `tooling`. Sin `setup.py`. Sin `setup.cfg`. El repo obtiene un esqueleto de layout `src/` con archivos `__init__.py` vacíos en cada paquete, un `smoke test` que prueba la `importability`, y un `pipeline` de `pre-commit` que hace `enforcement` de las reglas constitucionales desde el primer `commit`.

El cambio es intencionalmente acotado: cada línea de código o configuración en este cambio debe estar justificada por un requisito en `spec.md`. No se agrega nada "porque lo vamos a necesitar después" — ese es el tipo de andamiaje especulativo que llevó al viejo `pipeline.py` a tener 1341 líneas.

---

## 2. Decisiones de Build y Packaging

### 2.1 Build backend: `setuptools`

**Decisión**: Usar `setuptools>=68` como `build backend`.

**Alternativas consideradas**:
- `hatchling`: moderno, liviano, menos features. Adopción creciente.
- `pdm-backend`: atado a PDM; no estamos usando PDM como gestor de dependencias.
- `poetry-core`: atado a Poetry; no estamos usando Poetry.

**Justificación**:
- `setuptools` es el default. Todo desarrollador Python del planeta lo entiende.
- No necesitamos ninguna feature que `hatchling` provea por encima de `setuptools` (sin plugins, sin versionado dinámico más allá de `version = "0.0.0"`).
- Cambiar de `backend` después es barato si aparece un `gap` de features.
- Principio IX de la Constitución: "concepts over code, verify over assume". Elegir el default aburrido es la opción verificada.

### 2.2 Layout src (PEP 420)

**Decisión**: Todo el código importable vive bajo `src/cmcourier/`. Sin directorio `cmcourier/` a nivel `top-level`.

**Justificación**:
- Fuerza que los `editable installs` realmente instalen el paquete (en lugar de tomar la raíz del repo como si estuviera en `PYTHONPATH`). Esto captura `__init__.py` faltantes y módulos mal declarados al momento de la instalación, no en `runtime`.
- Elimina una clase de problemas de "los tests pasan local pero fallan en CI" causados por diferencias en la resolución de imports.
- Práctica estándar para proyectos Python modernos.

### 2.3 Versión

**Decisión**: `__version__ = "0.0.0"` hardcodeado en `src/cmcourier/__init__.py`. Los bumps de SemVer suceden desde ahí a medida que aterricen features reales.

**Justificación**:
- Todavía no necesitamos versionado dinámico desde `git tags`. Cuando se entregue el primer MVP, lo revisamos (probablemente `setuptools-scm` o una política manual de `bump`).
- Esqueleto vacío ≠ software entregable. `0.0.0` es honesto; `0.1.0` implicaría que algo funciona.

### 2.4 Reserva del entry point

**Decisión**: Declarar `[project.scripts] cmcourier = "cmcourier.cli.app:main"` aunque `main` no exista más allá de un `placeholder` de grupo Click.

**Justificación**:
- Reserva el nombre del binario desde el día uno. El primer contribuyente que agregue un comando CLI real no tiene que refactorizar la instalación.
- Fuerza que la función `placeholder` `main()` exista con la firma correcta, lo cual es documentación en sí mismo.

---

## 3. Política de Pinning de Dependencias

### 3.1 Dependencias de runtime

`Pin` a **versiones mínimas compatibles** con `>=` (sin tope superior) por ahora:

```toml
[project]
dependencies = [
  "pydantic>=2.0,<3.0",        # major-version cap to avoid silent breakage
  "click>=8.1,<9.0",
  "pyodbc>=5.0,<6.0",
  "requests>=2.31,<3.0",
  "requests-toolbelt>=1.0,<2.0",
  "pandas>=2.0,<3.0",
  "img2pdf>=0.5,<1.0",
  "Pillow>=10.0,<12.0",
  "PyPDF2>=3.0,<4.0",
]
```

**Justificación**:
- Tope inferior = mínimo contra el que validamos. Vamos a validar contra estas versiones durante el MVP.
- Tope superior = la siguiente `major`. Las versiones `major` son donde suceden los cambios `breaking`; queremos elegir conscientemente cuándo actualizar.
- Sin `pins` exactos (`==`) en esta capa. Los `pins` exactos viven en un archivo `requirements.lock` (post-MVP, cuando tengamos un `pipeline` de CI que necesite reproducibilidad).

### 3.2 Dependencias de desarrollo

```toml
[project.optional-dependencies]
dev = [
  "pytest>=7.4,<9.0",
  "pytest-cov>=4.1,<6.0",
  "ruff>=0.4,<1.0",
  "mypy>=1.8,<2.0",
  "pre-commit>=3.5,<5.0",
  "types-requests>=2.31,<3.0",
  "pandas-stubs>=2.0,<3.0",
]
```

---

## 4. Configuración del Tooling

### 4.1 ruff

```toml
[tool.ruff]
line-length = 100
target-version = "py311"
src = ["src", "tests"]

[tool.ruff.lint]
select = [
  "E", "W",   # pycodestyle
  "F",        # pyflakes
  "I",        # isort
  "B",        # flake8-bugbear
  "C4",       # flake8-comprehensions
  "UP",       # pyupgrade
  "N",        # pep8-naming
  "SIM",      # flake8-simplify
  "RET",      # flake8-return
  "PTH",      # flake8-use-pathlib
  "TID",      # flake8-tidy-imports
]
ignore = []

[tool.ruff.lint.per-file-ignores]
"__init__.py" = ["F401"]   # __init__.py may re-export without using
"tests/*" = ["S101"]       # asserts allowed in tests

[tool.ruff.format]
# defaults are fine; ruff format mimics black
```

**Decisión sobre `F401` para `__init__.py`**: sí, eximido. Las re-exportaciones son intencionales en `__init__.py`.

### 4.2 mypy

`Strict` de dos niveles como se especifica en el `spec`:

```toml
[tool.mypy]
python_version = "3.11"
files = ["src/cmcourier", "tests"]
strict = false              # baseline; overridden per-module below
warn_unused_configs = true
warn_redundant_casts = true
warn_unused_ignores = true
warn_return_any = true

# Strict for the layers where Principle I demands it
[[tool.mypy.overrides]]
module = [
  "cmcourier.domain.*",
  "cmcourier.services.*",
  "cmcourier.orchestrators.*",
]
strict = true

# Third-party deps with weak or missing stubs
[[tool.mypy.overrides]]
module = ["img2pdf", "pyodbc", "PyPDF2", "requests_toolbelt.*"]
ignore_missing_imports = true
```

**Justificación**: modo `strict` en las capas internas (donde la constitución exige limpieza) y modo pragmático en la capa de adaptadores (donde las librerías `third-party` con `stubs` malos generarían ruido). Esto coincide con Constitución §Constraints / Type checking.

### 4.3 pytest

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = ["-ra", "--strict-markers", "--strict-config"]
markers = [
  "unit: fast tests that mock all ports",
  "integration: tests that exercise real adapters (SQLite, CSV, Alfresco, etc.)",
  "slow: tests that take more than 5 seconds individually",
]
```

### 4.4 coverage

```toml
[tool.coverage.run]
source = ["src/cmcourier"]
branch = true

[tool.coverage.report]
fail_under = 80          # binding from the moment the first real code lands
show_missing = true
skip_covered = false
exclude_lines = [
  "pragma: no cover",
  "if TYPE_CHECKING:",
  "raise NotImplementedError",
]
```

**Nota**: el umbral del 80% está configurado, pero el esqueleto en sí tiene cero código de producción. El `coverage` de un paquete vacío es trivialmente 100%, así que el umbral "pasa" desde el día uno sin ser significativo. El umbral se vuelve vinculante en el momento en que se entregue código real. Esto es por diseño.

---

## 5. Pipeline de Pre-commit

### 5.1 Hooks

`.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.4.10
    hooks:
      - id: ruff           # lint with autofix
        args: ["--fix"]
      - id: ruff-format    # formatting

  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.10.0
    hooks:
      - id: mypy
        additional_dependencies: ["pydantic>=2.0", "types-requests"]
        files: ^src/cmcourier/
        # Run only on staged Python files in scope

  - repo: https://github.com/compilerla/conventional-pre-commit
    rev: v3.4.0
    hooks:
      - id: conventional-pre-commit
        stages: [commit-msg]
        args: ["feat", "fix", "docs", "refactor", "test", "chore", "perf", "ci"]

  - repo: local
    hooks:
      - id: no-co-authored-by
        name: Block Co-Authored-By in commit messages
        entry: bash scripts/hooks/no-co-authored-by.sh
        language: system
        stages: [commit-msg]
```

### 5.2 El hook `no-co-authored-by`

Implementado como un pequeño script de shell bajo `scripts/hooks/no-co-authored-by.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
msg_file="$1"
if grep -qiE '^[[:space:]]*Co-Authored-By:' "$msg_file"; then
  echo "ERROR: commit message contains 'Co-Authored-By' — disallowed by Constitution Principle IX." >&2
  echo "If this is human pair-programming, list the co-author in the PR description instead." >&2
  exit 1
fi
```

**Justificación**: un `pre-commit hook` es el único lugar donde esta regla se aplica automáticamente. La prosa de la constitución por sí sola no bloquea `commits` malos.

### 5.3 Pin de versión del framework de hooks

**Decisión**: pinear todas las versiones de hooks exactamente (el campo `rev:` arriba). La versión de `pre-commit` propiamente dicha está pineada en las `dev deps` con `>=3.5,<5.0`.

**Justificación**: que las versiones de los hooks cambien debajo nuestro es una sorpresa de CI que no necesitamos. Hacer el `bump` es un cambio deliberado `chore: bump pre-commit hooks`.

---

## 6. Layout Final del Repo

Después de que este cambio se mergee:

```
CMCourier/
├── .editorconfig
├── .gitignore
├── .pre-commit-config.yaml
├── .specify/
│   └── memory/constitution.md
├── .atl/skill-registry.md
├── CHANGELOG.md
├── CONTRIBUTING.md
├── README.md                          (Getting started filled in)
├── pyproject.toml                     (NEW)
├── docs/
│   ├── domain/the project's domain spec
│   ├── roadmap/POST-MVP.md
│   └── samples/{csv,excel,responses}/
├── scripts/
│   └── hooks/
│       └── no-co-authored-by.sh        (NEW)
├── specs/
│   └── 001-bootstrap-python-skeleton/
│       ├── spec.md
│       ├── plan.md
│       └── tasks.md
├── src/
│   └── cmcourier/                      (NEW)
│       ├── __init__.py                 (with __version__ = "0.0.0")
│       ├── main.py                     (placeholder; calls cli.app.main())
│       ├── domain/
│       │   ├── __init__.py
│       │   ├── models.py               (docstring-only placeholder)
│       │   ├── ports.py                (docstring-only placeholder)
│       │   └── exceptions.py           (docstring-only placeholder)
│       ├── adapters/
│       │   ├── __init__.py
│       │   ├── sources/
│       │   │   └── __init__.py
│       │   ├── tracking/
│       │   │   └── __init__.py
│       │   ├── assembly/
│       │   │   └── __init__.py
│       │   └── upload/
│       │       └── __init__.py
│       ├── services/
│       │   └── __init__.py
│       ├── orchestrators/
│       │   └── __init__.py
│       ├── cli/
│       │   ├── __init__.py
│       │   ├── app.py                  (Click group placeholder + main())
│       │   ├── commands/
│       │   │   └── __init__.py
│       │   └── ui/
│       │       └── __init__.py
│       └── config/
│           └── __init__.py
└── tests/                              (NEW)
    ├── __init__.py
    ├── conftest.py                     (empty placeholder)
    ├── test_smoke.py                   (the only test today)
    ├── unit/
    │   ├── __init__.py
    │   ├── domain/__init__.py
    │   ├── services/__init__.py
    │   └── orchestrators/__init__.py
    └── integration/
        ├── __init__.py
        ├── adapters/__init__.py
        └── pipeline/__init__.py
```

**Notas sobre el layout**:
- Cada `__init__.py` vacío es **intencional** — sin `namespace packages`, cada subdirectorio es un paquete explícito.
- `domain/{models,ports,exceptions}.py` son `placeholders` de solo `docstring` para que el `layering` sea visualmente obvio desde el día uno.
- `cli/app.py` existe como `placeholder` para que el `entry point` declarado en `pyproject.toml` realmente resuelva.
- `tests/` espeja parcialmente `src/cmcourier/` — solo las capas que van a tener `unit tests` (`domain`, `services`, `orchestrators`) necesitan `stubs`. Los `integration tests` se organizan por lo que testean (`adapters`, `pipeline`).

---

## 7. Detalle del Smoke Test

`tests/test_smoke.py`:

```python
"""Smoke tests: minimal proof that the package is installed and importable."""
import re

import cmcourier


def test_package_imports() -> None:
    """The package must be importable after `pip install -e .[dev]`."""
    assert cmcourier is not None


def test_version_is_set() -> None:
    """The package must expose a SemVer-compatible __version__ string."""
    version = getattr(cmcourier, "__version__", None)
    assert isinstance(version, str), "cmcourier.__version__ must be a string"
    assert version, "cmcourier.__version__ must be non-empty"
    assert re.match(r"^\d+\.\d+\.\d+(?:[-+].*)?$", version), (
        f"cmcourier.__version__ must be SemVer-compatible, got {version!r}"
    )
```

**Decisión sobre la ubicación**: `tests/test_smoke.py` (top-level), NO `tests/unit/test_smoke.py`. Razón: el `smoke test` es meta — testea que el `build` funciona, no una unidad de dominio. No debería descubrirse como parte de `unit tests` una vez que `tests/unit/` se llene.

---

## 8. Sección "Getting started" del README

Reemplaza el `placeholder` actual:

```markdown
## Getting started

### Prerequisites

- Python 3.11 or newer
- A C compiler and `unixODBC-dev` (Linux) / IBM iSeries Access ODBC Driver (Windows) — required by `pyodbc`
- Git

### Install (editable, with development tooling)

```bash
git clone <repo> CMCourier
cd CMCourier
python -m venv .venv
source .venv/bin/activate          # Linux / macOS
# .venv\Scripts\activate            # Windows
pip install -e .[dev]
pre-commit install
```

### Run the smoke test

```bash
pytest                             # all tests
pytest -m unit                     # only unit tests
pytest -m integration              # only integration tests
```

### Lint, format, type-check

```bash
ruff check src/ tests/
ruff format src/ tests/
mypy src/cmcourier/
```

### Pre-commit hook bypass

You don't bypass pre-commit hooks. If a hook fails, fix the cause and create a new commit. Never `--no-verify` (Constitution / Git Safety Protocol).
```

---

## 9. Entrada del CHANGELOG

Bajo `[Unreleased]` en `CHANGELOG.md`, reemplazar los bullets de "Planned for next release" con:

```markdown
## [Unreleased]

### Planned for next release
- First domain change: dataclasses + ports + exceptions for the hexagonal core.

## [0.3.0] — 2026-05-XX (this change's date once committed)

### Added
- `pyproject.toml` (PEP 621) with all runtime and dev dependencies pinned per Constitution §Constraints.
- `src/cmcourier/` skeleton in src layout (PEP 420) with hexagonal layering visible: `domain/`, `adapters/`, `services/`, `orchestrators/`, `cli/`, `config/`.
- `tests/` with unit / integration mirroring + a smoke test (`test_smoke.py`) confirming the package imports and exposes a SemVer `__version__`.
- `.pre-commit-config.yaml` with ruff, mypy, conventional-commits, and a custom `no-co-authored-by` hook.
- `.gitignore`, `.editorconfig`.
- README "Getting started" section.
- `scripts/hooks/no-co-authored-by.sh` to enforce Constitution §Workflow rule via pre-commit.
- `specs/001-bootstrap-python-skeleton/{spec.md, plan.md, tasks.md}` documenting this change end to end.
```

---

## 10. Riesgos y Mitigaciones

| Riesgo | Mitigación |
|--------|------------|
| La instalación de `pyodbc` falla en CI / `host` del contribuyente sin `unixODBC-dev` | El README Getting started lista el prerequisito explícitamente. El futuro `pipeline` de CI (cambio separado) lo instala vía apt/brew. |
| La primera corrida de `pre-commit` es lenta (descarga los entornos de los hooks) | Documentado en el README. Costo de una sola vez. |
| `mypy --strict` bloquea el primer cambio de código real por gaps en los `stubs` de `pyodbc`/`img2pdf` | `tool.mypy.overrides` para esos módulos ya tiene `ignore_missing_imports = true`. |
| El umbral de `coverage` del 80% sobre un esqueleto vacío parece trampa | Lo es, por diseño. Documentado como tal. Se vuelve vinculante cuando aterriza el primer código real. |
| El `pre-commit hook` en `commit-msg` falla en `git commit -m "..."` (sin editor) | Tanto `conventional-pre-commit` como el hook `no-co-authored-by` corren en `commit-msg`, que también se dispara para `commits` con `-m`. Funciona. |
| El hook de `Conventional Commits` es demasiado estricto para `commits` `wip` durante desarrollo local | Se espera que los contribuyentes hagan `squash` antes de abrir el PR. Documentado en CONTRIBUTING.md. Si el dolor se vuelve real, agregamos un `skip` opt-in (cambio separado). |

---

## 11. Pista sobre el Orden de Implementación

El archivo `tasks.md` agrupa tareas por fase. Las fases están secuenciadas para que cada fase produzca un estado parcialmente funcional — al final de cualquier fase, el contribuyente puede parar, pushear, y tener un `commit` intermedio significativo.

Fases:
1. Higiene del repo (`gitignore`, `editorconfig`)
2. Layout del código fuente (`__init__.py` vacío en todos lados)
3. Configuración de `build` y `tooling` (`pyproject.toml`)
4. Esqueleto de tests + `smoke test`
5. Pipeline de `pre-commit`
6. Verificación + actualización de documentación

Este orden coincide con el grafo de dependencias: higiene antes de layout, layout antes de `pyproject` (que referencia el layout), `pyproject` antes de tests (para que `pip install -e .[dev]` funcione), tests antes de `pre-commit` (para que `pre-commit run --all-files` tenga cosas contra qué correr), `pre-commit` antes de docs (para que la documentación refleje el estado funcional).

---

## 12. Preguntas Abiertas (ahora resueltas)

El `spec` listó 4 preguntas abiertas. Resueltas acá:

| Pregunta | Resolución |
|----------|------------|
| Build backend? | `setuptools` (§2.1 arriba) |
| Pinning de versión de pre-commit? | Pins exactos por hook; framework `>=3.5,<5.0` (§5.3) |
| Ubicación del smoke test? | `tests/test_smoke.py` (top level), NO `tests/unit/` (§7) |
| `__init__.py` exento de `F401`? | Sí, en `[tool.ruff.lint.per-file-ignores]` (§4.1) |

---

## 13. Arquitectura de Documentación

CMCourier usa un layout de documentación **inspirado en Diátaxis** (https://diataxis.fr): la documentación se divide por *propósito* en lugar de por tema. Esto evita el típico desastre de un README gigante que intenta enseñar, explicar y referenciar todo a la vez.

### 13.1 Los cuatro cuadrantes de Diátaxis

| Cuadrante | Propósito | Mentalidad del lector |
|-----------|-----------|----------------------|
| **Tutoriales** | Orientado al aprendizaje | "Soy nuevo y quiero aprender haciendo" |
| **Guías how-to** | Orientado a problemas | "Necesito resolver esta tarea específica" |
| **Reference** | Orientado a información | "Necesito buscar un dato específico" |
| **Explicación** | Orientado a entender | "Quiero entender cómo/por qué funciona esto" |

### 13.2 Lo que entregamos en 001 (subconjunto pragmático)

Para este cambio materializamos **solamente los dos cuadrantes que el usuario pidió explícitamente**: `how-to` y `explanation`. Los tutoriales y la `reference` se difieren hasta que aparezca contenido natural — un tutorial se escribe mejor cuando se entrega el primer `pipeline` y hay algo concreto que recorrer; una `reference` se escribe mejor cuando se estabiliza la superficie de comandos de la CLI.

```
docs/
├── INDEX.md                     # The map of all documentation (NEW)
├── domain/                       # already exists — explanation-class but special
│   └── the project's domain spec     # domain ground truth (precedence #4)
├── roadmap/                      # already exists
│   └── POST-MVP.md
├── samples/                      # already exists — reference fixtures
│   └── {csv,excel,responses}/
├── how-to/                       # NEW — "How to use"
│   └── README.md                 # purpose + naming convention + index of guides
└── explanation/                  # NEW — "How it works"
    └── README.md                 # purpose + naming convention + index of explanations
```

La `domain spec` del proyecto se queda donde está a pesar de ser de clase explicación. Es la **fuente de verdad del dominio** con precedencia #4 en la constitución; moverla invalidaría referencias cruzadas en artefactos ya entregados (constitución, README, archivos de `plan`). Se linkea desde `docs/explanation/README.md` como la explicación canónica del dominio.

### 13.3 Convenciones de nombres

- **How-to**: `docs/how-to/<task-slug>.md` (por ejemplo, `run-rvabrep-pipeline.md`, `configure-cmis-credentials.md`, `recover-from-failed-batch.md`).
- **Explanation**: `docs/explanation/<concept-slug>.md` (por ejemplo, `stage-architecture.md`, `metadata-resolution-cascade.md`, `cmis-session-warmup.md`).
- Los `slugs` son `kebab-case`, descriptivos, estables. Renombrar un doc existente es un cambio `breaking` para los links externos — bumpear el CHANGELOG.

### 13.4 Qué va en cada README de subdirectorio

Cada `how-to/README.md` y `explanation/README.md`:

1. Declara el propósito de ese tipo de doc en 2-3 oraciones (la definición del cuadrante de Diátaxis adaptada a CMCourier).
2. Lista la convención de nombres de §13.3.
3. Lista el contenido actualmente disponible como una lista de `bullets` markdown (vacía al inicio del MVP; se llena a medida que se agregan docs — cada cambio que entregue un doc actualiza el README apropiado).
4. Linkea de vuelta a `docs/INDEX.md` para navegación.

### 13.5 Qué va en `docs/INDEX.md`

Un mapa de una sola página de **cada** artefacto de documentación en el repo, agrupado por categoría, con descripciones de una línea y links. Forma aproximada:

```markdown
# CMCourier — Documentation Index

The single map of every document in the project. Pick the quadrant that matches your intent.

## For everyone
- README.md — project overview, current status
- CHANGELOG.md — versioned history (Keep a Changelog)
- CONTRIBUTING.md — workflow, commit standards, PR rules

## Engineering law
- .specify/memory/constitution.md — 9 immutable principles

## Domain ground truth
- docs/domain/the project's domain spec — full domain specification (RVI, CMIS, stages, metadata)

## Project planning
- docs/roadmap/POST-MVP.md — features deferred beyond MVP
- specs/<NNN>/ — per-change SDD artifacts (spec, plan, tasks)

## Reference data
- docs/samples/csv/ — sample CSVs (Modelo Documental, trigger lists, metadata sources)
- docs/samples/excel/RVILIB_RVABREP.xlsx — RVABREP table dump
- docs/samples/responses/EjemploRespuestaCMIS.txt — real CMIS response example

## How to use (recipes)
- (none yet — see docs/how-to/README.md)

## How it works (explanations)
- (none yet — see docs/explanation/README.md)
```

El INDEX se actualiza con cada cambio que agregue o mueva un artefacto de documentación (el `tasks.md` del cambio incluye una tarea para actualizarlo; CONTRIBUTING.md va a documentar esta responsabilidad).

### 13.6 Evolución futura

- Cuando se escriba el primer tutorial (probablemente cuando `rvabrep-pipeline` se entregue de punta a punta y tengamos un `walkthrough` real para dar a un operador nuevo), crear `docs/tutorials/` con su propio README.md siguiendo el mismo patrón.
- Cuando se estabilice la superficie de comandos de la CLI (post-MVP), crear `docs/reference/` con una `reference` de comandos CLI y una `reference` de schema de configuración.
- Cada agregado se documenta en CHANGELOG.md y en el INDEX.md.

---

## 14. Referencias Cruzadas

- Spec: `specs/001-bootstrap-python-skeleton/spec.md`
- Tasks: `specs/001-bootstrap-python-skeleton/tasks.md`
- Constitución: `.specify/memory/constitution.md`
- la `spec` (Project Layout), §15 (Implementation Order)
- CONTRIBUTING.md (convenciones del workflow que este cambio aplica vía hooks)
- Framework Diátaxis: https://diataxis.fr
