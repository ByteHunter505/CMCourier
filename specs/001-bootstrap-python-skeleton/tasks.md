# Tasks — 001-bootstrap-python-skeleton

**Status**: Borrador (en revisión)
**Creado**: 2026-05-08
**Referencia al spec**: `specs/001-bootstrap-python-skeleton/spec.md`
**Referencia al plan**: `specs/001-bootstrap-python-skeleton/plan.md`

> Checklist atómico de implementación. Cada tarea es lo suficientemente pequeña como para completarse en una sesión. Las fases están secuenciadas para que cada fase termine en un estado intermedio significativo.

---

## Cómo leer este archivo

- Las tareas están numeradas jerárquicamente: `<fase>.<tarea>`.
- Marcar `[ ]` → `[x]` a medida que cada tarea se completa.
- El modo `Strict TDD` está **habilitado**. Para tareas que producen código, quien implementa sigue `Red → Green → Refactor`:
  1. Escribir primero el test que falla (o reusar el escenario del `spec`).
  2. Confirmar que el test falla por la razón esperada.
  3. Escribir el mínimo código para que pase.
  4. Confirmar que el test pasa.
  5. Refactorizar mientras está en verde.
- Para tareas que no son de código (configs, docs), TDD no aplica directamente — los escenarios de verificación en `spec.md §4` son la prueba.

---

## Fase 1 — Higiene del repo

Victorias rápidas. Todavía no hay código Python.

- [ ] **1.1** Crear `.gitignore` en la raíz del repo con las entradas de `spec.md REQ-018`.
- [ ] **1.2** Crear `.editorconfig` en la raíz del repo con: `root = true`, bloque `[*]` configurando `indent_style = space`, `indent_size = 4`, `end_of_line = lf`, `charset = utf-8`, `trim_trailing_whitespace = true`, `insert_final_newline = true`. Agregar el override `[*.md]` con `trim_trailing_whitespace = false` (preservación de `trailing-space-as-linebreak` en Markdown).

**Fase 1 lista cuando**: `.gitignore` y `.editorconfig` existen y están trackeados por git.

---

## Fase 2 — Layout de código fuente

Crear cada directorio de paquete con `__init__.py`. Sin lógica.

- [ ] **2.1** Crear `src/cmcourier/__init__.py` con:
  ```python
  """CMCourier — banking document migration tool (RVI → IBM Content Manager)."""
  __version__ = "0.0.0"
  ```
- [ ] **2.2** Crear `src/cmcourier/main.py` con un `docstring` de módulo de una línea y un `main()` `placeholder` que importa de `cli.app`. Solamente a nivel de módulo — sin lógica.
- [ ] **2.3** Crear `src/cmcourier/domain/__init__.py` con un `docstring` describiendo el propósito de la capa ("Pure Python; no external dependencies. Models, ports, exceptions.").
- [ ] **2.4** Crear `src/cmcourier/domain/models.py` con un `docstring` `placeholder` ("Domain models — TriggerRecord, RVABREPDocument, CMMapping, etc. Populated in 002-domain-models-and-ports.").
- [ ] **2.5** Crear `src/cmcourier/domain/ports.py` con un `docstring` `placeholder` ("Abstract interfaces — IDataSource, ITrackingStore, IAssembler, IUploader. Populated in 002-domain-models-and-ports.").
- [ ] **2.6** Crear `src/cmcourier/domain/exceptions.py` con un `docstring` `placeholder` ("Typed exception hierarchy. Populated in 002-domain-models-and-ports.").
- [ ] **2.7** Crear `src/cmcourier/adapters/__init__.py` y los cuatro archivos `init` de los sub-paquetes: `sources/__init__.py`, `tracking/__init__.py`, `assembly/__init__.py`, `upload/__init__.py`. Cada uno tiene un `docstring` nombrando su propósito.
- [ ] **2.8** Crear `src/cmcourier/services/__init__.py` con un `docstring` de capa.
- [ ] **2.9** Crear `src/cmcourier/orchestrators/__init__.py` con un `docstring` de capa.
- [ ] **2.10** Crear `src/cmcourier/cli/__init__.py` con un `docstring` de capa.
- [ ] **2.11** Crear `src/cmcourier/cli/app.py` con el `placeholder` del grupo Click:
  ```python
  """CMCourier CLI entry point — Click group root."""
  import click

  @click.group()
  @click.version_option()
  def main() -> None:
      """CMCourier — RVI → IBM Content Manager migration tool."""

  if __name__ == "__main__":
      main()
  ```
- [ ] **2.12** Crear `src/cmcourier/cli/commands/__init__.py` y `src/cmcourier/cli/ui/__init__.py` con `docstrings` de capa.
- [ ] **2.13** Crear `src/cmcourier/config/__init__.py` con un `docstring` de capa.

**Fase 2 lista cuando**: cada directorio mostrado en `plan.md §6` existe con su `__init__.py`. Correr `find src/cmcourier -name __init__.py | wc -l` y confirmar que el conteo coincide con el layout.

---

## Fase 3 — Configuración de build y tooling

Crear `pyproject.toml`. Después de esta fase, `pip install -e .[dev]` debe funcionar.

- [ ] **3.1** Crear `pyproject.toml` con el bloque `[build-system]` (`requires = ["setuptools>=68", "wheel"]`, `build-backend = "setuptools.build_meta"`).
- [ ] **3.2** Agregar el bloque `[project]`: `name = "cmcourier"`, `version = "0.0.0"`, `description`, `requires-python = ">=3.11"`, `readme = "README.md"`, `license = {text = "Proprietary"}`, `authors = [{name = "bitBreaker"}]`, `keywords`, `classifiers`. Usar la descripción: "CMCourier — banking document migration tool from IBM RVI on AS400 to IBM Content Manager via CMIS."
- [ ] **3.3** Agregar el array `[project].dependencies` según `plan.md §3.1` (deps de `runtime` con `>=`/`<` bounds).
- [ ] **3.4** Agregar el array `[project.optional-dependencies].dev` según `plan.md §3.2`.
- [ ] **3.5** Agregar el bloque `[project.scripts]`: `cmcourier = "cmcourier.cli.app:main"`.
- [ ] **3.6** Agregar el bloque `[tool.setuptools]`: `package-dir = {"" = "src"}` y `[tool.setuptools.packages.find]` con `where = ["src"]`.
- [ ] **3.7** Agregar los bloques `[tool.ruff]` y `[tool.ruff.lint]`, `[tool.ruff.lint.per-file-ignores]`, `[tool.ruff.format]` según `plan.md §4.1`.
- [ ] **3.8** Agregar el bloque `[tool.mypy]` más los dos bloques `[[tool.mypy.overrides]]` según `plan.md §4.2`.
- [ ] **3.9** Agregar el bloque `[tool.pytest.ini_options]` según `plan.md §4.3`.
- [ ] **3.10** Agregar los bloques `[tool.coverage.run]` y `[tool.coverage.report]` según `plan.md §4.4`.

**Fase 3 lista cuando**:
- `python -m venv .venv && source .venv/bin/activate && pip install -e .[dev]` tiene éxito en un entorno limpio.
- `python -c "import cmcourier; print(cmcourier.__version__)"` imprime `0.0.0`.

---

## Fase 4 — Esqueleto de tests + smoke test

`Strict TDD` aplica desde acá. El `smoke test` es el primer test que falla y que termina de dirigir la fase 3 a ser válida.

- [ ] **4.1** Crear `tests/__init__.py` (vacío).
- [ ] **4.2** Crear `tests/conftest.py` con solamente un `docstring` de módulo ("Shared pytest fixtures. Populated as adapters land."). Sin `fixtures` todavía.
- [ ] **4.3** **Red**: escribir `tests/test_smoke.py` según `plan.md §7`. Correr `pytest`. Confirmar que ambos tests fallan con `ModuleNotFoundError: cmcourier` SI se corren antes de que la fase 3 esté completa. (Si la fase 3 se completó correctamente, los tests van a pasar en la primera corrida — eso también es aceptable.)
- [ ] **4.4** **Green**: asegurar que `pytest` pasa. Si falla, arreglar la causa real (probablemente un typo en `pyproject.toml` o un `__init__.py` faltante).
- [ ] **4.5** Crear `tests/unit/__init__.py`, `tests/unit/domain/__init__.py`, `tests/unit/services/__init__.py`, `tests/unit/orchestrators/__init__.py` — `stubs` vacíos de `unit tests` listos para la fase 002+.
- [ ] **4.6** Crear `tests/integration/__init__.py`, `tests/integration/adapters/__init__.py`, `tests/integration/pipeline/__init__.py` — `stubs` vacíos de `integration tests`.
- [ ] **4.7** Correr `pytest -v` y confirmar: 2 tests colectados, 2 pasan, 0 fallan. Capturar el output para el reporte de verificación.

**Fase 4 lista cuando**: `pytest` sale con 0 y el `smoke test` en verde.

---

## Fase 5 — Pipeline de pre-commit

Aplicar las reglas constitucionales desde el primer `commit` en adelante.

- [ ] **5.1** Crear `scripts/hooks/no-co-authored-by.sh` según `plan.md §5.2`. Hacerlo ejecutable: `chmod +x scripts/hooks/no-co-authored-by.sh`.
- [ ] **5.2** Crear `.pre-commit-config.yaml` según `plan.md §5.1`.
- [ ] **5.3** Correr `pre-commit install` y `pre-commit install --hook-type commit-msg`. Confirmar que instala tanto el hook de `pre-commit` como el de `commit-msg`.
- [ ] **5.4** **Smoke test de los hooks de lint**: correr `pre-commit run --all-files`. Esperar que `ruff`/`mypy` pasen sobre el esqueleto vacío (o que produzcan autofixes que después commiteamos). Si aparecen errores, arreglarlos y volver a correr.
- [ ] **5.5** **Smoke test del hook `no-co-authored-by`**: en un branch descartable, intentar un `commit` con `Co-Authored-By: Test <test@example.com>` en el mensaje. Confirmar que el `commit` es **rechazado** con el mensaje de error esperado. Capturar el output.
- [ ] **5.6** **Smoke test del hook de conventional commit**: en el mismo branch descartable, intentar un `commit` con `subject` `update stuff`. Confirmar el rechazo.
- [ ] **5.7** Descartar el branch descartable (`git branch -D <branch>`).

**Fase 5 lista cuando**: los `pre-commit hooks` están instalados y validados contra los escenarios de rechazo de `spec.md §4.5` y §4.6.

---

## Fase 6 — Actualización de documentación + verificación

Atar los cabos sueltos, andamiar la arquitectura de documentación (según `plan.md §13`), actualizar docs, correr la suite completa de verificación.

- [ ] **6.1** Actualizar la sección "Getting started" del `README.md` según `plan.md §8`.
- [ ] **6.2** Actualizar el checklist de Status del `README.md`: tildar la línea sobre "Python skeleton bootstrap".
- [ ] **6.3** Actualizar `CHANGELOG.md` según `plan.md §9` — agregar el bloque `[0.3.0]` con la fecha del `commit`, y ajustar los bullets de "Planned for next release" en `[Unreleased]`.
- [ ] **6.4** Crear `docs/INDEX.md` siguiendo la plantilla de `plan.md §13.5` — listar cada artefacto existente (README, CHANGELOG, CONTRIBUTING, constitución, `domain spec`, POST-MVP, samples) con descripciones de una línea; dejar vacías las secciones `how-to` y `explanation` con punteros a sus READMEs.
- [ ] **6.5** Crear `docs/how-to/README.md` según `plan.md §13.4`: declaración de propósito (orientada a problemas "How to use"), convención de nombres (`how-to/<task-slug>.md`, `kebab-case`), lista vacía de `bullets` de guías disponibles, link de vuelta a `docs/INDEX.md`.
- [ ] **6.6** Crear `docs/explanation/README.md` según `plan.md §13.4`: declaración de propósito (orientada a entender "How it works"), convención de nombres (`explanation/<concept-slug>.md`), lista vacía de `bullets` de explicaciones disponibles, link a la `domain spec` del proyecto como la explicación canónica del dominio, link de vuelta a `docs/INDEX.md`.
- [ ] **6.7** Actualizar la sección "Documentation map" del `README.md`: agregar un link en la fila superior a `docs/INDEX.md` como punto de entrada canónico. Mantener las filas existentes por artefacto para acceso rápido.
- [ ] **6.8** Correr la suite completa de verificación de `spec.md §8`:
  ```bash
  pip install -e .[dev]
  pytest -v
  ruff check src/ tests/
  ruff format --check src/ tests/
  mypy src/cmcourier/
  pre-commit run --all-files
  ```
  Capturar cada output. Todo DEBE pasar antes del `commit`.
- [ ] **6.9** Buscar PII con `grep` en los archivos nuevos (según `spec.md §4.8`):
  ```bash
  rg -n '\b\d{6}\b' src/ tests/                      # 6-digit numbers (CIF pattern)
  rg -n -i '(juan|maria|carlos)\s?(perez|gomez|rodriguez)' src/ tests/   # common Argentine names
  ```
  Confirmar que no hay coincidencias con aspecto real.
- [ ] **6.10** Hacer `stage` de todos los archivos nuevos y modificados. Confirmar que `git status` coincide con la lista esperada de archivos:
  ```
  modified: README.md
  modified: CHANGELOG.md
  added: .editorconfig
  added: .gitignore
  added: .pre-commit-config.yaml
  added: pyproject.toml
  added: scripts/hooks/no-co-authored-by.sh
  added: src/cmcourier/**/*.py
  added: tests/**/*.py
  added: docs/INDEX.md
  added: docs/how-to/README.md
  added: docs/explanation/README.md
  ```
- [ ] **6.11** Crear el `commit` de implementación en el branch de feature:
  ```
  feat: bootstrap Python skeleton with hexagonal layout and tooling

  Phase 0 of the implementation order from the spec. Ships
  pyproject.toml (PEP 621) declaring all settled dependencies,
  src/cmcourier/ in src layout with the six hexagonal layers as
  empty packages, tests/ skeleton with a smoke test confirming
  importability and __version__, ruff + mypy + pytest + coverage
  configured to enforce the constitution from the first line of
  real code.

  Pre-commit hooks block: lint failures, format violations, mypy
  errors, non-Conventional-Commits messages, and the Co-Authored-By
  trailer (Constitution Principle IX).

  No business logic in this change. The next change (002-domain-
  models-and-ports) starts populating domain/.

  Closes specs/001-bootstrap-python-skeleton/.
  ```

**Fase 6 lista cuando**: el branch está commiteado, todos los comandos de verificación en verde, listo para PR o `merge` directo.

---

## Fase 7 — Opcional: PR + merge

Si se usa el workflow de PR de GitHub:

- [ ] **7.1** Pushear el branch.
- [ ] **7.2** Abrir un PR con título `feat: bootstrap Python skeleton` (≤70 chars).
- [ ] **7.3** El body del PR linkea a `specs/001-bootstrap-python-skeleton/spec.md`, lista la evidencia de tests (el `smoke test` pasa, `lint`/`format`/`mypy` limpios, rechazo del hook demostrado).
- [ ] **7.4** Revisión (si aplica). Direccionar comentarios agregando nuevos `commits`, nunca con `amend`.
- [ ] **7.5** `Merge`.

Si se trabaja solo sobre `main` (setup actual):

- [ ] **7.1-alt** Confirmar que la suite de verificación pasó.
- [ ] **7.2-alt** Tagear si corresponde (NO tageamos pre-MVP).

---

## Mapeo de verificación (spec → tasks)

Para trazabilidad:

| Spec REQ | Tasks que lo cumplen |
|----------|----------------------|
| REQ-001 | 3.1 |
| REQ-002 | 3.1–3.10, verificado en 3-done y 4.4 |
| REQ-003 | 2.1, verificado en 4.4 |
| REQ-004 | 2.11, 3.5 |
| REQ-005 | 3.3 |
| REQ-006 | 3.4 |
| REQ-007 | 3.2 |
| REQ-008 | 2.x (toda la fase 2) |
| REQ-009 | 3.6 |
| REQ-010 | 2.x |
| REQ-011 | 3.7 |
| REQ-012 | 3.8 |
| REQ-013 | 3.9 |
| REQ-014 | 3.10 |
| REQ-015 | 5.2 |
| REQ-016 | 5.2 |
| REQ-017 | 5.1, 5.2 |
| REQ-018 | 1.1 |
| REQ-019 | 1.2 |
| REQ-020 | aplicado por 6.5 grep + disciplina de la Constitución |
| REQ-021 | 4.3, 4.4 |
| REQ-022 | 4.7 |
| REQ-023 | 6.1 |
| REQ-024 | 6.3 |
| REQ-025 | 6.2 |
| REQ-026 | 6.4 |
| REQ-027 | 6.5 |
| REQ-028 | 6.6 |
| REQ-029 | 6.7 |

| Escenario de aceptación | Tasks que producen evidencia |
|-------------------------|------------------------------|
| 4.1 (fresh install) | 3.1–3.10, 6.4 |
| 4.2 (smoke test passes) | 4.4, 4.7, 6.4 |
| 4.3 (linter clean) | 6.4 |
| 4.4 (mypy clean) | 6.4 |
| 4.5 (Co-Authored-By blocked) | 5.5 |
| 4.6 (non-conventional blocked) | 5.6 |
| 4.7 (hexagonal layering visible) | 2.x |
| 4.8 (no PII) | 6.9 |
| 4.9 (documentation index discoverable) | 6.4, 6.5, 6.6, 6.7 |

---

## Esfuerzo estimado

- Fase 1: 5 minutos
- Fase 2: 20 minutos (mecánica, muchos archivos chicos)
- Fase 3: 30 minutos (la parte sustanciosa: `pyproject.toml` + primer install)
- Fase 4: 15 minutos (`smoke test` + estructura)
- Fase 5: 25 minutos (`pre-commit` + validación de hooks)
- Fase 6: 30 minutos (estructura de docs + updates de README/CHANGELOG + verificación + `commit`)
- **Total**: ~2 horas y 5 minutos de trabajo enfocado para un contribuyente haciendo `pair-programming` con un agente.

Esto es consistente con la estimación del `spec` de "Phase 0 — Bootstrap (1 day)" — estamos bastante por debajo, porque mucho de la preparación (constitución, `domain spec`, docs) ya está hecho.

---

## Notas para quien implementa

- No desviarse del layout en `plan.md §6` sin enmendar antes el `plan`.
- Si una tarea no coincide exactamente con su REQ correspondiente, gana el `spec` — arreglar la tarea o enmendar el `spec`.
- Si la instalación de `pyodbc` falla en tu `host`, instalar `unixODBC-dev` (Debian/Ubuntu: `sudo apt install unixodbc-dev`; macOS: `brew install unixodbc`) y reintentar.
- El límite de 50 líneas por función (Principio III de la Constitución) no aplica en este cambio porque no hay funciones de consecuencia. Aplica en el momento en que aterrice la primera función real.
- `Strict TDD` aplica para cualquier línea de `*.py` bajo `src/cmcourier/` que haga algo más allá de un `docstring`. Los `placeholders` en este cambio tienen solamente `docstrings`, así que el único test que existe es el `smoke test` — y cubre todo el código de producción de este cambio (el `smoke test` afirma que `__version__` está seteado, y ese es el único comportamiento).
