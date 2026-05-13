# 040 — Tasks

## Phase 1: helper + URL swaps + tests

- [ ] 1.1 Add `_service_url(suffix: str = "") -> str` method to
      `CmisUploader`.
- [ ] 1.2 `_warmup_session` URL → `self._service_url()`.
- [ ] 1.3 `get_type_definition` URL → `self._service_url()`.
- [ ] 1.4 `verify_folder_exists` URL →
      `self._service_url(f"root/{normalized}")`.
- [ ] 1.5 `upload` URL → `self._service_url(f"root/{normalized}")`.
- [ ] 1.6 `test_connection` (if it shares the warmup pattern) →
      same.
- [ ] 1.7 Unit tests for `_service_url` (4 cases).
- [ ] 1.8 Integration tests for Alfresco-style URLs (3 cases).
- [ ] 1.9 Existing IBM-CM-style tests pass unchanged.
- [ ] 1.10 mypy + ruff clean.
- [ ] 1.11 Commit
      `fix(uploader): repo_id='' emits Alfresco-style URLs without doubled-slash (040 Phase 1)`.

## Phase 2: config docs + CHANGELOG 0.43.0 + smoke + FF

- [ ] 2.1 `scripts/staging/config-staging.yaml.template` cmis
      section explains Alfresco vs IBM CM distinction.
- [ ] 2.2 `docs/how-to/local-staging-simulation.md` Step 4 uses
      `repo_id: ""`.
- [ ] 2.3 `docs/how-to/cmis-target-preflight.md` notes the URL
      convention.
- [ ] 2.4 `CHANGELOG.md [0.43.0]` entry.
- [ ] 2.5 `README.md` feature row tick.
- [ ] 2.6 `pyproject.toml` 0.42.0 → 0.43.0.
- [ ] 2.7 Smoke: `cmcourier doctor --check cm-targets` PASSes
      against testserver:8080.
- [ ] 2.8 Full suite + mypy + ruff clean.
- [ ] 2.9 Commit
      `docs(040): config doc updates + CHANGELOG 0.43.0 + version bump (040 Phase 2)`.
- [ ] 2.10 FF to main.
