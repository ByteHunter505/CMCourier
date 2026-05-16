# Estilo de código

> [← Volver al índice](../INDEX.md) · [Contributing](README.md)

Convenciones que están enforced por pre-commit hooks. Si pasás los hooks, pasaste el estilo.

---

## Stack de enforcement

| Herramienta | Configurada en | Qué chequea |
|-------------|----------------|-------------|
| `ruff` (lint + format) | `pyproject.toml [tool.ruff]` | E/F/W/I/B/UP rules, line length 100 |
| `mypy --strict` | `pyproject.toml [tool.mypy]` | tipado estricto en todo `src/cmcourier/` |
| `pytest --strict-markers --strict-config` | `pyproject.toml [tool.pytest.ini_options]` | sin markers/config inventados |
| `pre-commit` | `.pre-commit-config.yaml` | corre ruff + format + mypy en cada commit |

Instalá con:

```bash
pip install -e ".[dev]"
pre-commit install
```

**Nunca uses `--no-verify`** para esquivar un hook. Si un hook se queja, arreglá la causa.

---

## Reglas duras (Constitution Principio III)

- **Funciones ≤ 50 líneas.** Sin excepciones. Si lo necesitás, partila.
- **Archivos ≤ 400 líneas** (soft tripwire).
- **Clases ≤ 200 líneas** (soft tripwire).
- **Single Responsibility**: si una función hace dos cosas (calcular + escribir, validar + transformar), partila.

Estas reglas duelen al principio. Después dejan de doler porque el código queda más limpio.

---

## Naming

| Cosa | Convención | Ejemplo |
|------|-----------|---------|
| Módulo | `snake_case` | `lane_controller.py` |
| Clase | `PascalCase` | `StreamingOrchestrator` |
| Función / variable | `snake_case` | `acquire_triggers` |
| Constante | `UPPER_SNAKE_CASE` | `DEFAULT_BUCKET_SIZE` |
| Privado | prefijo `_` | `_lane_controller` |
| Type alias | `PascalCase` o sufijo `_T` | `LaneSnapshot`, `Bytes_T` |

**Identificadores siempre en inglés**. Los comentarios y docstrings van en español (post-spec 071).

---

## Tipado

`mypy --strict` corre sobre todo `src/cmcourier/`. Esto significa:

- Todas las funciones públicas tienen anotación de tipo en parámetros Y retorno.
- Sin `Any` salvo justificación explícita con `# type: ignore[<code>]`.
- `from __future__ import annotations` en todos los módulos.
- Imports al top del archivo.

```python
# Bien
def assemble(
    trigger: Trigger,
    docs: list[RVABREPDocument],
    assembly_cfg: AssemblyConfig,
) -> StagedFile:
    ...

# Mal — falta tipado de retorno, lista sin tipo de elemento
def assemble(trigger, docs, assembly_cfg):
    ...
```

---

## Hexagonal architecture rules

| Capa | Puede importar de | NO puede importar de |
|------|-------------------|----------------------|
| `domain/` | stdlib | nada externo, ni de adapters/services/orchestrators |
| `adapters/` | stdlib, libs externas, `domain/` (ports + exceptions) | services, orchestrators, cli |
| `services/` | stdlib, `domain/` | adapters concretos, orchestrators, cli |
| `orchestrators/` | stdlib, `domain/`, `services/` (vía interfaces si posible) | adapters concretos, cli |
| `cli/` | todo lo anterior + click | — |

Si te encontrás importando `requests` o `pyodbc` en un service, pará. Refactoreá vía un port en `domain/`.

---

## Comentarios y docstrings

- **Defaults: cero comentarios.** Los nombres ya dicen qué hace.
- Comentás solo cuando el "por qué" no es obvio (invariante oculto, workaround a bug específico, decisión contraintuitiva).
- Docstrings en español, ≤ 3 líneas para la mayoría. Para clases grandes, una línea de qué hace + una línea de cómo encaja en el sistema.

```python
# Mal — comenta el QUÉ obvio
# Incrementa el contador en uno
counter += 1

# Bien — comenta el POR QUÉ no obvio
# +1 por el poison-pill que el consumer va a recibir al final
counter += 1
```

---

## Commits

- **Conventional Commits**: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `perf`, `ci`.
- Subject ≤ 72 caracteres, imperative mood.
- Cuerpo explica el **por qué**, no el qué (eso ya está en el diff).
- **NUNCA** `Co-Authored-By`, atribuciones a AI, o similares.
- **NUNCA** `--no-verify`.
- Atómicos: un cambio lógico por commit. No mezcles refactor + feat.

Ejemplos:

```
feat(streaming): add bucket-based orchestrator (063)
fix(lanes): forward lane_controller property to pipeline (070)
refactor: translate orchestrators + adapters to Spanish (071 Phase 2)
chore: remove legacy REBIRTH domain doc and live references
```

---

## Streaming-first

Constitution Principio IV: streaming sobre buffering.

- CSV → iterar con `csv.reader`, no `pd.read_csv` para listas grandes.
- DB → `query_stream()` con cursor, no `query()` que materializa.
- HTTP uploads → `MultipartEncoder` con file iterator, no leer todo el archivo en RAM.
- Triggers → producer thread con bounded queue (streaming mode).

---

## Ver también

- [spec-driven-flow.md](spec-driven-flow.md) — workflow SDD
- [testing-philosophy.md](testing-philosophy.md) — qué tests escribir
- [Constitution Principio I, III, IV](../../.specify/memory/constitution.md)
- [`.pre-commit-config.yaml`](../../.pre-commit-config.yaml)
