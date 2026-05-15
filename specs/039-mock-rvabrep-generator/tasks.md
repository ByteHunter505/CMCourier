# 039 — Tareas

## Fase 1: servicio generador + subcomando CLI

- [ ] 1.1 Dataclass frozen `RvabrepGenSpec` en
      `src/cmcourier/services/mock/rvabrep_generator.py` —
      rows / seed / output / idrvi_pool / image_mix /
      date_from / date_to / clients / delete_rate / cif_rate.
- [ ] 1.2 `generate_rvabrep(spec, out_path) -> int` `writer` de
      `streaming` usando `csv.writer`. Devuelve filas escritas.
- [ ] 1.3 Helpers: `_pick_idrvi`, `_pick_image_type`,
      `_pick_creation_date`, `_pick_last_view_date`,
      `_pick_total_pages`, `_pick_file_name`, `_pick_image_path`,
      `_pick_txn_num`, `_pick_client`, `_pick_cif`.
- [ ] 1.4 `_validate_row` por fila que lanza
      `ConfigurationError` con el índice de fila. Corre antes de
      cada escritura.
- [ ] 1.5 Subcomando Click `cmcourier mock rvabrep` cableado en
      el grupo `mock` existente con los flags de la spec.
- [ ] 1.6 El CLI carga el CSV fuente IDRVI vía
      `TabularDataSource`, deduplica IDRVIs, toma top-N
      lexicográficamente, y construye el `RvabrepGenSpec`.
- [ ] 1.7 Tests unitarios (10 casos según el plan de Fase 1):
      determinismo, conteo de filas, unicidad de `txn_num`,
      tolerancia de mezcla de imágenes, respeto del pool IDRVI,
      invariantes PDF, extensiones paginadas, rango de fechas,
      `last_view`, falla de invariante.
- [ ] 1.8 Suite unitaria completa + `mypy` + `ruff` limpios.
- [ ] 1.9 Commit
      `feat(services,cli): cmcourier mock rvabrep — synthetic RVABREP CSV generator (039 Phase 1)`.

## Fase 2: test de integración + mock generate encadenado

- [ ] 2.1 `tests/integration/cli/test_mock_rvabrep.py` con el
      escenario end-to-end (`CliRunner`, 100 filas,
      `IndexingService` + `MappingService` consumen la salida).
- [ ] 2.2 Integración encadenada con `mock generate` con bordes
      de tamaño pequeños verifica que 100 archivos físicos
      materialicen.
- [ ] 2.3 Suite completa + `mypy` + `ruff` limpios.
- [ ] 2.4 Commit
      `test(integration): rvabrep generator end-to-end + chained mock generate (039 Phase 2)`.

## Fase 3: docs + CHANGELOG 0.42.0 + version bump + FF

- [ ] 3.1 `runbook` del operador
      `docs/how-to/mock-rvabrep-generator.md` — flags, ejemplos
      (1k / 50k / 1M), flujo encadenado con `mock generate`,
      determinismo, caveat de la fuente IDRVI.
- [ ] 3.2 `scripts/staging/README.md` — agregar una §X enlazando
      el nuevo how-to.
- [ ] 3.3 `CHANGELOG.md [0.42.0]` — solo sección Added.
- [ ] 3.4 Tilde de la fila de feature en el README.
- [ ] 3.5 Versión de `pyproject.toml` → `0.42.0`.
- [ ] 3.6 Smoke a 50k: el comando se completa en < 5s, salida
      parseable.
- [ ] 3.7 Suite completa + `mypy` + `ruff` limpios.
- [ ] 3.8 Commit
      `docs(039): mock-rvabrep how-to + CHANGELOG 0.42.0 + version bump (039 Phase 3)`.
- [ ] 3.9 Merge FF a main.
