# 076 — Tasks

## Fase 1 — Spec

- [x] 1.1 `specs/076-multipart-encoder-streaming-uploads/spec.md`
- [x] 1.2 `specs/076-multipart-encoder-streaming-uploads/plan.md`
- [x] 1.3 `specs/076-multipart-encoder-streaming-uploads/tasks.md`

## Fase 2 — Implementación

- [ ] 2.1 `pyproject.toml` agrega `requests-toolbelt>=1.0,<2.0`.
- [ ] 2.2 `src/cmcourier/adapters/upload/cmis_uploader.py`:
        importar `MultipartEncoder`.
- [ ] 2.3 Reemplazar el `httpx.Client.post(data=..., files=...)`
        por `MultipartEncoder` + `content=` + Content-Type header.
- [ ] 2.4 Verificar sintaxis + mypy.

## Fase 3 — Tests

- [ ] 3.1 Crear `tests/unit/adapters/upload/test_multipart_encoder.py`
        con los 3 tests del plan.
- [ ] 3.2 `pytest -m unit -k multipart` pasa.
- [ ] 3.3 Suite completa: `pytest -m unit` sin regresiones.

## Fase 4 — CHANGELOG + bump

- [ ] 4.1 `CHANGELOG.md` entry `[0.78.0]`.
- [ ] 4.2 `pyproject.toml` `0.77.0` → `0.78.0`.
- [ ] 4.3 `pip install -e ".[dev]"` para traer la nueva dep
        (no `--no-deps`).
- [ ] 4.4 `cmcourier --version` → `0.78.0`.

## Fase 5 — Commits + push

- [ ] 5.1 `feat: add 076 spec, plan, tasks`
- [ ] 5.2 `fix(upload): use MultipartEncoder for true streaming uploads to CMIS (076)`
- [ ] 5.3 `test: cover MultipartEncoder body assembly (076)`
- [ ] 5.4 `docs(076): CHANGELOG 0.78.0 + version bump`
- [ ] 5.5 `git push origin main`
