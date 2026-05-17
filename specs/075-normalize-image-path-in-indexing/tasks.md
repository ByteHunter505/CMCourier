# 075 — Tasks

## Fase 1 — Spec

- [x] 1.1 `specs/075-normalize-image-path-in-indexing/spec.md`
- [x] 1.2 `specs/075-normalize-image-path-in-indexing/plan.md`
- [x] 1.3 `specs/075-normalize-image-path-in-indexing/tasks.md`

## Fase 2 — Implementación

- [ ] 2.1 Agregar helper `_normalize_image_path(value: str) -> str` en
        `src/cmcourier/services/indexing.py`.
- [ ] 2.2 Modificar línea 269 para envolver el `_str(...)` con el
        nuevo helper.
- [ ] 2.3 Verificar sintaxis y `mypy`.

## Fase 3 — Tests

- [ ] 3.1 Crear `tests/unit/services/test_indexing_image_path.py`
        con 8 tests de `_normalize_image_path`.
- [ ] 3.2 Suite completa: `pytest -m unit` sin regresiones.

## Fase 4 — CHANGELOG + bump

- [ ] 4.1 `CHANGELOG.md` entry `[0.77.0]`.
- [ ] 4.2 `pyproject.toml` `0.76.0` → `0.77.0`.
- [ ] 4.3 `pip install -e . --no-deps`.
- [ ] 4.4 `cmcourier --version` → `0.77.0`.

## Fase 5 — Commits + push

- [ ] 5.1 Commit 1: `feat: add 075 spec, plan, tasks`
- [ ] 5.2 Commit 2: `fix(indexing): normalize leading separators in RVABREP image_path (075)`
- [ ] 5.3 Commit 3: `test: cover image_path normalization`
- [ ] 5.4 Commit 4: `docs(075): CHANGELOG 0.77.0 + version bump`
- [ ] 5.5 `git push origin main`
