# 039 — Plan

Tres fases, ~4-5h en total. RED→GREEN por fase, commit por fase,
FF en el último commit.

## Fase 1 — Servicio generador + subcomando CLI (~2.5h)

### Archivos

- `src/cmcourier/services/mock/rvabrep_generator.py` (nuevo)
  - Dataclass frozen `RvabrepGenSpec` — rows / seed / output /
    idrvi_pool / image_mix / date range / clients / delete_rate /
    cif_rate. Todo escalar; el pool de IDRVI es una tupla de
    strings ya sorteados desde el CSV fuente por el llamador.
  - Función `generate_rvabrep(spec, out_path)` — abre el path de
    salida para escritura, fluye filas vía `csv.writer` como
    `streaming` para que la memoria quede acotada incluso para
    `rows=1_000_000`. Devuelve el conteo de filas escritas.
  - Helpers internos: `_pick_idrvi`, `_pick_image_type`,
    `_pick_creation_date`, `_pick_last_view_date`,
    `_pick_total_pages`, `_pick_file_name`, `_pick_image_path`,
    `_pick_txn_num`, `_pick_client`, `_pick_cif`. Cada uno toma la
    instancia compartida `random.Random`.
  - `_validate_row(row, spec, idx)` lanza `ConfigurationError`
    con el índice de fila cuando falla un invariante. Corre cada
    fila antes de escribir.
- `src/cmcourier/cli/commands/mock.py` (editar)
  - Agregar el subcomando `rvabrep` al grupo `mock` existente.
  - Las opciones Click coinciden con la superficie CLI de la spec.
  - El comando construye un `RvabrepGenSpec` desde los flags, lee
    el CSV `--idrvi-source` (por defecto
    `docs/samples/csv/MapeoRVI_CM.csv`) vía `TabularDataSource`,
    descarta blancos + deduplica IDRVIs, toma el top `--idrvi-top`
    por orden lexicográfico (determinista), y llama a
    `generate_rvabrep`.
  - Al éxito, imprime un resumen de una línea
    `Wrote {rows} rows to {output} (image_mix={...}, idrvis={N}, seed={S}).`

### Tests

- `tests/unit/services/mock/test_rvabrep_generator.py` (nuevo)
  - `test_deterministic_with_same_seed`: dos corridas con la
    misma semilla → mismos bytes. Distinta semilla → bytes
    distintos.
  - `test_row_count_matches_spec`: `spec.rows = N` → la salida
    tiene N filas de datos + 1 encabezado.
  - `test_txn_num_unique`: corrida de 5000 filas, todos los
    `txn_num` distintos.
  - `test_image_mix_within_tolerance`: corrida de 5000 filas,
    proporciones observadas dentro de ±2% de la mezcla
    configurada.
  - `test_idrvi_pool_respected`: cada `index7` de salida está en
    el pool dado.
  - `test_pdf_rows_have_pdf_extension_and_one_page`: cada fila
    con `image_type=O` tiene `file_name.endswith(".PDF")` y
    `total_pages == 1`.
  - `test_paged_rows_have_numeric_extension`: cada fila `B` o `C`
    tiene `file_name` terminando en una extensión numérica.
  - `test_creation_date_in_range`: cada CYYMMDD es parseable y
    cae en `[date_from, date_to]`.
  - `test_last_view_zero_or_after_creation`: cuando
    `last_view_date != "0"`, parsea y es ≥ `creation_date`.
  - `test_invariant_failure_raises`: forzar a una fila a violar
    (vía monkeypatch) lanza `ConfigurationError` antes de
    escribir.

### Commit

```
feat(services,cli): cmcourier mock rvabrep — synthetic RVABREP CSV generator (039 Phase 1)
```

## Fase 2 — Test de integración + smoke contra el mock generate existente (~1h)

### Archivos

- `tests/integration/cli/test_mock_rvabrep.py` (nuevo)
  - Test end-to-end con `CliRunner`: `mock rvabrep --rows 100
    --output {tmp}/r.csv --seed 100 --idrvi-source
    tests/fixtures/services/modelo_documental.csv`.
  - Lee el CSV de vuelta a través de `TabularDataSource` +
    `IndexingService` y verifica que 100 documentos materialicen
    como instancias `RVABREPDocument`.
  - Cruza referencias contra el fixture de mapeo consolidado:
    cada `index7` se une contra al menos una fila del modelo
    documental.
  - Encadena en `cmcourier mock generate --rvabrep-csv {tmp}/r.csv
    --output-root {tmp}/files` con bordes de tamaño pequeños y
    verifica que 100 archivos físicos materialicen.

### Tests

- Correr la suite completa. Los tests existentes de mock quedan
  intactos.

### Commit

```
test(integration): rvabrep generator end-to-end + chained mock generate (039 Phase 2)
```

## Fase 3 — Docs + CHANGELOG 0.42.0 + version bump + FF (~30min)

### Archivos

- `docs/how-to/mock-rvabrep-generator.md` (nuevo) — `runbook` del
  operador:
  - Cuándo usar este comando.
  - Los flags, con ejemplos para escalas de 1k / 50k / 1M corridas.
  - Cómo encadenar en `mock generate`.
  - La dependencia implícita sobre `--idrvi-source` y qué pasa
    cuando la fuente tiene menos de `--idrvi-top` valores
    distintos.
  - Garantía de determinismo y cómo interactúan las semillas con
    el generador de archivos materializados (las semillas
    distintas para los dos comandos son independientes — el
    contenido del archivo está keado en `txn_num` + índice de
    página, no en el orden de fila).
- `scripts/staging/README.md` — agregar una §X "Generando un
  RVABREP sintético" apuntando al nuevo how-to.
- `CHANGELOG.md` — entrada `[0.42.0]`. Una única sección Added.
- `README.md` — tildar la fila de feature.
- Bump de versión en `pyproject.toml` a `0.42.0`.

### Tests

- Suite completa en verde.
- `mypy --strict src/cmcourier/{domain,services,orchestrators}`
  limpio.
- `ruff check` + `ruff format --check` limpios.
- Smoke a 50k: `cmcourier mock rvabrep --rows 50000 --output
  /tmp/r50k.csv --seed 50000` se completa en < 5s y la salida
  pasa un linter de CSV rápido (conteo de columnas, match de
  encabezado, parseable por fila).

### Commit

```
docs(039): mock-rvabrep how-to + CHANGELOG 0.42.0 + version bump (039 Phase 3)
```

### Merge FF a main. La rama queda (el operador la elimina cuando esté listo).
