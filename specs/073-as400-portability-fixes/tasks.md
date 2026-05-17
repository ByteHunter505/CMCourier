# 073 — Tasks

## Fase 1 — Spec artifacts

- [x] 1.1 `specs/073-as400-portability-fixes/spec.md`
- [x] 1.2 `specs/073-as400-portability-fixes/plan.md`
- [x] 1.3 `specs/073-as400-portability-fixes/tasks.md`

## Fase 2 — Fix 1: doctor health-check query

- [ ] 2.1 Editar `src/cmcourier/cli/doctor.py` línea 379:
        `src.query("SELECT 1", [])` →
        `src.query("SELECT 1 FROM SYSIBM.SYSDUMMY1", [])`.
- [ ] 2.2 Escribir/extender `tests/unit/cli/test_doctor_as400.py`:
        mockear `As400DataSource`, capturar SQL, aseverar
        `SYSIBM.SYSDUMMY1`.
- [ ] 2.3 `pytest -m unit -k doctor` pasa.

## Fase 3 — Fix 2: mock generate respeta query + prepende schema

- [ ] 3.1 Editar `src/cmcourier/cli/commands/mock.py:259-267`
        (`_build_source`) — pasar `query=source.query` si existe;
        fallback table = `f"{conn.database}.RVABREP"`.
- [ ] 3.2 Test 1: `source.query` seteado → As400DataSource recibe
        `query=...`.
- [ ] 3.3 Test 2: `source.query=None`, `connection.table=None` →
        As400DataSource recibe `table="RVILIB.RVABREP"`.
- [ ] 3.4 Test 3 (regresión): `connection.table="MYLIB.MYTABLE"` se
        respeta sin modificar.
- [ ] 3.5 `pytest -m unit -k mock_generate` pasa.

## Fase 4 — Fix 3: planner permisivo

- [ ] 4.1 Editar `src/cmcourier/services/mock/planner.py:215-233`:
        `_dispatch_image_kind` retorna `FileKind | None` en vez de
        `raise ConfigurationError`.
- [ ] 4.2 Editar el callsite (línea ~155): si `kind is None`, emitir
        `_log.warning(..., extra={...})` con `txn_num`, `image_type`,
        `reason`, y `continue`.
- [ ] 4.3 Actualizar docstring de `plan_files` para reflejar el
        nuevo comportamiento permisivo (líneas ~107-108).
- [ ] 4.4 Test: 6 filas con mezcla de códigos → planner yieldea
        solo los conocidos + loggea 2 warnings.
- [ ] 4.5 `pytest -m unit -k planner` pasa.

## Fase 5 — Tests de regresión

- [ ] 5.1 `pytest -m unit` entero (no solo los nuevos).
- [ ] 5.2 `pytest -m integration` (puede saltarse en Windows si
        Alfresco/Docker no está; mínimo: que los unit/integration
        no-AS400 pasen).

## Fase 6 — CHANGELOG + version bump

- [ ] 6.1 `CHANGELOG.md` nueva entry `[0.75.0]` documentando los
        tres fixes con referencias a spec 073.
- [ ] 6.2 `pyproject.toml` version `0.74.0` → `0.75.0`.
- [ ] 6.3 `.venv/bin/pip install -e . --no-deps` (o equivalente
        Windows).
- [ ] 6.4 `cmcourier --version` debe imprimir `0.75.0`.

## Fase 7 — Commits phased

- [ ] 7.1 Commit 1: `feat: add 073 spec, plan, tasks` (solo `specs/073-*/`).
- [ ] 7.2 Commit 2: `fix(doctor): use SYSIBM.SYSDUMMY1 for AS400 health-check`.
- [ ] 7.3 Commit 3: `fix(mock): respect indexing.source.query + prepend schema in fallback table`.
- [ ] 7.4 Commit 4: `fix(mock): warn-and-skip unknown image_type instead of aborting`.
- [ ] 7.5 Commit 5: `test: cover 073 doctor + mock generate + planner permissive`.
- [ ] 7.6 Commit 6: `docs(073): CHANGELOG 0.75.0 + version bump`.
- [ ] 7.7 `git push origin main`.
