# 043 — Tasks

## Fase 1 — AutoTuneController.set_p95_provider

- [ ] 1.1 Método público ``set_p95_provider(provider)`` en
      ``AutoTuneController``. Swap atómico de atributo; sin reinicio
      de thread.
- [ ] 1.2 ``_tick`` lee ``self._p95_provider`` a través del
      atributo así que un swap toma efecto inmediato en el próximo
      tick.
- [ ] 1.3 Test unitario: swap a mitad de vida, próximo tick observa
      el valor de retorno del nuevo provider.
- [ ] 1.4 mypy + ruff limpios.
- [ ] 1.5 Commit
      ``feat(services): AutoTuneController.set_p95_provider swap hook (043 Phase 1)``.

## Fase 2 — multi-batch wirea la fuente de p95 del upload-recorder

- [ ] 2.1 ``MultiBatchOrchestrator._upload_p95_observer()`` lee
      desde ``self.upload_recorder()`` y devuelve
      ``current_stage_p95("S5")`` o ``0.0``.
- [ ] 2.2 ``_run_overlapped._upload_loop`` llama a
      ``controller.set_p95_provider(self._upload_p95_observer)``
      antes de ``controller.start()``.
- [ ] 2.3 Test unitario: con un ``p95_provider`` falso seteado en un
      controlador mockeado, el orchestrator lo sobrescribe al
      arrancar el solapamiento.
- [ ] 2.4 mypy + ruff limpios.
- [ ] 2.5 Commit
      ``fix(orchestrators): multi-batch AIMD reads p95 from upload-active recorder (043 Phase 2)``.

## Fase 3 — docs + CHANGELOG 0.46.0 + bump de versión + verify + FF

- [ ] 3.1 Entrada ``CHANGELOG.md [0.46.0]`` — Fixed (read path de
      p95 de AIMD), Changed (se agregó set_p95_provider).
- [ ] 3.2 ``pyproject.toml`` 0.45.0 → 0.46.0.
- [ ] 3.3 ``pip install -e . --no-deps`` — refrescar metadata.
- [ ] 3.4 ``cmcourier --version`` reporta 0.46.0.
- [ ] 3.5 Tick en fila de features de ``README.md``.
- [ ] 3.6 Re-correr §F.4 (``--total 200 --batches-in-flight 2``).
- [ ] 3.7 Grepear eventos ``auto_tune_decision``; assertear que al
      menos uno tiene ``p95_observed_ms > 0``.
- [ ] 3.8 Suite unitaria completa + ruff + mypy limpios.
- [ ] 3.9 Commit
      ``docs(043): CHANGELOG 0.46.0 + version bump + AIMD live re-verify (043 Phase 3)``.
- [ ] 3.10 FF a main.
