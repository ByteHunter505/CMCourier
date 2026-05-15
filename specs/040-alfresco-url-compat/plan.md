# 040 — Plan

Dos fases, ~1.5h en total.

## Fase 1 — Helper `_service_url` + intercambio en 6 puntos + tests (~1h)

### Archivos

- `src/cmcourier/adapters/upload/cmis_uploader.py`
  - Agregar el método `_service_url(suffix: str = "") -> str`.
  - Reemplazar 6 construcciones de URL inline con f-string:
    - `_warmup_session` línea ~388: `f"{base}/{repo_id}"` →
      `self._service_url()`.
    - `test_connection` (si comparte el patrón de warmup).
    - `get_type_definition`: `f"{base}/{repo_id}"` →
      `self._service_url()`.
    - `verify_folder_exists` línea ~315:
      `f"{base}/{repo_id}/root/{normalized}"` →
      `self._service_url(f"root/{normalized}")`.
    - `upload` línea ~365: igual.
    - Cualquier otro path `_check_*` futuro (ninguno hoy).
- `tests/integration/adapters/test_cmis_uploader.py`
  - Nueva clase `TestServiceUrl` con 4 tests tipo unitarios:
    - `_service_url() == base_url` cuando `repo_id=""`.
    - `_service_url() == f"{base_url}/{repo_id}"` cuando
      `repo_id` está definido.
    - `_service_url("root/X") == f"{base_url}/root/X"` cuando
      vacío.
    - `_service_url("root/X") == f"{base_url}/{repo_id}/root/X"`
      cuando definido.
  - Nueva clase de integración `TestAlfrescoStyleUrls` con 3
    casos usando ``responses``:
    - `verify_folder_exists` con `repo_id=""` hace GET a
      `.../browser/root/<path>` y acepta un JSON de carpeta.
    - `upload` con `repo_id=""` hace POST a
      `.../browser/root/<path>`.
    - `get_type_definition` con `repo_id=""` consulta
      `.../browser` (sin id en el path).
  - Los tests estilo IBM-CM existentes (con `repo_id` definido)
    siguen pasando sin cambios — el helper es un refactor puro
    para esos.

### Tests

```bash
.venv/bin/python -m pytest tests/integration/adapters/test_cmis_uploader.py -x
.venv/bin/python -m mypy src/cmcourier/
.venv/bin/python -m ruff check src/cmcourier/ tests/
```

### Commit

```
fix(uploader): repo_id='' emits Alfresco-style URLs without doubled-slash (040 Phase 1)
```

## Fase 2 — Docs de config + CHANGELOG 0.43.0 + smoke + FF (~30min)

### Archivos

- `scripts/staging/config-staging.yaml.template`
  - Agregar un bloque de comentarios sobre la sección `cmis`
    explicando la distinción Alfresco vs IBM CM:
    ```yaml
    cmis:
      # Browser Binding service URL.
      # - IBM Content Manager: ".../cmis-browser" (NO trailing /browser);
      #   set repo_id to the CM repository identifier.
      # - Alfresco Community: ".../public/cmis/versions/1.1/browser";
      #   set repo_id to "" (the path already encodes the repo id).
      base_url: "<host>"
      repo_id: ""
    ```
- `docs/how-to/local-staging-simulation.md`
  - El Paso 4 refleja `repo_id: ""` para la config del Alfresco
    de staging.
- `docs/how-to/cmis-target-preflight.md`
  - Agregar una nota en §5 (disciplina operativa) sobre la
    convención de URL.
- `CHANGELOG.md`
  - `[0.43.0]` — Added: compatibilidad de URL Alfresco vía
    `repo_id=""`. Changed: semánticas de `CmisConfig.repo_id`
    (vacío antes estaba indefinido → ahora explícito "sin id en
    el path").
- `README.md`
  - Tildar la fila de feature.
- `pyproject.toml`
  - Bump de versión 0.42.0 → 0.43.0.

### Smoke

Tras el commit:

```bash
.venv/bin/cmcourier doctor --config sample/config-staging.yaml --check cm-targets
```

Esperar 3 PASS (`cm_type_alignment`, `cmis_folders_exist`,
`cmis_properties_alignment`) contra `testserver:8080`.

### Commit

```
docs(040): config doc updates + CHANGELOG 0.43.0 + version bump (040 Phase 2)
```

### FF a main, la rama queda.
