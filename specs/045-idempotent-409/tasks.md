# 045 — Tasks

## Fase 1 — Recuperación de 409 en CmisUploader

- [ ] 1.1 Método privado ``_lookup_existing_object_id(folder_url, name)``
      — GET ``cmisselector=children``, devolver
      ``cmis:objectId`` del hijo que matchea o ``None``.
- [ ] 1.2 ``upload(...)`` extendido: en 409 del POST, correr el
      lookup; devolver el id recuperado en hit, re-raisear en miss.
- [ ] 1.3 Nuevos eventos estructurados
      ``s5_upload_409_recovery_attempt`` /
      ``s5_upload_409_recovered`` / ``s5_upload_409_recovery_failed``
      (agregados a ``JsonFormatter.ALLOWED_EXTRA_FIELDS`` si su
      payload incluye claves nuevas).
- [ ] 1.4 Test unitario: 409 + lookup hit → upload devuelve id recuperado.
- [ ] 1.5 Test unitario: 409 + lookup miss → re-raisea CMISClientError.
- [ ] 1.6 Test unitario: 200 en primer intento → lookup nunca invocado.
- [ ] 1.7 mypy + ruff limpios.
- [ ] 1.8 Commit
      ``fix(uploader): idempotent 409 recovery — lookup existing object on conflict (045 Phase 1)``.

## Fase 2 — docs + CHANGELOG 0.48.0 + bump de versión + re-verify en vivo + FF

- [ ] 2.1 ``CHANGELOG.md [0.48.0]`` — Fixed (idempotencia de
      `race condition` del kill), Added (helper de lookup + eventos).
- [ ] 2.2 ``pyproject.toml`` 0.47.0 → 0.48.0.
- [ ] 2.3 ``.venv/bin/pip install -e . --no-deps``.
- [ ] 2.4 ``cmcourier --version`` reporta 0.48.0.
- [ ] 2.5 Tick en fila de features de ``README.md``.
- [ ] 2.6 Re-verify en vivo: kill-mid-S5 + resume; assertear s5_failed=0.
- [ ] 2.7 Suite unitaria completa + ruff + mypy limpios.
- [ ] 2.8 Commit
      ``docs(045): CHANGELOG 0.48.0 + version bump + 409 idempotency live re-verify (045 Phase 2)``.
- [ ] 2.9 FF a main.
