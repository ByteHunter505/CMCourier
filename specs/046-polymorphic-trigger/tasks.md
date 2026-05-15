# 046 — Tasks

## Fase 1 — Jerarquía Trigger en domain

- [ ] 1.1 ABC ``Trigger`` abstracto con ``audit_row()``.
- [ ] 1.2 ``ClientTrigger(shortname, cif, system_id)`` —
      audit_row devuelve campos literales.
- [ ] 1.3 ``RvabrepRowTrigger(row)`` — audit_row proyecta
      ``row[col_shortname]`` etc usando los defaults
      compartidos de ``RvabrepColumnsConfig``.
- [ ] 1.4 ``LocalScanTrigger(file_path, row)`` — misma proyección
      que ``RvabrepRowTrigger``.
- [ ] 1.5 Alias backward-compat ``TriggerRecord = ClientTrigger``
      así cada import existente sigue andando.
- [ ] 1.6 Tests unitarios: audit_row por subtipo + identidad del alias.
- [ ] 1.7 mypy + ruff limpios.
- [ ] 1.8 Commit
      ``feat(domain): polymorphic Trigger hierarchy (046 Phase 1)``.

## Fase 2 — Las estrategias S0 emiten el subtipo correcto

- [ ] 2.1 ``DirectRvabrepTriggerStrategy``: descartar dedup por
      ``(shortname, system_id)``; rendir
      ``RvabrepRowTrigger`` por cada fila no-borrada.
- [ ] 2.2 ``LocalScanTriggerStrategy``: rendir
      ``LocalScanTrigger(file_path, row)`` por cada archivo
      escaneado.
- [ ] 2.3 ``As400TriggerStrategy``: rendir ``RvabrepRowTrigger``
      por cada fila del SQL.
- [ ] 2.4 Actualizar los tests unitarios existentes de estrategia
      para assertear los nuevos subtipos.
- [ ] 2.5 mypy + ruff limpios.
- [ ] 2.6 Commit
      ``feat(services): per-pipeline trigger subtypes in S0 strategies (046 Phase 2)``.

## Fase 3 — Enrich polimórfico de S1 + helper de CIF

- [ ] 3.1 ``IndexingService.enrich(trigger)`` despachando por
      subtipo; reusa ``find_documents`` para ClientTrigger y
      ``_classify`` para triggers basados en row.
- [ ] 3.2 Helper ``_trigger_cif(trigger)`` en el módulo metadata.
- [ ] 3.3 El self-heal de CIF del ``MetadataResolver`` usa el helper.
- [ ] 3.4 El stage S1 de ``staged.py`` llama ``enrich`` en vez de
      ``find_documents``; ``_build_record`` usa
      ``trigger.audit_row()``.
- [ ] 3.5 Tests unitarios: enrich por subtipo (con guard de
      MagicMock en los caminos RvabrepRowTrigger / LocalScanTrigger).
- [ ] 3.6 Test unitario: ``_trigger_cif`` parametrizado sobre los
      subtipos + CIF-presente / CIF-ausente.
- [ ] 3.7 mypy + ruff limpios. Suite completa verde.
- [ ] 3.8 Commit
      ``feat(services,orchestrators): S1 polymorphic enrich + CIF helper (046 Phase 3)``.

## Fase 4 — docs + CHANGELOG 0.49.0 + bump de versión + re-verify en vivo + FF

- [ ] 4.1 ``CHANGELOG.md [0.49.0]`` — Added (jerarquía Trigger),
      Changed (semánticas de local-scan + rvabrep-direct), Fixed
      (expansión demasiado amplia de §E.4).
- [ ] 4.2 ``pyproject.toml`` 0.48.0 → 0.49.0.
- [ ] 4.3 ``.venv/bin/pip install -e . --no-deps``.
- [ ] 4.4 ``cmcourier --version`` reporta 0.49.0.
- [ ] 4.5 Tick en fila de features de ``README.md``.
- [ ] 4.6 ``docs/how-to/validation-checklist.md`` §E.4 — actualizar
      output esperado (100 docs, no 1860).
- [ ] 4.7 Re-verify en vivo §E.4: 100 archivos → 100 docs en
      Alfresco.
- [ ] 4.8 Suite completa unit + integration verde; ruff + mypy
      limpios.
- [ ] 4.9 Commit
      ``docs(046): CHANGELOG 0.49.0 + version bump + local-scan re-verify (046 Phase 4)``.
- [ ] 4.10 FF a main.
