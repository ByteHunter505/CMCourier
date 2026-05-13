# 040 — Alfresco URL compatibility (`repo_id=""` semantics)

## Why

The CmisUploader (010) was built against IBM Content Manager's
Browser Binding endpoint, which expects the repository id to appear
**inside the URL path** between the service URL and `/root/`:

```
http://ibm-cm:9080/.../cmis-browser/<repository_id>/root/<folder>
```

CMCourier emits exactly that shape: `f"{base_url}/{repo_id}/root/..."`.
Alfresco's CMIS Browser Binding 1.1, by contrast, **does not include
the repository id in the path** when `base_url` already terminates in
`.../browser`. The repository id is read from the JSON returned by
`repositoryInfo`, never echoed in the URL:

```
http://alfresco:8080/alfresco/api/-default-/public/cmis/versions/1.1/browser/root/<folder>
```

Today no config setting makes the adapter emit the Alfresco shape.
Setting `repo_id=""` does NOT work — the f-string emits a doubled
slash (`.../browser//root/<folder>`) which Alfresco rejects with
HTTP 405 "Unknown operation". Setting `repo_id="-default-"` reaches
the URL `.../browser/-default-/root/<folder>` which Alfresco also
rejects.

Operators who run the staging dry-run against the local Alfresco
container shipped under `scripts/staging/` therefore cannot exercise
the pipeline against it. The doctor cm-targets pre-flight FAILs
folder + type checks even when the underlying resources exist.

040 closes that gap with a minimal additive change: when `repo_id`
is empty, the adapter omits both the slash and the segment, emitting
`.../browser/root/<folder>` directly. IBM CM behavior is preserved
verbatim when `repo_id` is set (the historical default).

## What

### Adapter change

Add a single helper `CmisUploader._service_url(suffix: str = "") -> str`
that builds URLs in a way that respects `repo_id=""`:

```python
def _service_url(self, suffix: str = "") -> str:
    if self._cfg.repo_id:
        url = f"{self._cfg.base_url}/{self._cfg.repo_id}"
    else:
        url = self._cfg.base_url
    return f"{url}/{suffix}" if suffix else url
```

Replace every existing f-string URL build in `CmisUploader` that
hard-codes `f"{base}/{repo_id}"` or `f"{base}/{repo_id}/root/..."`
with a call to `self._service_url(...)`. The six call sites are:

- `_warmup_session`: `self._service_url()`
- `get_type_definition`: `self._service_url()`
- `verify_folder_exists`: `self._service_url(f"root/{normalized}")`
- `upload`: `self._service_url(f"root/{normalized}")`
- `test_connection`: same as `_warmup_session`
- (any future `_check_*` helper added by 038): same pattern

No public API change. No port change. `CmisConfig.repo_id` already
accepts any string, including `""`.

### Config schema

`CmisConfig.repo_id` becomes formally documented as "leave empty to
target a Browser-Binding service URL that already encodes the
repository id (Alfresco). Set to the IBM CM repository identifier
(`$x!icmnlsdb_cmis` typically) for IBM CM."

`scripts/staging/config-staging.yaml.template` is updated to show
both forms with a comment block explaining the Alfresco vs IBM CM
distinction.

### Default behavior

- `repo_id` set (any non-empty string) → identical URL shape to
  pre-040 behavior. IBM CM consumers see no change.
- `repo_id=""` → URLs lose the `/<repo_id>` segment entirely. The
  adapter still works for warmup, type-definition, folder
  verification, and upload — all against Alfresco's URL convention.

## Out of scope

- Switching the adapter's HTTP method semantics (Alfresco accepts
  the same multipart createDocument shape; only URL changes).
- Adapter rewrite for any other CMIS quirk (`cmisselector=object`
  works in Alfresco against folder paths, `=repositoryInfo` works
  at the service URL, etc.).
- Auto-detection of "is this Alfresco or IBM CM?" — out of scope
  forever; operator config is the single source of truth.

## Acceptance criteria

- `_service_url()` exists, returns the correct shape for both
  `repo_id=""` and `repo_id="something"`.
- Six URL build sites in CmisUploader use the helper.
- Unit tests for `_service_url` (4 cases: empty / set / with
  suffix / without suffix).
- Integration test against a fake Alfresco-style endpoint
  (responses lib, `repo_id=""`) verifies the URLs emitted contain
  `/browser/root/...` not `/browser//root/...`.
- The existing integration tests with `repo_id` set keep passing.
- `cmcourier doctor --check cm-targets` against the live staging
  Alfresco at `testserver:8080` PASSes (cm_type_alignment,
  cmis_folders_exist, cmis_properties_alignment) with
  `repo_id: ""` in the config.
- mypy + ruff clean.
- CHANGELOG `[0.43.0]` entry.

## Notes

This is a small, focused compatibility fix — single helper, six
edits, ~1h total including the spec. Worth being a formal spec
(040) rather than a chore commit because:

1. It changes the contract of `CmisConfig.repo_id` (empty was
   previously meaningless — now it has explicit semantics).
2. CHANGELOG needs to call out the new Alfresco support so
   operators know they can pivot the staging config.
3. Tests demand the convention be locked in — without coverage,
   the next adapter refactor could silently re-break Alfresco.
