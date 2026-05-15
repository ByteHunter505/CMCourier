# 038 — Tareas

## Fase 1: columnas CMISFolder + CMISPropertyId a lo largo del stack

- [ ] 1.1 `MappingConfig.rvi_cm_cmis_folder_column: str = "CMISFolder"`
      + `MappingConfig.metadatos_cmis_property_id_column: str = "CMISPropertyId"`
      en `config/schema.py`.
- [ ] 1.2 `CMMapping.cmis_folder: str | None = None` en
      `domain/models.py`.
- [ ] 1.3 `MappingService` lee `CMISFolder` desde la columna
      configurada y puebla `cmis_folder`. Columna faltante →
      `None`; celda vacía → `None`.
- [ ] 1.4 `MetadataService.resolve_properties` clavea los
      resultados por `CMISPropertyId` cuando está poblado, por
      nombre amigable de lo contrario. Compat hacia atrás cuando
      la columna está ausente.
- [ ] 1.5 El constructor de URL de S5 en `StagedPipeline` consume
      `mapping.cmis_folder` (sin llamada de creación de carpeta
      acá todavía — fase 2).
- [ ] 1.6 Tests unitarios: valores por defecto del esquema; CSV
      del mapeo con / sin / con columna vacía; columna de
      metadata poblada / vacía / faltante.
- [ ] 1.7 Test de integración: la URL de S5 contiene `/$type/X`
      cuando `cmis_folder="$type/X"`.
- [ ] 1.8 Suite completa + `mypy` + `ruff` limpios.
- [ ] 1.9 Commit `feat(config,mapping,metadata,pipeline): CMISFolder + CMISPropertyId columns (038 Phase 1)`.

## Fase 2: verify_folder_exists + remover superficie de creación

- [ ] 2.1 Renombrar `IUploader.ensure_folder` →
      `verify_folder_exists` en `domain/ports.py`. Tipo de retorno
      `bool`. Actualizar docstring.
- [ ] 2.2 Reescribir el método en `CmisUploader` como una sonda
      de solo-lectura `GET ?cmisselector=object`; devolver
      `True` / `False` según el mapeo de respuesta de la spec;
      lanzar excepción en 401/conectividad.
- [ ] 2.3 Eliminar `CmisUploader._create_folder_segment`.
- [ ] 2.4 Remover la llamada `uploader.ensure_folder(...)` de
      `orchestrators/staged.py` S5.
- [ ] 2.5 Actualizar tests existentes del uploader:
      `verify_folder_exists_returns_true_for_existing`,
      `_returns_false_on_404`,
      `_returns_false_when_not_folder`.
- [ ] 2.6 Eliminar tests que referencien `_create_folder_segment`.
- [ ] 2.7 Test nuevo del `pipeline`: corrida feliz de 10 documentos
      registra cero llamadas a `verify_folder_exists`.
- [ ] 2.8 Suite completa + `mypy` + `ruff` limpios.
- [ ] 2.9 Commit `refactor(uploader,pipeline): verify_folder_exists (read-only) + remove S5 folder-creation surface (038 Phase 2)`.

## Fase 3: cmis_folders_exist + cmis_properties_alignment + cm-targets

- [ ] 3.1 `_check_cmis_folders_exist` en `cli/doctor.py`:
      PASS / FAIL (listar faltantes) / SKIP (sin `cmis_folder`).
- [ ] 3.2 `_check_cmis_properties_alignment` en `cli/doctor.py`:
      `get_type_definition` memoizado por tipo; PASS / FAIL
      (agrupado por tipo) / SKIP (sin `cmis_property_id`).
- [ ] 3.3 `_CHECK_GROUPS["cm-targets"]` registrado con los tres
      checks; grupo `cm-types` existente preservado.
- [ ] 3.4 `run_doctor` invoca los nuevos checks cuando el grupo
      activo coincide.
- [ ] 3.5 Tests unitarios en `tests/unit/cli/test_doctor.py`:
      caminos PASS / FAIL / SKIP para ambos nuevos checks;
      membresía de `cm-targets`.
- [ ] 3.6 Test de integración nuevo
      `tests/integration/cli/test_doctor_cm_targets.py` con
      `stub` uploader devolviendo respuestas deterministas.
- [ ] 3.7 Suite completa + `mypy` + `ruff` limpios.
- [ ] 3.8 Commit `feat(doctor): cmis_folders_exist + cmis_properties_alignment + cm-targets group (038 Phase 3)`.

## Fase 4: s5_upload_attempt + s5_upload_failed + unmask_pii

- [ ] 4.1 `ObservabilityConfig.unmask_pii: bool = Field(default=False)`
      en `config/schema.py`.
- [ ] 4.2 Auditar las reglas de enmascarado de
      `observability/pii.py` para los campos que emitimos;
      agregar conveniencia
      `mask_dict(properties, unmask=False)`.
- [ ] 4.3 `CmisUploader` emite `s5_upload_attempt` antes de cada
      intento de POST con propiedades enmascaradas.
- [ ] 4.4 En no-201, emite `s5_upload_failed` extendiendo el
      evento de intento con `status_code`, `response_body`
      truncado y `curl_equivalent`.
- [ ] 4.5 `curl_equivalent` honra `unmask_pii` (valores crudos
      cuando es true, enmascarados cuando es false).
- [ ] 4.6 El arranque de `cli/doctor.py` emite una línea WARNING
      cuando `unmask_pii=True`.
- [ ] 4.7 Tests unitarios para `pii.mask_value` + `pii.mask_dict`.
- [ ] 4.8 Tests de integración: 201 → 1 evento de intento;
      400 → intento + falla; `unmask_pii=true` → valores crudos;
      warning del doctor se muestra.
- [ ] 4.9 Suite completa + `mypy` + `ruff` limpios.
- [ ] 4.10 Commit `feat(observability,uploader): s5_upload_attempt + s5_upload_failed events + unmask_pii toggle (038 Phase 4)`.

## Fase 5: docs + CHANGELOG 0.41.0 + version bump + FF

- [ ] 5.1 `runbook` del operador
      `docs/how-to/cmis-target-preflight.md`:
      llenar las nuevas columnas del CSV; correr
      `doctor --check cm-targets`; leer
      `s5_upload_attempt` / `s5_upload_failed` desde
      `metrics.jsonl`; uso y riesgos de `unmask_pii`.
- [ ] 5.2 Agregar §X a `docs/how-to/validation-checklist.md`
      describiendo el paso de pre-flight `cm-targets`.
- [ ] 5.3 `scripts/staging/README.md` — agregar
      `bash register-model.sh` + pre-creación manual de carpeta +
      `doctor --check cm-targets` al camino de quick-start.
- [ ] 5.4 Entrada `CHANGELOG.md [0.41.0]` — Added, Changed
      (BREAKING `IUploader.ensure_folder` →
      `verify_folder_exists`), Removed
      (`_create_folder_segment`, auto-carpeta de S5).
- [ ] 5.5 `README.md` — tildar la fila de feature para
      pre-flight `cm-targets`.
- [ ] 5.6 Versión de `pyproject.toml` → `0.41.0`.
- [ ] 5.7 Corrida smoke contra el Alfresco de staging:
      pre-crear carpeta + `register-model.sh` + `doctor --check
      cm-targets` PASS + `pipeline` de 5 documentos escribe 5
      eventos de intento.
- [ ] 5.8 Suite completa + `mypy` + `ruff` limpios.
- [ ] 5.9 Commit `docs(038): cmis-target-preflight how-to + CHANGELOG 0.41.0 + IUploader contract bump (038 Phase 5)`.
- [ ] 5.10 Merge FF + eliminar la rama.
