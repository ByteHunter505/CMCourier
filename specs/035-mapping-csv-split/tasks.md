# 035 — Tasks

## Phase 1: schema + service + wiring

- [ ] 1.1 Add split-mode fields + `model_validator` to
      `config/schema.py::MappingConfig`. Tests: `tests/unit/config/test_schema.py`
      (5 new cases).
- [ ] 1.2 Extend `services/mapping.py::MappingColumnsConfig` with
      split-mode column names + `col_required_marker`.
- [ ] 1.3 Extend `services/mapping.py::MappingService.__init__` with
      optional `metadata_source`; implement split-mode loader
      (`_load_split`). Tests: `tests/unit/services/test_mapping_split.py`
      (7 new cases).
- [ ] 1.4 Add `build_mapping_service(MappingConfigModel) -> MappingService`
      in `config/wiring.py`. Tests:
      `tests/integration/config/test_wiring.py` (2 new cases — one per
      mode).
- [ ] 1.5 Switch four call sites to the helper:
      `config/wiring.py::wire_services_from_config`,
      `cli/doctor.py:421`, `cli/doctor.py:484`,
      `cli/commands/inspect.py:118`, `cli/commands/inspect.py:161`.
- [ ] 1.6 `uv run pytest -q tests/unit/config tests/unit/services tests/integration/config`
      green; full suite green.
- [ ] 1.7 `uv run mypy src tests` + `uv run ruff check .` clean.
- [ ] 1.8 Commit `feat(mapping,config): two-mode MappingConfig (...) (035 Phase 1)`.

## Phase 2: sample + docs + CHANGELOG + FF

- [ ] 2.1 Append `CMISType` column (empty) to
      `docs/samples/csv/MapeoRVI_CM.csv`.
- [ ] 2.2 Update `docs/how-to/as400-sync.md`: drop 035 known-limitation
      note, add brief split-mode callout pointing at the
      configuration guide.
- [ ] 2.3 Update configuration guide TOML examples (both modes).
- [ ] 2.4 `CHANGELOG.md`: add `[0.36.0]` section with 035 entry; move
      035 out of Unreleased.
- [ ] 2.5 Mark 035 SHIPPED in POST-MVP roadmap doc; tick README
      checkbox if present.
- [ ] 2.6 Full test suite green.
- [ ] 2.7 Commit `docs(035): sample CSV CMISType + ... (035 Phase 2)`.
- [ ] 2.8 FF merge to `main`; delete branch.
