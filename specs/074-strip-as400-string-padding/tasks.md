# 074 — Tasks

## Fase 1 — Spec artifacts

- [x] 1.1 `specs/074-strip-as400-string-padding/spec.md`
- [x] 1.2 `specs/074-strip-as400-string-padding/plan.md`
- [x] 1.3 `specs/074-strip-as400-string-padding/tasks.md`

## Fase 2 — Implementación

- [ ] 2.1 Editar `src/cmcourier/adapters/sources/as400.py`: agregar
        `_normalize_row(columns, row)` a nivel de módulo (después
        de los helpers existentes).
- [ ] 2.2 Reemplazar la materialización inline en `query()`
        (línea 95).
- [ ] 2.3 Reemplazar la materialización inline en `query_stream()`
        (línea 137).
- [ ] 2.4 Verificar sintaxis: `python -c "import ast; ast.parse(open('src/cmcourier/adapters/sources/as400.py').read())"`.

## Fase 3 — Tests

- [ ] 3.1 Crear `tests/unit/adapters/sources/test_as400_normalize.py`
        con los 7 tests del plan.
- [ ] 3.2 `pytest tests/unit/adapters/sources/test_as400_normalize.py -v`
        pasa.
- [ ] 3.3 `pytest -m unit` completo pasa sin regresiones.

## Fase 4 — CHANGELOG + version bump

- [ ] 4.1 `CHANGELOG.md` entry `[0.76.0]`.
- [ ] 4.2 `pyproject.toml` `version = "0.75.0"` → `"0.76.0"`.
- [ ] 4.3 `.venv/bin/pip install -e . --no-deps`.
- [ ] 4.4 `cmcourier --version` debe imprimir `0.76.0`.

## Fase 5 — Commits phased + push

- [ ] 5.1 Commit 1: `feat: add 074 spec, plan, tasks` (specs/).
- [ ] 5.2 Commit 2: `fix(adapters): strip whitespace from AS400 string columns at materialization (074)`.
- [ ] 5.3 Commit 3: `test: cover As400DataSource._normalize_row`.
- [ ] 5.4 Commit 4: `docs(074): CHANGELOG 0.76.0 + version bump`.
- [ ] 5.5 `git push origin main`.
