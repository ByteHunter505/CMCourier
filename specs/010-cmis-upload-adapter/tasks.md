# Tasks — 010-cmis-upload-adapter

**Status**: Draft
**Spec**: `specs/010-cmis-upload-adapter/spec.md`
**Plan**: `specs/010-cmis-upload-adapter/plan.md`

---

## Phase 1 — Dev dependency

- [ ] **1.1** Add `"responses>=0.25,<1.0"` to `pyproject.toml` under `[project.optional-dependencies].dev`.
- [ ] **1.2** `pip install -e .[dev]` (in the venv) to fetch `responses`. Verify with `python -c "import responses; print(responses.__version__)"`.

---

## Phase 2 — Tests RED

- [ ] **2.1 (R)** Create `tests/integration/adapters/test_cmis_uploader.py`:
  - Module docstring, `pytestmark = pytest.mark.integration`.
  - Imports from `cmcourier.adapters.upload.cmis_uploader` (yet-to-exist).
  - Imports of `responses`, `requests`, `pytest`.
  - `_make_config(**overrides)` factory with `retry_base_delay_s=0.0`.
  - `_make_staged(tmp_path, *, size_bytes=1024)` writing a synthetic PDF.
  - `_BASE_URL = "http://cmis.example.test:9080/opencmcmis/browser"`,
    `_REPO_ID = "$x!testrepo"`.
- [ ] **2.2 (R)** Write the 9 test groups per plan §5.2 (~26 tests):
  - `TestCmisConfig` (2): default field values; `frozen` (assignment raises).
  - `TestWarmup` (3): lazy (no calls on construction), 1 GET on first state-changing call, 5xx during warmup raises `CMISServerError`.
  - `TestTestConnection` (3): parses repository info; missing keys → ""; 4xx raises `CMISClientError`.
  - `TestEnsureFolder` (5): skips `$type` segments, recursive (3 segments → 3 POSTs), cache prevents re-POST on second call, HTTP 409 = success, cached after 409.
  - `TestUploadHappyPath` (4): succinct properties path, standard properties fallback, `id` fallback, `Content-Type` header starts with `multipart/form-data; boundary=`.
  - `TestUploadRetry` (4): 5xx → backoff → success (3 calls), 4xx → fail-fast (1 call + raise), 401 → re-warmup + retry (1 extra GET + 2 POSTs), retry budget exhausted → `RetriesExhaustedError`.
  - `TestUploadWindows10053` (1): connection error containing `"10053"` doubles sleep delay; ERROR log emitted.
  - `TestBandwidthLimiter` (3): throttle 1 MB at 0.5 MB/s ≈ 2 s (±20%), `mbps=0` passthrough, passthrough methods (`seek/tell/close`).
  - `TestLoggingDiscipline` (1): retry log contains `txn_num` + `attempt`; never logs property values from the upload's `properties` dict (assertion on `caplog.records`).
- [ ] **2.3 (R)** Tests that exercise retry MUST `monkeypatch.setattr` `time.sleep` inside the cmis_uploader module to a no-op. The `TestBandwidthLimiter` test does NOT monkey-patch.
- [ ] **2.4 (R)** Run `pytest tests/integration/adapters/test_cmis_uploader.py -v`. Confirm collection ImportError.

---

## Phase 3 — Implementation GREEN

- [ ] **3.1 (G)** Create `src/cmcourier/adapters/upload/cmis_uploader.py` with module docstring, `__all__`, imports (`time`, `logging`, `dataclasses.dataclass`, `collections.abc.Mapping`, `pathlib.Path`, `requests`, `requests.exceptions.ConnectionError`, `requests_toolbelt.MultipartEncoder`), constants (`_SYSTEM_FOLDER_PREFIX`, `_WINDOWS_ABORT_MARKER`, `_MAX_BACKOFF_S`, `_RESPONSE_BODY_TRUNCATION`), logger.
- [ ] **3.2 (G)** Implement `CmisConfig` (frozen+slots) per plan §3.1.
- [ ] **3.3 (G)** Implement `BandwidthLimiter` per plan §4.7, including the passthrough methods and the `_enabled` short-circuit.
- [ ] **3.4 (G)** Implement `CmisUploader.__init__(config)`: store config, create `requests.Session` with auth + verify, initialize `_folder_cache: set[str] = set()`, `_warm: bool = False`.
- [ ] **3.5 (G)** Implement `_warmup_session()` per plan §4.1.
- [ ] **3.6 (G)** Implement `test_connection()` calling `_warmup_session` and parsing the repository info JSON.
- [ ] **3.7 (G)** Implement `_post_with_retries` per plan §4.2. Keep ≤ 50 lines; extract `_backoff_sleep(attempt, doubled)` if needed.
- [ ] **3.8 (G)** Implement `_create_folder_segment` per plan §4.3 with the 409-as-success branch.
- [ ] **3.9 (G)** Implement `ensure_folder` per plan §4.3 including system-folder skip + cache.
- [ ] **3.10 (G)** Implement `_build_multipart_for_upload` per plan §4.5.
- [ ] **3.11 (G)** Implement `_parse_object_id` per plan §4.6.
- [ ] **3.12 (G)** Implement `upload` per plan §4.4 (calls `ensure_folder` first, then `_build_multipart_for_upload`, then `_post_with_retries`, then `_parse_object_id`).
- [ ] **3.13 (G)** Update `src/cmcourier/adapters/upload/__init__.py` to re-export `CmisConfig`, `BandwidthLimiter`, `CmisUploader`.
- [ ] **3.14 (G)** Run `pytest tests/integration/adapters/test_cmis_uploader.py -v`. Iterate until all green.
- [ ] **3.15 (Rf)** Refactor for clarity. Verify every method ≤ 50 lines.

---

## Phase 4 — Verification

- [ ] **4.1** `ruff check src/ tests/` — clean.
- [ ] **4.2** `ruff format --check src/ tests/` — clean (or apply).
- [ ] **4.3** `mypy src/cmcourier/` — clean.
- [ ] **4.4** `pytest --cov=src/cmcourier --cov-report=term-missing` — coverage on `adapters/upload/cmis_uploader.py` ≥ 85%, total ≥ 80%.
- [ ] **4.5** `pre-commit run --all-files` — clean.

---

## Phase 5 — Docs + commit + merge FF

- [ ] **5.1** Update `CHANGELOG.md`:
  - "Planned for next release" → MVP orchestrator wiring S0..S6 (all real adapters now).
  - Add `[0.12.0] — 2026-05-10` entry: Added / Changed / Verification / Rationale.
- [ ] **5.2** Update `README.md` Status checklist: tick "Tenth change: CmisUploader (S5)".
- [ ] **5.3** PII grep on new files (no `JUANPEREZ` / `123456` / etc. — should use `TESTUSER001` / `000000` placeholders).
- [ ] **5.4** Stage all files. Expected status:
  ```
  modified: CHANGELOG.md
  modified: README.md
  modified: pyproject.toml
  modified: src/cmcourier/adapters/upload/__init__.py
  added:    src/cmcourier/adapters/upload/cmis_uploader.py
  added:    tests/integration/adapters/test_cmis_uploader.py
  added:    specs/010-cmis-upload-adapter/{spec,plan,tasks}.md
  ```
- [ ] **5.5** Commit `feat(adapters): add CmisUploader for stage S5` (template per spec §7 of the commit message body).
- [ ] **5.6** `git checkout main && git merge --ff-only feat/010-cmis-upload-adapter && git branch -d feat/010-cmis-upload-adapter`.

---

## Verification mapping (REQ → tasks)

| Spec REQ | Tasks |
|----------|-------|
| REQ-001..002 (config) | 3.2 + TestCmisConfig (2.2) |
| REQ-003..004 (construction) | 3.4 + TestWarmup |
| REQ-005..006 (warmup) | 3.5 + TestWarmup + TestUploadRetry 401 |
| REQ-007..008 (test_connection) | 3.6 + TestTestConnection |
| REQ-009..012 (ensure_folder) | 3.8, 3.9 + TestEnsureFolder |
| REQ-013..016 (upload) | 3.10, 3.11, 3.12 + TestUploadHappyPath |
| REQ-017..021 (retry policy) | 3.7 + TestUploadRetry + TestUploadWindows10053 |
| REQ-022..024 (BandwidthLimiter) | 3.3 + TestBandwidthLimiter |
| REQ-025 (logging) | 3.7 + TestLoggingDiscipline |
| NFR-002 (coverage) | 4.4 |
| NFR-003 (50-line cap) | 3.15 |

---

## Estimated effort

- Phase 1 (dev dep): 5 min
- Phase 2 (RED): 120 min
- Phase 3 (GREEN): 100 min
- Phase 4 (verification): 20 min
- Phase 5 (docs + commit + merge): 15 min
- **Total**: ~4 h 20 min

---

## Notes for the implementor

- The retry loop is the riskiest method. Keep it readable; if `_post_with_retries` exceeds 45 lines, extract `_should_retry`, `_attempt_post`, etc.
- `MultipartEncoder` content type includes a `boundary=...` suffix; tests use `startswith` not equality.
- `responses` does NOT consume `MultipartEncoder` streams for body capture by default. Use `responses.add_callback` for streaming tests; for retry/error tests, `responses.add(method, url, status=...)` is enough.
- `requests.exceptions.ConnectionError` extends `OSError`; the `_post_with_retries` `except ConnectionError` clause should import the exception explicitly to avoid catching plain `ConnectionError` (`builtins.ConnectionError`).
- `time.sleep` is monkey-patched IN the `cmis_uploader` module's namespace, not globally — that's why the module imports `time` at top-level rather than `from time import sleep`.
- The PII grep at 5.3 must verify NEITHER the spec/plan/tasks NOR the test code includes real CIFs/names. Stick to `TESTUSER001` / `000000` / `999999`.
- `responses` is a dev-only dep; do NOT add to `[project].dependencies`.
