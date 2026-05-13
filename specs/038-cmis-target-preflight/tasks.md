# 038 — Tasks

## Phase 1: CMISFolder + CMISPropertyId columns through the stack

- [ ] 1.1 `MappingConfig.rvi_cm_cmis_folder_column: str = "CMISFolder"`
      + `MappingConfig.metadatos_cmis_property_id_column: str = "CMISPropertyId"`
      in `config/schema.py`.
- [ ] 1.2 `CMMapping.cmis_folder: str | None = None` in
      `domain/models.py`.
- [ ] 1.3 `MappingService` reads `CMISFolder` from the configured
      column, populates `cmis_folder`. Missing column → None;
      empty cell → None.
- [ ] 1.4 `MetadataService.resolve_properties` keys results by
      `CMISPropertyId` when populated, friendly name otherwise.
      Backward-compat when column is absent.
- [ ] 1.5 `StagedPipeline` S5 URL builder consumes
      `mapping.cmis_folder` (no folder-creation call here yet —
      phase 2).
- [ ] 1.6 Unit tests: schema defaults; mapping CSV with /
      without / empty column; metadata column populated /
      empty / missing.
- [ ] 1.7 Integration test: S5 URL contains `/$type/X` when
      `cmis_folder="$type/X"`.
- [ ] 1.8 Full suite + mypy + ruff clean.
- [ ] 1.9 Commit `feat(config,mapping,metadata,pipeline): CMISFolder + CMISPropertyId columns (038 Phase 1)`.

## Phase 2: verify_folder_exists + remove creation surface

- [ ] 2.1 Rename `IUploader.ensure_folder` → `verify_folder_exists`
      in `domain/ports.py`. Return type `bool`. Update docstring.
- [ ] 2.2 Rewrite the method in `CmisUploader` as a read-only
      `GET ?cmisselector=object` probe; return True / False per
      the spec's response map; raise on 401/connectivity.
- [ ] 2.3 Delete `CmisUploader._create_folder_segment`.
- [ ] 2.4 Remove the `uploader.ensure_folder(...)` call from
      `orchestrators/staged.py` S5.
- [ ] 2.5 Update existing uploader tests:
      `verify_folder_exists_returns_true_for_existing`,
      `_returns_false_on_404`,
      `_returns_false_when_not_folder`.
- [ ] 2.6 Delete tests referencing `_create_folder_segment`.
- [ ] 2.7 New pipeline test: 10-doc happy run records zero
      `verify_folder_exists` calls.
- [ ] 2.8 Full suite + mypy + ruff clean.
- [ ] 2.9 Commit `refactor(uploader,pipeline): verify_folder_exists (read-only) + remove S5 folder-creation surface (038 Phase 2)`.

## Phase 3: cmis_folders_exist + cmis_properties_alignment + cm-targets

- [ ] 3.1 `_check_cmis_folders_exist` in `cli/doctor.py`:
      PASS / FAIL (list missing) / SKIP (no cmis_folder).
- [ ] 3.2 `_check_cmis_properties_alignment` in `cli/doctor.py`:
      memoized per-type `get_type_definition`; PASS / FAIL
      (grouped by type) / SKIP (no cmis_property_id).
- [ ] 3.3 `_CHECK_GROUPS["cm-targets"]` registered with all three
      checks; existing `cm-types` group preserved.
- [ ] 3.4 `run_doctor` invokes the new checks when the active
      group matches.
- [ ] 3.5 Unit tests in `tests/unit/cli/test_doctor.py`:
      PASS / FAIL / SKIP paths for both new checks;
      `cm-targets` membership.
- [ ] 3.6 New integration test
      `tests/integration/cli/test_doctor_cm_targets.py` with
      stub uploader returning deterministic responses.
- [ ] 3.7 Full suite + mypy + ruff clean.
- [ ] 3.8 Commit `feat(doctor): cmis_folders_exist + cmis_properties_alignment + cm-targets group (038 Phase 3)`.

## Phase 4: s5_upload_attempt + s5_upload_failed + unmask_pii

- [ ] 4.1 `ObservabilityConfig.unmask_pii: bool = Field(default=False)`
      in `config/schema.py`.
- [ ] 4.2 Audit `observability/pii.py` masking rules for the
      fields we emit; add `mask_dict(properties, unmask=False)`
      convenience.
- [ ] 4.3 `CmisUploader` emits `s5_upload_attempt` before each
      POST attempt with masked properties.
- [ ] 4.4 On non-201, emits `s5_upload_failed` extending the
      attempt event with `status_code`, truncated
      `response_body`, and `curl_equivalent`.
- [ ] 4.5 `curl_equivalent` honors `unmask_pii` (raw values
      when true, masked when false).
- [ ] 4.6 `cli/doctor.py` startup emits a WARNING line when
      `unmask_pii=True`.
- [ ] 4.7 Unit tests for `pii.mask_value` + `pii.mask_dict`.
- [ ] 4.8 Integration tests: 201 → 1 attempt event; 400 →
      attempt + failed; unmask_pii=true → raw values; doctor
      warning surfaces.
- [ ] 4.9 Full suite + mypy + ruff clean.
- [ ] 4.10 Commit `feat(observability,uploader): s5_upload_attempt + s5_upload_failed events + unmask_pii toggle (038 Phase 4)`.

## Phase 5: docs + CHANGELOG 0.41.0 + version bump + FF

- [ ] 5.1 `docs/how-to/cmis-target-preflight.md` operator runbook:
      filling the new CSV columns; running
      `doctor --check cm-targets`; reading
      `s5_upload_attempt` / `s5_upload_failed` from
      `metrics.jsonl`; unmask_pii usage and risks.
- [ ] 5.2 Append §X to `docs/how-to/validation-checklist.md`
      describing the cm-targets pre-flight step.
- [ ] 5.3 `scripts/staging/README.md` — add `bash register-model.sh`
      + manual folder pre-create + `doctor --check cm-targets`
      to the quick-start path.
- [ ] 5.4 `CHANGELOG.md [0.41.0]` entry — Added, Changed
      (BREAKING `IUploader.ensure_folder` → `verify_folder_exists`),
      Removed (`_create_folder_segment`, S5 auto-folder).
- [ ] 5.5 `README.md` — tick the feature row for cm-targets
      pre-flight.
- [ ] 5.6 `pyproject.toml` version → `0.41.0`.
- [ ] 5.7 Smoke run against staging Alfresco:
      pre-create folder + `register-model.sh` + `doctor --check
      cm-targets` PASS + 5-doc pipeline writes 5 attempt events.
- [ ] 5.8 Full suite + mypy + ruff clean.
- [ ] 5.9 Commit `docs(038): cmis-target-preflight how-to + CHANGELOG 0.41.0 + IUploader contract bump (038 Phase 5)`.
- [ ] 5.10 FF merge + branch delete.
