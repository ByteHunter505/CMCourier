# 040 — Plan

Two phases, ~1.5h total.

## Phase 1 — `_service_url` helper + 6 call-site swaps + tests (~1h)

### Files

- `src/cmcourier/adapters/upload/cmis_uploader.py`
  - Add `_service_url(suffix: str = "") -> str` method.
  - Replace 6 inline f-string URL builds:
    - `_warmup_session` line ~388: `f"{base}/{repo_id}"` → `self._service_url()`.
    - `test_connection` (if it shares the warmup pattern).
    - `get_type_definition`: `f"{base}/{repo_id}"` → `self._service_url()`.
    - `verify_folder_exists` line ~315: `f"{base}/{repo_id}/root/{normalized}"` → `self._service_url(f"root/{normalized}")`.
    - `upload` line ~365: same.
    - Any other future `_check_*` paths (none today).
- `tests/integration/adapters/test_cmis_uploader.py`
  - New `TestServiceUrl` class with 4 unit-ish tests:
    - `_service_url() == base_url` when `repo_id=""`.
    - `_service_url() == f"{base_url}/{repo_id}"` when `repo_id` set.
    - `_service_url("root/X") == f"{base_url}/root/X"` when empty.
    - `_service_url("root/X") == f"{base_url}/{repo_id}/root/X"` when set.
  - New `TestAlfrescoStyleUrls` integration class with 3 cases
    using ``responses``:
    - `verify_folder_exists` with `repo_id=""` issues a GET to
      `.../browser/root/<path>` and accepts a folder JSON.
    - `upload` with `repo_id=""` POSTs to `.../browser/root/<path>`.
    - `get_type_definition` with `repo_id=""` queries `.../browser`
      (no path-encoded id).
  - Existing IBM-CM-style tests (with `repo_id` set) keep passing
    unchanged — the helper is a pure refactor for those.

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

## Phase 2 — Config docs + CHANGELOG 0.43.0 + smoke + FF (~30min)

### Files

- `scripts/staging/config-staging.yaml.template`
  - Add a comment block on the `cmis` section explaining the
    Alfresco vs IBM CM distinction:
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
  - Step 4 reflects `repo_id: ""` for the staging Alfresco config.
- `docs/how-to/cmis-target-preflight.md`
  - Add a note in §5 (operational discipline) about the URL
    convention.
- `CHANGELOG.md`
  - `[0.43.0]` — Added: Alfresco URL compatibility via
    `repo_id=""`. Changed: `CmisConfig.repo_id` semantics
    (empty was undefined → now explicit "no repo id in path").
- `README.md`
  - Tick the feature row.
- `pyproject.toml`
  - Version bump 0.42.0 → 0.43.0.

### Smoke

After commit:

```bash
.venv/bin/cmcourier doctor --config sample/config-staging.yaml --check cm-targets
```

Expect 3 PASS (cm_type_alignment, cmis_folders_exist,
cmis_properties_alignment) against `testserver:8080`.

### Commit

```
docs(040): config doc updates + CHANGELOG 0.43.0 + version bump (040 Phase 2)
```

### FF to main, branch stays.
