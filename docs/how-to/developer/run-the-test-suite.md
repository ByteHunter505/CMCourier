# Correr la batería de tests

> [← Volver al índice](../../INDEX.md) · [How-to](../README.md) · [Developer](README.md)

`pytest` es la herramienta única — sin tox, sin nox. Los tests están organizados por marcadores (`unit`, `integration`, `slow`) y por carpeta (`tests/unit/`, `tests/integration/`, `tests/e2e/`). El gate de coverage es `fail_under = 80`.

## Cuándo aplica

- Antes de abrir un PR.
- Antes de mergear (los hooks de pre-commit corren `ruff` + `mypy`, pero NO `pytest` — eso lo hacés vos).
- Cuando un test que pasaba localmente falla en CI: replicalo con los mismos marcadores que el job.

## Pasos

### 1. Setup una vez

```bash
uv pip install -e ".[dev]"
pre-commit install
```

Las dev deps incluyen `pytest`, `pytest-cov`, `respx` (mocking HTTP para los tests de uploader), `pandas-stubs` y `types-PyYAML`.

### 2. Corridas básicas por marcador

```bash
pytest                                  # toda la suite (incluye slow)
pytest -m unit                          # solo unit — mockea los ports, < 1 s por test
pytest -m integration                   # solo integration — adapters reales sobre SQLite/CSV/fixtures
pytest -m "not slow"                    # excluye los slow (> 5 s individuales)
pytest -m "unit or integration"         # unit + integration, sin slow
pytest -m "integration and not slow"    # integration rápidos
```

Los marcadores están declarados en `pyproject.toml [tool.pytest.ini_options].markers` con `--strict-markers`, así que un typo (`@pytest.mark.uint`) explota al recolectar.

### 3. Filtros por archivo, clase o test

```bash
pytest tests/unit/services/test_metadata.py
pytest tests/unit/services/test_metadata.py::test_bac_cif_resuelve_desde_trigger
pytest -k "metadata and not slow"               # filtro por substring en el nodeid
pytest tests/unit/ -x                            # parar al primer fail
pytest tests/unit/ --lf                          # solo los que fallaron la última vez
pytest tests/unit/ --ff                          # primero los que fallaron, después el resto
```

### 4. Verbosidad y output

```bash
pytest -v                       # nombre completo de cada test
pytest -vv                      # también valores en asserts (útil para diffs grandes)
pytest -s                       # no captures stdout (ver `print` y `logger.info`)
pytest --tb=short               # traceback corto (default es `auto`)
pytest --tb=line                # una línea por fallo (resumen)
pytest -ra                      # resumen final con razones de skip/xfail (ya está en addopts)
```

### 5. Coverage

```bash
pytest --cov=src/cmcourier --cov-report=term-missing
pytest --cov=src/cmcourier --cov-report=html      # luego abrí htmlcov/index.html
pytest --cov=src/cmcourier --cov-report=xml       # output para CI / Codecov
pytest --cov=src/cmcourier --cov-fail-under=90    # subí el bar para una corrida puntual
```

Configurado en `pyproject.toml`:

- Source: `src/cmcourier` (branch coverage activado).
- Gate global: `fail_under = 80`.
- Excluidos: `pragma: no cover`, `if TYPE_CHECKING:`, `raise NotImplementedError`.

### 6. Paralelo (opcional)

Si tenés `pytest-xdist` instalado:

```bash
pytest -n auto                  # tantos workers como cores
pytest -n 4 -m unit             # 4 workers, solo unit
```

Cuidado: los tests de integration que tocan `tracking.db` deben pedir `tmp_path` para aislamiento — fixtures session-scoped sobre el mismo path crashean en paralelo.

## Verificación

```bash
pytest -m "not slow" --cov=src/cmcourier         # lo que debería pasar antes de PR
pytest tests/test_smoke.py -v                     # smoke de boot-up
```

Si la coverage cae bajo 80%, el comando falla con código distinto de cero — CI lo bloquea.

## Fixtures clave

`tests/conftest.py` define una sola fixture session-scoped y `autouse=True`:

- **`_generate_xlsx_fixtures`** — genera `tests/fixtures/sources/sample.xlsx` y `tests/fixtures/sources/multi_sheet.xlsx` la primera vez que se invoca. Los XLSX son gitignored para no pollutear el repo con binarios; la generación es sub-segundo, determinística (datos hardcodeados).

Las fixtures específicas viven en `tests/fixtures/`:

- `tests/fixtures/services/metadata/` — CSVs para tests de `MetadataService`.
- `tests/fixtures/pipeline/` — CSVs RVABREP y `MetadatosCM` para tests end-to-end.
- `tests/fixtures/assembly/` — TIFFs/PDFs de página única para `PdfAssembler`.
- `tests/fixtures/sources/` — CSV y XLSX para `TabularDataSource`.

`pytest_collection_modifyitems` no está en juego — los marcadores se aplican por `pytestmark = pytest.mark.unit` al inicio del módulo o por `@pytest.mark.integration` por test.

## Convenciones del repo

- **Unit (`@pytest.mark.unit`)**: mockean los `ports` (`IDataSource`, `ITrackingStore`, `IUploader`). Sin I/O. < 1 s cada uno. Viven en `tests/unit/`.
- **Integration (`@pytest.mark.integration`)**: usan adapters reales (`TabularDataSource` sobre CSV, `SQLiteTrackingStore` sobre `tmp_path`, `CmisUploader` con `respx`). 1–10 s cada uno. Viven en `tests/integration/`.
- **E2E (`tests/e2e/`)**: tocan Alfresco o AS400 vivos. Limitados, no corren en CI default; los corre el operador antes de release.
- **AS400 NO se mockea** (Principio VI). Cuando un test necesita comportamiento de `IDataSource` AS400-shaped, usa `TabularDataSource` sobre CSV — es el sustituto canónico para dev/test.
- **Helpers como `_CountingSource`** envuelven adapters reales y cuentan invocaciones; no son stubs, son wrappers que delegan.
- **PII en fixtures**: los CIF y nombres en fixtures son falsos por construcción (`JUANPEREZ01`, `MARIAGOMEZ02`). Nunca commitees datos reales del banco.

## Gotchas

- **`addopts` ya incluye `--strict-markers --strict-config -ra`**. No los repitas en la línea de comando.
- **Coverage por branch**: un `if` cubierto en una rama y no en la otra cuenta como parcial. Usá `--cov-report=term-missing` para ver qué líneas / ramas faltan.
- **Paths absolutos en fixtures**: si un test usa `Path(__file__).parent`, el resultado depende del cwd. La convención del repo es `Path(__file__).parent.parent.parent / "fixtures"` desde un módulo de test — ver `tests/unit/services/test_metadata.py:_FIXTURES`.
- **mypy strict en `cmcourier.domain.*`, `cmcourier.services.*`, `cmcourier.orchestrators.*`** (ver `pyproject.toml [[tool.mypy.overrides]]`). Si añadís código en estas capas, los tipos no perdonan — `Any` es prohibido salvo en bordes I/O.
- **No corras `pytest --no-verify` cuando un hook falla** — los hooks (`ruff`, `mypy`) protegen el invariante. `--no-verify` está prohibido por Constitución.

## Ver también

- `pyproject.toml` — `[tool.pytest.ini_options]`, `[tool.coverage.*]`, `[tool.mypy]`
- `tests/conftest.py` — fixtures session-scoped
- `.specify/memory/constitution.md` — Principio VI (no mockear AS400)
- [`profile-a-bottleneck.md`](profile-a-bottleneck.md) — cuando los tests pasan pero el pipeline va lento
