# 046 — Plan

Cuatro fases (~3-4 h total). Las fases entregan en un orden que
mantiene la suite de tests verde en cada paso.

## Fase 1 — Definir la jerarquía Trigger (~45 min)

### Archivos

- `src/cmcourier/domain/models.py`
  - Nueva base abstracta ``Trigger`` + subtipos ``ClientTrigger`` /
    ``RvabrepRowTrigger`` / ``LocalScanTrigger``.
  - Cada subtipo implementa ``audit_row()`` devolviendo
    ``{shortname, cif, system_id}`` con la proyección apropiada.
  - Backward-compat: mantener ``TriggerRecord`` como nombre público
    apuntando a ``ClientTrigger`` así cada import existente sigue
    andando sin churn.

### Tests

- ``tests/unit/domain/test_trigger.py`` (nuevo):
  - ``ClientTrigger.audit_row`` devuelve los campos literales.
  - ``RvabrepRowTrigger.audit_row`` proyecta desde nombres de
    columna RVABREP vía el ``RvabrepColumnsConfig`` existente.
  - ``LocalScanTrigger.audit_row`` proyecta desde su fila capturada.
  - ``TriggerRecord is ClientTrigger`` assertea el alias.

### Commit

```
feat(domain): polymorphic Trigger hierarchy (046 Phase 1)
```

## Fase 2 — Las estrategias S0 emiten el subtipo correcto (~1 h)

### Archivos

- `src/cmcourier/services/triggers/direct_rvabrep.py`
  - Descartar el dedup por ``(shortname, system_id)``. Rendir un
    ``RvabrepRowTrigger(row=row)`` por cada fila no-borrada.
  - El docstring de la clase actualiza a reflejar "un trigger por
    fila RVABREP" (ya no "uno por cliente").
- `src/cmcourier/services/triggers/local_scan.py`
  - Reemplazar el yield de ``TriggerRecord`` con
    ``LocalScanTrigger(file_path=entry, row=row)``. La rama
    multi-match (colisiones raras de filename de RVABREP) rinde
    un trigger por cada fila matcheada.
- `src/cmcourier/services/triggers/as400.py`
  - Mismo cambio de forma que direct_rvabrep — rendir
    ``RvabrepRowTrigger(row=row)`` por cada fila del SQL.
- `src/cmcourier/services/triggers/csv.py`
  - Sin cambios de código. Sigue rindiendo ``ClientTrigger``
    (== ``TriggerRecord``).
- `src/cmcourier/services/triggers/single_doc.py`
  - Sin cambios de código. Sigue rindiendo ``ClientTrigger``.

### Tests

- Los archivos de ``tests/unit/services/triggers/`` para cada
  estrategia actualizan sus aserciones para chequear el nuevo
  subtipo:
  - direct_rvabrep: ``isinstance(t, RvabrepRowTrigger)`` y
    ``t.row[...] == expected``.
  - local_scan: ``isinstance(t, LocalScanTrigger)`` y
    ``t.file_path == expected``.
  - as400: ``isinstance(t, RvabrepRowTrigger)``.

### Commit

```
feat(services): per-pipeline trigger subtypes in S0 strategies (046 Phase 2)
```

## Fase 3 — Enrich polimórfico de S1 + helper de CIF (~1 h)

### Archivos

- `src/cmcourier/services/indexing.py`
  - Nuevo método público ``enrich(trigger: Trigger) ->
    list[RVABREPDocument]`` que despacha por subtipo:
    - ``ClientTrigger`` → camino existente de ``find_documents``.
    - ``RvabrepRowTrigger`` → ``[self._row_to_document(row)]``,
      reusando el helper interno existente ``_classify`` que
      construye el dataclass desde una fila raw.
    - ``LocalScanTrigger`` → igual que el caso de row.
  - ``find_documents`` y ``find_documents_batch`` quedan intactos
    para el camino de cliente. No cambiamos sus firmas.
- `src/cmcourier/services/metadata.py`
  - Nuevo helper a nivel módulo ``_trigger_cif(trigger) -> str |
    None`` que devuelve el CIF del atributo que sea que el
    trigger lleve (``ClientTrigger.cif`` o
    ``X.row[col_cif]``). El camino de self-healing de CIF del
    resolver usa esto en vez de ``trigger.cif`` directo.
- `src/cmcourier/orchestrators/staged.py`
  - Reemplazar la única llamada
    ``self._indexing_service.find_documents(t)`` en el stage S1 con
    ``self._indexing_service.enrich(t)``.
  - ``_build_record`` llama a ``trigger.audit_row()`` para llenar
    las tres columnas trigger_*; nada de acceso directo a atributos.

### Tests

- ``tests/unit/services/test_indexing.py``:
  - ``test_enrich_client_trigger_uses_find_documents`` —
    delegación happy-path.
  - ``test_enrich_rvabrep_row_trigger_skips_data_source`` —
    pasar un MagicMock IDataSource que falla en cualquier llamada;
    assertear que ``enrich`` devuelve exactamente un documento.
  - ``test_enrich_local_scan_trigger_returns_single_doc`` —
    mismo guard de MagicMock; assertear un documento por trigger
    sin importar cuántos docs tenga el cliente.
- ``tests/unit/services/test_metadata.py``:
  - ``test_trigger_cif_helper`` parametrizado sobre los tres
    subtipos, con y sin el CIF presente.
- ``tests/unit/orchestrators/test_staged.py``: los tests
  existentes que construyen un ``TriggerRecord`` y caminan el
  pipeline siguen pasando (son shape-csv — pegan el camino
  ``ClientTrigger``).

### Commit

```
feat(services,orchestrators): S1 polymorphic enrich + CIF helper (046 Phase 3)
```

## Fase 4 — Docs + CHANGELOG 0.49.0 + bump de versión + re-verify en vivo §E.4 + FF (~30 min)

### Archivos

- `CHANGELOG.md` ``[0.49.0]`` — Added (jerarquía Trigger),
  Changed (semánticas del set de upload de local-scan +
  rvabrep-direct — **visible operacionalmente**), Fixed (el issue
  de "expansión demasiado amplia" de §E.4 que catalogamos
  previamente como un hallazgo de docs).
- `pyproject.toml` 0.48.0 → 0.49.0.
- Tick en fila de features de `README.md`.
- `docs/how-to/validation-checklist.md` §E.4 (local-scan):
  actualizar el output esperado. Pre-046 teníamos 1860 docs de un
  pool de 100 archivos; post-046 esperamos exactamente 100.

### Release dance

```bash
.venv/bin/pip install -e . --no-deps
.venv/bin/cmcourier --version    # esperar 0.49.0
```

### Re-verify en vivo

Replicar §E.4 contra staging:

```bash
# Wipear ambos lados
bash scripts/staging/wipe-alfresco-docs.sh
rm -f sample/staging-tracking.db sample/staging-tracking.db-wal sample/staging-tracking.db-shm

# Mismo pool de scan de §E.4
ls sample/local-scan-pool | wc -l   # esperar ~200

CMIS_USERNAME=admin CMIS_PASSWORD=admin .venv/bin/cmcourier local-scan-pipeline run \
  --config sample/config-staging-localscan.yaml \
  --total 100 --no-tui
```

Aceptación:

- ``total_triggers == 100`` Y ``total_docs == 100`` (un doc por
  archivo escaneado — sin expansión demasiado amplia).
- ``s5_done == 100``, ``s5_failed == 0``.
- El tree-walk de los 21 folders de staging confirma 100 docs en
  Alfresco (matcheando los 100 archivos escaneados exactamente).

### Commit

```
docs(046): CHANGELOG 0.49.0 + version bump + local-scan re-verify (046 Phase 4)
```

### FF a main.
