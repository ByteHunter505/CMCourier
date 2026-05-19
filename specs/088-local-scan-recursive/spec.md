# 088 — `local_scan` con flag `recursive`

## Por qué

El operador descubrió que el modo `local_scan` solo lista el
**directorio raíz** del `scan_path` — los archivos bajo cualquier
subdirectorio se ignoran silenciosamente. El árbol natural del RVI
es `<source_root>/<ABAICD>/<ABAJCD>/file.PDF`, así que apuntar
`scan_path` a un raíz alto no procesaba nada.

Pre-088:

```python
for entry in self._scan_path.iterdir():       # ← solo primer nivel
    if not entry.is_file() or not _is_trigger_filename(entry.name):
        continue
```

Workaround pre-088: aplanar manualmente con `Copy-Item -Recurse` o
hardlinks, duplicando entradas de directorio. Frágil con filenames
colisionantes entre subdirs.

## Qué

### Cambios

1. **`LocalScanTriggerConfig.recursive: bool = False`** (schema):
   nuevo flag opt-in. Default `False` preserva el contrato pre-088.

2. **`LocalScanTriggerStrategy.__init__`**: nuevo parámetro
   `recursive: bool = False`. Almacenado como `_recursive`.

3. **`LocalScanTriggerStrategy.acquire`**: el iterador cambia
   dinámicamente —

   ```python
   entries = (
       self._scan_path.rglob("*") if self._recursive
       else self._scan_path.iterdir()
   )
   for entry in entries:
       if not entry.is_file() or not _is_trigger_filename(entry.name):
           continue
       ...
   ```

   Los filtros de filename (`*.PDF` y `*.001`) y el lookup contra
   RVABREP no se tocan — solo cambia la fuente de paths.

4. **`wiring.py`**: pasa `recursive=trigger_cfg.recursive` al
   constructor de la strategy.

### Uso

```yaml
trigger:
  kind: local_scan
  scan_path: C:\rvi-sources              # raíz del árbol original
  recursive: true                        # ← descenso por todos los subdirs
```

Con la spec activa, el operador apunta directo al raíz del RVI:

```
C:\rvi-sources\
  ├── 042\
  │   ├── 0526\
  │   │   ├── DOC1.PDF              ← procesado
  │   │   └── DOC2.001              ← procesado
  │   └── 0527\
  │       └── DOC3.PDF              ← procesado
  └── 100\
      └── 0001\
          └── DOC4.PDF              ← procesado
```

Sin recursivo (default), solo procesaría archivos directamente en
`C:\rvi-sources\` (típicamente ninguno).

### Tests

* `tests/unit/services/test_local_scan_recursive.py`:
  - default es no-recursivo (regresión pre-088)
  - `recursive=True` cubre todos los niveles
  - filtros de filename se preservan recursivamente
  - `LocalScanTriggerConfig` default y opt-in

## Criterios de aceptación

1. Sin override en YAML, `recursive=False` y el comportamiento es
   byte-idéntico al pre-088 (regresión-safe).
2. Con `recursive: true`, archivos en cualquier profundidad bajo
   `scan_path` se descubren si pasan el filtro de filename.
3. `*.PDF` y `*.001` siguen siendo los únicos triggers válidos,
   recursivo o no.
4. `pytest -m unit` pasa.

## Riesgos

* **Backward-compat total**. Configs pre-088 cargan idénticamente.
  Solo el operador que opta-in cambia el iterador.
* **Symlinks**: `Path.rglob` en Python 3.11/3.12 sigue symlinks por
  default. Si el `scan_path` tiene symlinks circulares, el motor
  podría loopear. Edge case raro en ambientes Windows productivos —
  documentado pero no mitigado en 088. Si surge en prod, se agrega
  un `follow_symlinks: false` o se hace `rglob` con `walk()`.
* **Performance**: `rglob("*")` itera todo el árbol antes de
  filtrar. Para árboles muy grandes (millones de entries) puede ser
  lento solo listar. Mitigación: el operador usa `as400` trigger
  con un `query` filtrado para batches enormes.

## Notas

- No se cambia el algoritmo de matching contra RVABREP — sigue
  siendo un `get_by_fields` por filename. Si dos archivos
  homónimos están en distintas subcarpetas, ambos disparan
  triggers (potencialmente la misma fila RVABREP × 2). Edge case
  poco probable porque RVABREP indexa por filename físico único.
- Recordatorio operativo: en Windows el iter de Path es
  case-insensitive a nivel filesystem (NTFS) pero el match contra
  RVABREP es case-sensitive a nivel DB. Si tu RVABREP tiene
  `ABAJCD='DOC123.PDF'` y el archivo físico es `doc123.pdf`, el
  matching falla.
