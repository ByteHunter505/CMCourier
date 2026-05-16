> [← Volver al índice](../INDEX.md) · [Tutoriales](README.md)

# 00 — Getting Started

Vas a clonar el repo, instalar las dependencias, correr el smoke test y disparar la CLI por primera vez. Al final tenés un entorno verde sobre el que se construyen todos los demás tutoriales.

Tiempo estimado: 15–25 min según conexión y plataforma.

---

## Prerrequisitos

CMCourier corre sobre Python 3.11+ y depende de un par de cosas nativas. Si te falta algo, instalalo antes de seguir.

| Requisito | Por qué |
|-----------|---------|
| **Python 3.11 o 3.12** | El proyecto declara `requires-python = ">=3.11"`. Pydantic v2 + `httpx[http2]` esperan esta versión. |
| **Git** | Para clonar el repo y para los pre-commit hooks. |
| **Compilador de C + headers ODBC** | `pyodbc` se compila durante el `pip install`. Sin esto el install rompe. |
| **Docker** (opcional, para staging) | El runbook de dry-run levanta un Alfresco 23.x en Docker como destino CMIS de pruebas. No hace falta para los tests unitarios. |

### Instalación de las dependencias de sistema

**Linux (Debian/Ubuntu):**

```bash
sudo apt install build-essential unixodbc-dev git
```

**macOS (Homebrew):**

```bash
brew install unixodbc git
```

**Windows:**

Instalá el [IBM iSeries Access ODBC Driver](https://www.ibm.com/support/pages/ibm-i-access-client-solutions) (ya trae su propio SDK), Git for Windows, y Python 3.11+ desde python.org. Build Tools de Visual Studio si pyodbc te pide compilar.

> ¿Vas a apuntar contra AS400 real? El driver iSeries Access es el oficial; el `unixodbc-dev` solo da los headers para compilar `pyodbc`, no el driver. Para los tutoriales iniciales no hace falta — los smoke tests y el `doctor` corren sin AS400.

---

## 1. Cloná el repo

```bash
git clone <url-del-repo> CMCourier
cd CMCourier
```

A partir de acá todos los comandos suponen que estás parado en la raíz del repo (donde vive `pyproject.toml`).

---

## 2. Creá y activá el virtualenv

Mantenemos las dependencias aisladas. Usá `venv` del stdlib:

```bash
python3 -m venv .venv
source .venv/bin/activate          # Linux / macOS
# .venv\Scripts\activate           # Windows (PowerShell o cmd)
```

Si el prompt te muestra `(.venv)` adelante, estás adentro. Si abrís otra terminal después, vas a tener que reactivarlo. Algunos editores (VSCode con la extensión Python, PyCharm) detectan el `.venv` automáticamente.

> Si tenés `uv` instalado, podés usar `uv venv` en lugar de `python3 -m venv .venv` — es bastante más rápido. Funciona igual de bien con el resto del workflow.

---

## 3. Instalá el paquete en modo editable

CMCourier expone un extra `dev` que trae pytest, ruff, mypy y pre-commit. Querés ese.

```bash
pip install -e ".[dev]"
```

O si usás `uv`:

```bash
uv pip install -e ".[dev]"
```

El `-e` (editable) hace que los cambios en `src/cmcourier/` se reflejen sin reinstalar. El comillas-alrededor-del-extra es importante en zsh; en bash funciona sin comillas también.

Esto te instala (entre otras):

- `pydantic>=2.0,<3.0` — validación de config
- `click>=8.1,<9.0` — CLI
- `httpx[http2]>=0.27,<1.0` — cliente CMIS con HTTP/2
- `pyodbc>=5.0,<6.0` — driver AS400
- `pandas>=2.0,<3.0`, `openpyxl` — CSV/XLSX
- `img2pdf`, `Pillow`, `PyPDF2` — ensamblado de PDF en S4
- `textual>=0.80,<6.0` — TUI
- `psutil>=5.9,<7.0` — métricas de sistema

Si `pyodbc` falla compilando, casi siempre es porque te faltan los headers ODBC. Volvé al paso de prerrequisitos.

---

## 4. Instalá los pre-commit hooks

CMCourier corre `ruff` (lint + format) y `mypy` antes de cada commit. La constitución prohíbe `--no-verify`, así que si los hooks no están instalados el primer commit te explota la cara.

```bash
pre-commit install
pre-commit install --hook-type commit-msg
```

El segundo hook valida que tus commits sigan el formato conventional (`feat:`, `fix:`, `docs:`, etc.).

---

## 5. Smoke test: correr la suite unitaria

Si la instalación está sana, los tests unitarios pasan en unos segundos.

```bash
pytest -m unit
```

Esperás algo del estilo:

```
================ test session starts ================
collected 800+ items / 400+ deselected
.......................................   [100%]
================ N passed, M deselected in 4.21s ================
```

Los markers disponibles (definidos en `pyproject.toml`):

| Marker | Para qué | Tiempo típico |
|--------|----------|---------------|
| `unit` | Ports mockeados, sin I/O | < 1 s cada uno |
| `integration` | Adapters reales contra SQLite/CSV locales | 1–10 s cada uno |
| `slow` | Tests que tardan | varía |

Comandos útiles:

```bash
pytest                              # toda la suite
pytest -m unit                      # solo unit
pytest -m integration               # solo integration
pytest -m "not slow"                # todo menos los lentos
pytest --cov src/cmcourier --cov-report=html   # con cobertura HTML
```

El gate de cobertura del proyecto es `fail_under = 80`. Si bajás de ese número, CI te rebota.

---

## 6. Disparar la CLI por primera vez

El entry point `cmcourier` quedó instalado por el `pip install -e`. Probalo:

```bash
cmcourier --help
```

Vas a ver el grupo principal con los subcomandos disponibles:

```
Usage: cmcourier [OPTIONS] COMMAND [ARGS]...

Commands:
  csv-trigger-pipeline   Run the CSV-triggered pipeline...
  rvabrep-pipeline       Run the RVABREP pipeline...
  local-scan-pipeline    Run the local-scan pipeline...
  single-doc             Diagnostic one-off pipeline...
  doctor                 Pre-flight validation...
  batch                  Batch lifecycle introspection
  inspect                Tracking DB inspection
  analyze                Log analysis
  as400-query            AS400 query passthrough
  background             Backgrounded long jobs
  sync                   AS400 NIARVILOG sync helpers
  mock                   Synthetic file tree generator
  cache                  Document cache maintenance
  completion             Shell completion install
```

> Si `cmcourier` no se encuentra, el venv no está activado. `source .venv/bin/activate` y de nuevo.

Instalar autocompletion para que la vida sea más fácil:

```bash
cmcourier completion bash       # o zsh, o fish
```

Eso te imprime el script — seguí las instrucciones que muestra para enchufarlo a tu shell.

---

## 7. Variables de entorno (para más adelante)

Para los tutoriales 02 en adelante vas a necesitar credenciales en el entorno. La constitución prohíbe credenciales en YAML commiteado.

```bash
export CMIS_USERNAME="..."          # usuario del repositorio CMIS
export CMIS_PASSWORD="..."          # password
export AS400_USERNAME="..."         # opcional; solo si usás source AS400
export AS400_PASSWORD="..."         # opcional
```

Para correr los tests unitarios y el `doctor` contra configs falsos no las necesitás. Las dejás cuando llegue el momento.

---

## Verificación final

Antes de pasar al 01, chequeá:

- [ ] `python --version` muestra 3.11 o superior
- [ ] `which cmcourier` devuelve una ruta dentro de `.venv/`
- [ ] `pytest -m unit` pasa en verde
- [ ] `cmcourier --help` muestra los comandos
- [ ] `pre-commit` está instalado (probá `pre-commit run --all-files` — debería terminar limpio)

Si los cinco dan check, estás listo. Si alguno falla, volvé a leer la sección correspondiente; casi siempre es un detalle del venv o de los headers ODBC.

---

## Siguientes pasos

- [01 — El YAML de configuración](01-the-yaml-config.md): armar tu primer config válido, sección por sección
- [02 — Pipelines y cuándo usarlas](02-pipelines-and-how-to-use-them.md): las cuatro pipelines, comparadas
- [`CONTRIBUTING.md`](../../CONTRIBUTING.md): si vas a abrir un PR, leelo antes
- [`README.md`](../../README.md): contexto general del proyecto y estado actual
