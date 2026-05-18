# 085 — Cleanup de staged files post-S5_DONE

## Por qué

Descubierto en producción. El operador reportó: "los archivos no se
están borrando luego de que se cargan a CMIS". Verificación con `rg`:

```
rg "unlink|os.remove|rmtree" src/cmcourier --type py
```

**Resultado**: 0 matches en el orchestrator y en los adapters de
producción. Las únicas dos llamadas a `unlink` en `src/` están en
`cli/doctor.py` (un probe efímero del filesystem y el cleanup del
sample_dry_run).

Comportamiento pre-085:
1. S4 ensambla `temp_dir/{txn_num}.pdf` con `shutil.copy2` (PDF
   nativo) o `img2pdf` (TIFF/JPEG → PDF).
2. S5 sube el `StagedFile` a CMIS.
3. **El archivo en `temp_dir` queda en disco para siempre**. Ni
   post-S5_DONE, ni en cleanup de batch, ni en cleanup de pipeline.

Implicancia productiva: una migración de N documentos deja N PDFs
huérfanos en `temp_dir`. Un lote de 100k documentos × ~500KB ≈ 50GB
de basura acumulada. El operador tiene que limpiar manualmente.

## Qué

### Cambios

1. **`StagedPipeline.__init__`**: nuevo parámetro keyword-only
   `keep_staged_files: bool = False`. Default = borrar.

2. **`StagedPipeline._cleanup_staged_file`** (nuevo): borra
   `staged.path` con `unlink(missing_ok=True)`. Idempotente. Falla
   del unlink se loguea como warning pero NO propaga — un cleanup
   roto no debe revertir un S5_DONE legítimo ya persistido en
   tracking.

3. **Callsite**: después de `mark_uploaded` / `mark_stage_done`
   exitoso (línea 1170-1180 del orchestrator), antes de
   `_mark_completed(lane)`. NO se invoca en S5_FAILED — si hay
   retry, S4 regenera el staged desde source.

4. **`AssemblyConfig.keep_staged_files`** (schema): bool default
   `False`. El operador opta-out poniéndolo `true` en el YAML cuando
   necesita inspeccionar el ensamblado post-upload para debug.

5. **`wiring.py`**: pasa `config.assembly.keep_staged_files` al
   constructor del orchestrator.

### Uso

```yaml
assembly:
  source_root: /mnt/rvi/sources
  temp_dir: /var/run/cmcourier/staged
  keep_staged_files: false   # default — limpia post-upload
```

Para debug:

```yaml
assembly:
  keep_staged_files: true    # preserva temp_dir/{txn}.pdf
```

### Tests

* `tests/unit/orchestrators/test_staged_cleanup_after_upload.py`:
  - unlink del staged existente
  - `missing_ok` cubre archivo ya inexistente (idempotente)
  - `keep_staged_files=True` lo preserva
  - `OSError` se loguea pero no propaga
  - `AssemblyConfig` default es `False`

## Criterios de aceptación

1. Post-upload exitoso, `staged.path.exists()` es `False` (default).
2. Con `keep_staged_files=True`, `staged.path.exists()` es `True`.
3. Si el unlink falla (file lock, permisos), el orchestrator devuelve
   `"done"` igual — el S5_DONE ya está persistido.
4. `cmcourier doctor` no menciona staged como `FAIL` ni `WARNING`
   (no aplica acá).
5. `pytest -m unit` pasa.

## Riesgos

* **Solo se borran los staged en `temp_dir`** — `source_root` (los
  archivos del RVI bajo `ABAICD/ABAJCD/`) **NO se tocan jamás**. La
  fuente del banco es read-only para CMCourier; cualquier retiro del
  RVI es responsabilidad de un proceso aguas arriba.
* **Retry**: si un S5 falla y el operador hace `cmcourier batch retry`,
  S4 corre de nuevo y regenera el staged desde source. El cleanup no
  invalida retry.
* **Race condition**: dos workers no pueden tocar el mismo
  `staged.path` (txn_num es único por documento), así que no hay
  competencia.

## Notas

- Si el operador antes corría con `temp_dir` apuntando a un
  filesystem persistente esperando que CMCourier mantenga el
  ensamblado, ese comportamiento se rompe. Mitigación: setear
  `keep_staged_files: true` en el YAML.
- Posible spec futura: cleanup periódico de huérfanos en `temp_dir`
  (archivos viejos de crashes anteriores). Out of scope acá.
