# 072 — Tasks

## Fase 1 — Movimientos físicos

- [ ] 1.1 `git mv docs/samples/csv/ reference-data/csv/`
- [ ] 1.2 `git mv docs/samples/excel/ reference-data/excel/`
- [ ] 1.3 `git mv docs/samples/responses/ reference-data/cmis-responses/`
- [ ] 1.4 `git mv docs/samples/config-reference.yaml docs/reference/config-reference.yaml`
- [ ] 1.5 `rm docs/samples/cmis_service.py` (untracked, gitignored — solo borrar del filesystem)
- [ ] 1.6 `rmdir docs/samples/` (queda vacío)
- [ ] 1.7 Verificar con `git status` que el rename se ve como `R` (rename), no como `A` + `D`.

## Fase 2 — Update del código de producción

- [ ] 2.1 `src/cmcourier/cli/commands/mock.py:320` — `_DEFAULT_IDRVI_SOURCE` apunta a `reference-data/csv/MapeoRVI_CM.csv`.
- [ ] 2.2 `src/cmcourier/cli/commands/mock.py:350` — string en `--help` actualizado.
- [ ] 2.3 Buscar otros hits accidentales en `src/`: `rg -F "docs/samples" src/`. Debe devolver cero.

## Fase 3 — Update de docs vivos

- [ ] 3.1 `docs/INDEX.md` líneas 186-188 — tabla "Datos de referencia". Actualizar paths Y movera la sección (ahora apunta fuera de `docs/`).
- [ ] 3.2 `docs/reference/cli.md` línea 338 — default de `--idrvi-source`.
- [ ] 3.3 `docs/adr/007-csv-trigger-primary-source.md` línea 45 — `TriggerExample.csv`.
- [ ] 3.4 `docs/how-to/mock-rvabrep-generator.md` líneas 51, 114 — defaults de `--idrvi-source`.
- [ ] 3.5 `docs/how-to/local-staging-simulation.md` líneas 155, 158, 167, 201, 202 — refs a `MapeoRVI_CM.csv` y `MetadatosCM.csv`.
- [ ] 3.6 `docs/how-to/developer/add-a-new-config-field.md` línea 87 — ref a `config-reference.yaml`.
- [ ] 3.7 `docs/tutorials/README.md` línea 41 — link a `config-reference.yaml`.
- [ ] 3.8 `docs/tutorials/01-the-yaml-config.md` líneas 9, 148, 453 — refs múltiples.
- [ ] 3.9 `docs/tutorials/05-doctor-deep-dive.md` línea 118 — ref al CSV de mapping.

## Fase 4 — Update de Constitution + skill registry

- [ ] 4.1 `.specify/memory/constitution.md` línea 148 — "test fixtures bajo `docs/samples/`..." → "...bajo `reference-data/`...".
- [ ] 4.2 `.specify/memory/constitution.md` línea 208 — "Sample data y reference files bajo `docs/samples/`" → "...bajo `reference-data/`".
- [ ] 4.3 `.atl/skill-registry.md` línea 151 — misma mención.

## Fase 5 — .gitignore + CHANGELOG + version bump

- [ ] 5.1 `.gitignore` — remover la línea `docs/samples/cmis_service.py` (la carpeta ya no existe).
- [ ] 5.2 `CHANGELOG.md` — nueva entry `[0.74.0]` documentando el move.
- [ ] 5.3 `pyproject.toml` — `version = "0.73.0"` → `"0.74.0"`.

## Fase 6 — Install + verify

- [ ] 6.1 `.venv/bin/pip install -e . --no-deps` para reinstalar con la nueva versión.
- [ ] 6.2 `cmcourier --version` debe imprimir `0.74.0`.
- [ ] 6.3 `cmcourier mock rvabrep --help | rg idrvi-source` debe mostrar el path nuevo.
- [ ] 6.4 `rg -F "docs/samples" src/ tests/ docs/ .specify/ .atl/ README.md` devuelve cero hits.
- [ ] 6.5 `pytest -m unit` pasa.

## Fase 7 — Commits phased

- [ ] 7.1 Commit 1: `feat: add 072 spec, plan, tasks` (solo `specs/072-*/`).
- [ ] 7.2 Commit 2: `refactor: relocate reference data out of docs/` (git mv + mock.py + .gitignore).
- [ ] 7.3 Commit 3: `docs: update path references to reference-data/` (docs/ + constitution + skill registry).
- [ ] 7.4 Commit 4: `docs(072): CHANGELOG 0.74.0 + version bump`.
- [ ] 7.5 `git log --oneline -5` para confirmar la cadena.
- [ ] 7.6 NO push.
