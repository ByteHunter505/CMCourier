# Spec — 001-bootstrap-python-skeleton

**Status**: Borrador (en revisión)
**Creado**: 2026-05-08
**Autor**: bitBreaker
**Versión de la constitución al momento del borrador**: v1.0.0

> El **qué** de este cambio. Describe requisitos, escenarios de aceptación y elementos fuera de alcance. El **cómo** vive en `plan.md`. El checklist de implementación vive en `tasks.md`.

---

## 1. Intención

Levantar el esqueleto del proyecto Python para que todos los cambios posteriores tengan un sandbox funcional donde aterrizar código. Sin este andamiaje, no se puede escribir ningún `pipeline`, adaptador, servicio o test: `pytest` no existe, `mypy` no existe, `ruff` no existe, y el paquete `cmcourier` no es importable.

Este cambio **no** implementa ninguna lógica de negocio. Es el andamiaje — `pyproject.toml`, layout, configs, hooks, `smoke test`. Una vez que se mergea, el siguiente cambio puede empezar a escribir código real de inmediato, con `enforcement` completo del `tooling` desde la primera línea.

Este cambio corresponde a la **Fase 0** en `docs/domain/the project's domain spec §15` ("Implementation Order"), ahora ejecutada bajo la disciplina SDD establecida en la constitución del proyecto.

---

## 2. Por qué ahora

- La constitución y la `domain spec` fueron ratificadas. Las reglas básicas de ingeniería están definidas.
- Sin `pyproject.toml`, el Principio VI de la Constitución (Real Test Pyramid) no se puede aplicar — nada corre.
- Sin `mypy --strict`, el Principio I (Arquitectura Hexagonal, cero dependencias en `domain/`) no se puede aplicar a nivel de tipos.
- Sin `pre-commit hooks`, el Principio III (límite de 50 líneas por función) y la regla de no `Co-Authored-By` se aplican manualmente, lo que significa de forma inconsistente.
- Cada día que esto se demora es un día en el que alguien podría escribir la primera línea de `pipeline.py` 2.0 y deshacer el trabajo de arquitectura ya pagado.

---

## 3. Requisitos (RFC 2119)

### 3.1 Build y packaging

- **REQ-001**: El proyecto DEBE declarar su configuración de `build` en un único `pyproject.toml` en la raíz del repo, conforme a PEP 621.
- **REQ-002**: El proyecto DEBE ser instalable en modo editable vía `pip install -e .[dev]` desde un `checkout` limpio sin pasos manuales más allá del comando de instalación.
- **REQ-003**: El nombre del paquete DEBE ser `cmcourier`. El paquete DEBE ser importable como `import cmcourier` inmediatamente después de la instalación.
- **REQ-004**: El proyecto DEBE declarar un `entry point` vacío `cmcourier = "cmcourier.cli.app:main"` para que el nombre del binario quede reservado para la CLI aunque la CLI todavía no exista de forma significativa.

### 3.2 Dependencias

- **REQ-005**: Todas las dependencias de `runtime` declaradas en la sección Constraints de la Constitución DEBEN estar listadas bajo `[project].dependencies`: `pydantic>=2.0`, `click>=8.1`, `pyodbc>=5.0`, `requests>=2.31`, `requests-toolbelt>=1.0`, `pandas>=2.0`, `img2pdf>=0.5`, `Pillow>=10.0`, `PyPDF2>=3.0`.
- **REQ-006**: Todas las dependencias de desarrollo DEBEN estar listadas bajo `[project.optional-dependencies].dev`: `pytest>=7.4`, `pytest-cov>=4.1`, `ruff>=0.4`, `mypy>=1.8`, `pre-commit>=3.5`, `type stubs` (`types-requests`, `pandas-stubs`).
- **REQ-007**: La versión de Python DEBE ser `>=3.11` según la sección Constraints de la Constitución.

### 3.3 Layout de código fuente

- **REQ-008**: El repositorio DEBE seguir el layout descrito en `docs/domain/the project's domain spec §14.2` para `src/cmcourier/` y `tests/`, con una desviación: solamente los directorios requeridos para el `smoke test` del esqueleto deben crearse en este cambio. Los submódulos que se llenarán más adelante (por ejemplo `models.py`, `ports.py`) SE crean con `placeholders` de solo `docstring`, de manera que el `layering` hexagonal sea visible de inmediato.
- **REQ-009**: El layout del paquete DEBE usar un directorio `src/` (`src layout` de PEP 420) — `src/cmcourier/__init__.py` es la raíz del paquete, no un directorio `cmcourier/` a nivel `top-level`.
- **REQ-010**: Cada directorio bajo `src/cmcourier/` DEBE contener un `__init__.py` (sin `namespace packages` implícitos).

### 3.4 Configs de tooling

- **REQ-011**: `ruff` DEBE estar configurado bajo `[tool.ruff]` con reglas seleccionadas para coincidir con el estilo del proyecto: `E`, `W`, `F`, `I`, `B`, `C4`, `UP`, `N`, `SIM`, `RET`, `PTH`. Largo de línea 100.
- **REQ-012**: `mypy` DEBE estar configurado bajo `[tool.mypy]` con `strict = true` aplicado a `src/cmcourier/domain/`, `src/cmcourier/services/`, `src/cmcourier/orchestrators/`. Las otras capas (`adapters/`, `cli/`, `config/`) PUEDEN usar una configuración más permisiva para acomodar dependencias `third-party` sin tipos, pero DEBEN seguir siendo `type-checked`.
- **REQ-013**: `pytest` DEBE estar configurado bajo `[tool.pytest.ini_options]` con `testpaths = ["tests"]`, definiciones de `markers` para `unit`, `integration`, `slow`, y `addopts = ["-ra", "--strict-markers"]`.
- **REQ-014**: `coverage` DEBE estar configurado bajo `[tool.coverage.run]` y `[tool.coverage.report]` con `source = ["src/cmcourier"]`, `branch = true`, y `fail_under = 80`. El umbral del 80% se vuelve vinculante en el momento en que aterriza el primer código real; el esqueleto vacío está exento porque no tiene código testeable.

### 3.5 Pre-commit hooks

- **REQ-015**: Un archivo `.pre-commit-config.yaml` DEBE estar presente en la raíz del repo.
- **REQ-016**: El `pipeline` de `pre-commit` DEBE incluir: `ruff check` (lint), `ruff format --check` (format), `mypy` sobre los archivos `staged` de las capas dentro del alcance, y un chequeo de `Conventional Commits` para el mensaje.
- **REQ-017**: El `pipeline` de `pre-commit` DEBE bloquear cualquier mensaje de `commit` que contenga `Co-Authored-By` (case-insensitive) según la sección Workflow de la Constitución.

### 3.6 Higiene del repo

- **REQ-018**: Un `.gitignore` DEBE cubrir los artefactos de `build`/`runtime` de Python: `__pycache__/`, `*.pyc`, `*.pyo`, `*.egg-info/`, `dist/`, `build/`, `.venv/`, `venv/`, `env/`, `.pytest_cache/`, `.ruff_cache/`, `.mypy_cache/`, `.coverage`, `htmlcov/`, `logs/`, `tmp/`, `staging/`, `.idea/`, `.vscode/`.
- **REQ-019**: Un `.editorconfig` DEBE estar presente en la raíz del repo con: indentación de 4 espacios, finales de línea LF, encoding UTF-8, recortar espacios al final, insertar `newline` final.
- **REQ-020**: El esqueleto NO DEBE agregar ningún dato de muestra/test que contenga CIFs reales, nombres de clientes ni números de cuenta (Principio VIII de la Constitución).

### 3.7 Smoke test

- **REQ-021**: `tests/test_smoke.py` DEBE existir y contener al menos dos tests:
  - Uno que afirme que `import cmcourier` tiene éxito.
  - Uno que afirme que `cmcourier.__version__` es un `string` no vacío que coincide con el patrón SemVer.
- **REQ-022**: El `smoke test` DEBE pasar sobre el esqueleto vacío — es la única prueba de que el andamiaje funciona.

### 3.8 Actualización de documentación

- **REQ-023**: La sección `Getting started` en `README.md` DEBE estar completada (ya no un `placeholder`), describiendo los comandos de `install` / `test` / `lint`.
- **REQ-024**: Una entrada en `CHANGELOG.md` bajo `[Unreleased]` DEBE documentar este cambio antes de que aterrice el `commit`.
- **REQ-025**: El checklist de Status en `README.md` DEBE tildar la línea del `bootstrap`.

### 3.9 Arquitectura de documentación

- **REQ-026**: El repo DEBE contener un `docs/INDEX.md` a nivel `top-level` que mapee cada artefacto de documentación (constitución, `domain spec`, roadmap, README, CHANGELOG, CONTRIBUTING, how-to, explanation, samples) con una descripción de una línea y un link. El INDEX es el punto de entrada canónico para descubrir documentación.
- **REQ-027**: El repo DEBE contener `docs/how-to/README.md` describiendo el propósito de las guías how-to (orientadas a problemas, pasos prácticos para "cómo usar"), la convención de nombres (`how-to/<task-slug>.md`), y listando las guías disponibles actualmente (lista de bullets vacía al inicio del MVP).
- **REQ-028**: El repo DEBE contener `docs/explanation/README.md` describiendo el propósito de los documentos de explicación (orientados a entender, "cómo funciona"), la convención de nombres (`explanation/<concept-slug>.md`), y listando las explicaciones disponibles actualmente (lista de bullets vacía al inicio del MVP).
- **REQ-029**: La sección "Documentation map" en `README.md` DEBE linkear a `docs/INDEX.md` como punto de entrada canónico. Los links individuales de artefactos permanecen en el mapa del README para acceso rápido; INDEX.md es el espejo navegable de una sola página.

---

## 4. Escenarios de Aceptación

Los escenarios usan formato Given/When/Then. Cada uno es verificable de forma independiente.

### 4.1 La instalación fresca funciona

- **Given** un `checkout` limpio del branch `feat/001-bootstrap-python-skeleton`
- **And** Python 3.11 o superior está instalado
- **And** un `virtualenv` fresco está activo
- **When** el contribuyente corre `pip install -e .[dev]`
- **Then** la instalación se completa sin errores
- **And** `python -c "import cmcourier; print(cmcourier.__version__)"` imprime un `string` SemVer

### 4.2 El smoke test pasa

- **Given** el paquete está instalado según el escenario 4.1
- **When** el contribuyente corre `pytest`
- **Then** el `smoke test` pasa
- **And** el reporte de tests muestra cero `failures`, cero errores

### 4.3 El linter pasa sobre el esqueleto

- **Given** el paquete está instalado según el escenario 4.1
- **When** el contribuyente corre `ruff check src/ tests/` y `ruff format --check src/ tests/`
- **Then** no se reportan errores
- **And** el `exit code` es cero

### 4.4 El type checker aplica strict sobre domain

- **Given** el paquete está instalado según el escenario 4.1
- **When** el contribuyente corre `mypy --strict src/cmcourier/domain/`
- **Then** no se reportan errores
- **And** el `exit code` es cero

### 4.5 El hook de pre-commit bloquea commits malos

- **Given** el contribuyente corrió `pre-commit install` en su `working tree`
- **When** intenta un `commit` con un mensaje que contiene `Co-Authored-By: <cualquiera>`
- **Then** el `commit` es abortado con un mensaje que nombra la línea ofensora
- **And** el `commit` NO se agrega al branch

### 4.6 El hook de pre-commit bloquea commits no convencionales

- **Given** el contribuyente corrió `pre-commit install`
- **When** intenta un `commit` con el `subject` `update stuff`
- **Then** el `commit` es abortado porque el mensaje no cumple con `Conventional Commits`

### 4.7 Layering hexagonal visible en el layout

- **Given** el cambio se mergeó
- **When** alguien externo abre `src/cmcourier/`
- **Then** ve los directorios `domain/`, `adapters/`, `services/`, `orchestrators/`, `cli/`, `config/`
- **And** cada directorio tiene un `__init__.py`
- **And** `domain/` contiene archivos `placeholder` `models.py`, `ports.py`, `exceptions.py` con `docstrings` explicando su rol futuro

### 4.8 Sin PII en fixtures

- **Given** el cambio se mergeó
- **When** el contribuyente busca con `grep` patrones de PII conocidos (CIFs de 6 dígitos con aspecto real, nombres argentinos comunes) bajo `src/`, `tests/`, `docs/samples/`
- **Then** no se encuentran coincidencias
- **And** cualquier archivo de muestra usa identificadores sintéticos como `JUANPEREZ01` (ya documentado como sintético en la `domain spec`)

### 4.9 El índice de documentación es descubrible

- **Given** el cambio se mergeó
- **When** un nuevo contribuyente abre `README.md`
- **Then** encuentra un link a `docs/INDEX.md` en la sección "Documentation map"
- **And** al abrir `docs/INDEX.md` ve un mapa completo de toda la documentación actual agrupada por categoría
- **And** al abrir `docs/how-to/README.md` ve la declaración de propósito, la convención de nombres y una lista de bullets (vacía por ahora) de guías disponibles
- **And** al abrir `docs/explanation/README.md` ve la misma estructura para explicaciones

---

## 5. Fuera de Alcance

Estos elementos NO forman parte de este cambio. Cada uno tiene su propio cambio futuro.

- Implementación de cualquier modelo de dominio (`TriggerRecord`, `RVABREPDocument`, `CMMapping`, etc.). El `spec`/`plan`/código para eso es el segundo cambio.
- Implementación de cualquier `port` (interfaz). Igual que arriba.
- Cualquier adaptador concreto (CSV, AS400, SQLite, CMIS, ensamblado de PDF). Cada adaptador tiene su propio cambio.
- Cualquier código de `pipeline` u `orchestrator`.
- Cualquier comando CLI más allá de un `placeholder` de grupo Click que imprima un mensaje de ayuda.
- Schema de configuración (modelos `pydantic` para `config.yaml`).
- Archivo `config.yaml` real bajo `config/`.
- `docker-compose.yml` para tests de integración con Alfresco.
- Documentación del setup del driver AS400 en Linux.
- Definición del `pipeline` de CI (GitHub Actions, etc.). Va a aterrizar en un cambio `chore` separado una vez que la superficie de tests lo justifique.
- Aplicación real del umbral de `coverage` (el esqueleto no tiene código testeable; el umbral se vuelve vinculante cuando aterrice el primer código real).

---

## 6. Restricciones de la Constitución

Este `spec` NO DEBE violar ningún principio constitucional. Específicamente:

- **Principio I**: `domain/` se crea sin imports `third-party`. Incluso los `placeholders` de solo `docstring` no importan nada.
- **Principio III**: cada archivo de config que creamos se mantiene bajo los `tripwires` (sin un `pyproject.toml` de 1000 líneas). Todos los archivos en este cambio son cortos.
- **Principio V**: sin lectura de variables de entorno en ningún módulo que no sea el (futuro) `config/env.py`. Los módulos del esqueleto están suficientemente vacíos como para que esto sea trivial.
- **Principio VII**: este `spec` existe antes de que se entregue cualquier código. Los archivos `plan` y `tasks` existen antes de que empiece cualquier implementación.
- **Principio VIII**: sin PII en ningún lado. Confirmado en el escenario 4.8.
- **Principio IX**: cada decisión en este `spec` está justificada — sin decoración, sin seguir modas.

---

## 7. Riesgos y Preguntas Abiertas

### 7.1 Riesgos conocidos

- **Los `pre-commit hooks` pueden frenar al primer contribuyente** hasta que se acostumbre a arreglar errores de `lint`/`format` localmente antes de pushear. Mitigación: documentado en CONTRIBUTING.md con comandos concretos de fix (`ruff format src/`, `ruff check --fix src/`).
- **`mypy --strict` sobre el esqueleto vacío puede no surfacear problemas hoy y después explotar en el momento en que aterriza código real.** Eso es por diseño — el modo `strict` captura los problemas en la línea donde se introducen, no al final de un sprint. El `plan` documenta cómo manejar la adopción gradual si fuera necesario.
- **`pyodbc` no se instala limpiamente en todos los hosts** sin los headers de desarrollo de `unixODBC`. La documentación de CI / contribuyente DEBE mencionar esto.

### 7.2 Preguntas abiertas (deben resolverse en plan.md)

- Elección del `build backend`: `setuptools`, `hatchling`, `pdm-backend`, o `poetry-core`? El `plan` elige uno y documenta por qué.
- Versión del framework `pre-commit`: pineada exactamente, o `>=`? El `plan` decide.
- El `smoke test` vive en `tests/test_smoke.py` (top-level) o `tests/unit/test_smoke.py`? El `plan` decide.
- `ruff` `per-file-ignores`: queremos que `__init__.py` esté exento de `F401` (imports no usados)? El `plan` decide.

---

## 8. Estrategia de Verificación

La verificación de este `spec` ocurre en `/sdd-verify` (o su equivalente manual) mapeando cada REQ y Escenario a un chequeo concreto:

- REQ-001 → `grep` que `pyproject.toml` existe en la raíz del repo, bloque `[project]` presente
- REQ-002 → correr el escenario 4.1 en un `venv` limpio
- REQ-003 → `python -c "import cmcourier"` sale con 0
- REQ-004 → `grep` del `entry-point` en `pyproject.toml`
- REQ-005, REQ-006 → `grep` de los `strings` de dependencias en `pyproject.toml`
- REQ-007 → `requires-python = ">=3.11"` presente
- REQ-008–REQ-010 → el árbol del repo coincide con el layout esperado
- REQ-011–REQ-014 → `grep` de los bloques de config en `pyproject.toml`, correr cada herramienta contra el árbol vacío
- REQ-015–REQ-017 → correr `pre-commit run --all-files`; correr un `commit` sintético intentando `Co-Authored-By` y verificar el rechazo
- REQ-018, REQ-019 → `grep` de entradas en `.gitignore` y `.editorconfig`
- REQ-020, escenario 4.8 → `grep` automatizado de patrones de PII
- REQ-021, REQ-022, escenario 4.2 → correr `pytest`
- REQ-023 → el `diff` de `README.md` muestra contenido nuevo bajo "Getting started"
- REQ-024 → el `diff` de `CHANGELOG.md` muestra la nueva entrada
- REQ-025 → el `diff` de `README.md` muestra el checkbox tildado
- REQ-026 → `docs/INDEX.md` existe con todos los artefactos documentados listados
- REQ-027 → `docs/how-to/README.md` existe con propósito + nombres + lista vacía
- REQ-028 → `docs/explanation/README.md` existe con la misma estructura
- REQ-029 → el `diff` de `README.md` muestra el link a `docs/INDEX.md` desde "Documentation map"
- Escenario 4.9 → click-through manual de README → INDEX → how-to/README → explanation/README

---

## 9. Referencias Cruzadas

- Constitución: `.specify/memory/constitution.md`
- `Domain ground truth`: la `domain spec` del proyecto (especialmente §14.2 "Project Layout" y §15 "Implementation Order")
- Roadmap post-MVP: `docs/roadmap/POST-MVP.md`
- Workflow del proyecto: `CONTRIBUTING.md`
- Changelog actual: `CHANGELOG.md`
