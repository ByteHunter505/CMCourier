# 031 — Tasks

## Phase 1 — Sizing parser
- [ ] T1.1 — Create `cmcourier/services/mock/__init__.py` + `tests/unit/services/mock/__init__.py` markers.
- [ ] T1.2 — Write `tests/unit/services/mock/test_sizing.py` (≥6 tests, REQ-005) — RED.
- [ ] T1.3 — Implement `cmcourier/services/mock/sizing.py::parse_size` (binary units, suffix-optional) — GREEN.

## Phase 2 — Content writer
- [ ] T2.1 — Define `FilePlan` in `cmcourier/services/mock/types.py` (frozen, slots, REQ-006).
- [ ] T2.2 — Write `tests/unit/services/mock/test_content.py` (≥8 tests, REQ-026): pdf pages, pdf re-openable, tiff LZW, jpeg openable, size band, determinism, skip-if-exists, force — RED.
- [ ] T2.3 — Implement `MockContentWriter` in `cmcourier/services/mock/content.py` (PDF/TIFF/JPEG branches + 5-attempt size-targeting loop) — GREEN.
- [ ] T2.4 — `pytest tests/unit/services/mock/` green (sizing + content).

## Phase 3 — Planner
- [ ] T3.1 — Write `tests/unit/services/mock/test_planner.py` (≥8 tests, REQ-016): pdf dispatch, image dispatch (single-page `.001`), deleted skip, include-deleted opt-in, system filter, doctype filter + limit, dedup conflict warn, path norm Windows, unknown image_type raise — RED.
- [ ] T3.2 — Implement `PlannerFilters`, `SizeBounds`, `normalize_image_path`, `plan_files` in `cmcourier/services/mock/planner.py` — GREEN.
- [ ] T3.3 — `pytest tests/unit/services/mock/` green (all 3 modules).

## Phase 4 — CLI + wiring
- [ ] T4.1 — Write `tests/integration/cli/test_mock_generate.py` (4 cases, REQ-034): happy path decodable, dry-run no-write, seed determinism, validation error — RED.
- [ ] T4.2 — Implement `cmcourier/cli/commands/mock.py` (Click group + `generate` + option parsing + source dispatch + error mapping) — GREEN.
- [ ] T4.3 — Wire into `cmcourier/cli/app.py`: import `mock_group` + `main.add_command(mock_group)`.
- [ ] T4.4 — `CHANGELOG.md` `[Unreleased]` entry under "Tooling" pointing to `specs/031-mock-file-generator/spec.md`.
- [ ] T4.5 — Full gate: `ruff check && ruff format --check && mypy src/cmcourier/ && pytest && pre-commit run --all-files`.
- [ ] T4.6 — Manual smoke: `cmcourier mock generate --rvabrep-csv <fixture> --root /tmp/m031 --pdf-min 20kb --pdf-max 200kb --img-min 5kb --img-max 50kb --seed 1`; verify decodable output + summary line.
- [ ] T4.7 — FF merge after `sdd-verify` clean.
