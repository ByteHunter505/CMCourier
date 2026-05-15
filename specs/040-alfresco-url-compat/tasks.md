# 040 — Tareas

## Fase 1: helper + intercambios de URL + tests

- [ ] 1.1 Agregar el método
      `_service_url(suffix: str = "") -> str` a `CmisUploader`.
- [ ] 1.2 URL de `_warmup_session` → `self._service_url()`.
- [ ] 1.3 URL de `get_type_definition` → `self._service_url()`.
- [ ] 1.4 URL de `verify_folder_exists` →
      `self._service_url(f"root/{normalized}")`.
- [ ] 1.5 URL de `upload` →
      `self._service_url(f"root/{normalized}")`.
- [ ] 1.6 `test_connection` (si comparte el patrón de warmup) →
      igual.
- [ ] 1.7 Tests unitarios para `_service_url` (4 casos).
- [ ] 1.8 Tests de integración para URLs estilo Alfresco (3 casos).
- [ ] 1.9 Los tests estilo IBM-CM existentes pasan sin cambios.
- [ ] 1.10 `mypy` + `ruff` limpios.
- [ ] 1.11 Commit
      `fix(uploader): repo_id='' emits Alfresco-style URLs without doubled-slash (040 Phase 1)`.

## Fase 2: docs de config + CHANGELOG 0.43.0 + smoke + FF

- [ ] 2.1 La sección `cmis` de
      `scripts/staging/config-staging.yaml.template` explica la
      distinción Alfresco vs IBM CM.
- [ ] 2.2 El Paso 4 de `docs/how-to/local-staging-simulation.md`
      usa `repo_id: ""`.
- [ ] 2.3 `docs/how-to/cmis-target-preflight.md` nota la
      convención de URL.
- [ ] 2.4 Entrada `CHANGELOG.md [0.43.0]`.
- [ ] 2.5 Tilde de la fila de feature en el README.
- [ ] 2.6 `pyproject.toml` 0.42.0 → 0.43.0.
- [ ] 2.7 Smoke: `cmcourier doctor --check cm-targets` PASSes
      contra `testserver:8080`.
- [ ] 2.8 Suite completa + `mypy` + `ruff` limpios.
- [ ] 2.9 Commit
      `docs(040): config doc updates + CHANGELOG 0.43.0 + version bump (040 Phase 2)`.
- [ ] 2.10 FF a main.
