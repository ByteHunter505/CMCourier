# 035 — Tareas

## Fase 1: esquema + servicio + cableado

- [ ] 1.1 Agregar campos de modo dividido + `model_validator` a
      `config/schema.py::MappingConfig`. Tests:
      `tests/unit/config/test_schema.py` (5 nuevos casos).
- [ ] 1.2 Extender `services/mapping.py::MappingColumnsConfig` con
      nombres de columna del modo dividido + `col_required_marker`.
- [ ] 1.3 Extender `services/mapping.py::MappingService.__init__`
      con `metadata_source` opcional; implementar el cargador de
      modo dividido (`_load_split`). Tests:
      `tests/unit/services/test_mapping_split.py` (7 nuevos casos).
- [ ] 1.4 Agregar
      `build_mapping_service(MappingConfigModel) -> MappingService`
      en `config/wiring.py`. Tests:
      `tests/integration/config/test_wiring.py` (2 nuevos casos —
      uno por modo).
- [ ] 1.5 Migrar los cuatro puntos de llamada al helper:
      `config/wiring.py::wire_services_from_config`,
      `cli/doctor.py:421`, `cli/doctor.py:484`,
      `cli/commands/inspect.py:118`, `cli/commands/inspect.py:161`.
- [ ] 1.6 `uv run pytest -q tests/unit/config tests/unit/services tests/integration/config`
      en verde; suite completa en verde.
- [ ] 1.7 `uv run mypy src tests` + `uv run ruff check .` limpios.
- [ ] 1.8 Commit `feat(mapping,config): two-mode MappingConfig (...) (035 Phase 1)`.

## Fase 2: muestra + docs + CHANGELOG + FF

- [ ] 2.1 Agregar la columna `CMISType` (vacía) a
      `docs/samples/csv/MapeoRVI_CM.csv`.
- [ ] 2.2 Actualizar `docs/how-to/as400-sync.md`: eliminar la nota
      de limitación conocida de 035, agregar un recuadro breve del
      modo dividido apuntando a la guía de configuración.
- [ ] 2.3 Actualizar los ejemplos TOML de la guía de configuración
      (ambos modos).
- [ ] 2.4 `CHANGELOG.md`: agregar la sección `[0.36.0]` con la
      entrada de 035; mover 035 fuera de Unreleased.
- [ ] 2.5 Marcar 035 como SHIPPED en el doc del roadmap POST-MVP;
      tildar el checkbox del README si está presente.
- [ ] 2.6 Suite completa de pruebas en verde.
- [ ] 2.7 Commit `docs(035): sample CSV CMISType + ... (035 Phase 2)`.
- [ ] 2.8 Merge FF a `main`; eliminar la rama.
