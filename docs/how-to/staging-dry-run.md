# How-to: Dry-run de staging

> [← Volver al índice](../INDEX.md) · [How-to](README.md)

Un dry-run de staging valida la combinación **código + config + datos reales**
contra un repositorio CMIS no productivo **antes** de la primera
migración productiva. Hace aparecer los bugs que ningún test sintético
puede atrapar: rarezas de encoding, conectividad CMIS, cobertura de
mapping, características de performance sobre el bandwidth real del link,
drift de schema AS400.

Este runbook es **genérico** — se aplica a cualquier entorno de staging
(CMIS staging provisto por el banco, nuestra propia simulación de
Alfresco, una futura instancia multi-tenant de test). Para el setup
específico Alfresco-on-Docker local, ver `docs/how-to/local-staging-simulation.md`.

---

## Prerrequisitos

1. **URL + credenciales de CMIS staging** en env vars `CMIS_USERNAME` /
   `CMIS_PASSWORD`.
2. **Sample de filas RVABREP** — CSV exportado de AS400 productivo o
   una réplica ODBC. 100-1000 filas mínimo para ejercitar `lane`s (036) +
   multi-batch (028).
3. **Sample de archivos fuente** — TIFFs / PDFs alcanzables vía el
   path `assembly.source_root` configurado.
4. **CSVs de mapping productivos** — `MapeoRVI_CM.csv` + `MetadatosCM.csv`
   del banco, O nuestro dataset sintético para simulación.
5. **Una DB de tracking SQLite vacía** bajo `tracking.db_path` — dropearla
   en cada corrida mantiene los batches aislados.

## Los siete pasos

El dry-run corre como una **cascada con gates**. Cada paso tiene una
**condición de stop**: si falla, arreglar y reintentar antes de avanzar.
No salteés — un fallo de paso 3 sobre un fallo de paso 2 puede ocultar
causas raíz.

### Paso 0 — `cmcourier doctor`

```bash
cmcourier doctor -c config-staging.yaml
```

Los seis checks pre-flight:

1. `log_dir_writable` — ./logs es escribible.
2. `cmis_connectivity` — el CMIS staging responde.
3. `tracking_openable` — SQLite abre con modo WAL.
4. `mapping_completeness` — el Modelo Documental tiene ≥1 fila.
5. `metadata_sources` — cada fuente de alias CSV carga ≥1 fila.
6. `cm_type_alignment` — cada `cm_object_type` distinto derivado del
   mapping resuelve vía CMIS `getTypeDefinition`. **El check más
   discriminante** — un fallo acá significa que faltan tipos en
   staging, o que necesitás el override `cmis_type` (039) para
   mapearlos a un tipo genérico.
7. `sample_dry_run` — walk S1→S4 sobre el primer doc del primer trigger.

**Condición de stop**: cualquier FAIL excepto un `sample_dry_run`
SKIPpeado (que ocurre cuando el trigger no tiene docs, OK en issues
de dataset que ya conocemos). Arreglar el check que falla; reintentar.

### Paso 1 — Un doc de punta a punta

```bash
cmcourier rvabrep-pipeline run -c config-staging.yaml --total 1
```

El pipeline corre S0→S5 para **exactamente un doc**. El primer upload real.

**Validar post-corrida**:
- El doc aparece en CMIS staging bajo el path de carpeta esperado.
- Su `cmis:objectTypeId` matchea lo que seteamos (el target del override
  si se usa, el valor derivado en otro caso).
- Sus propiedades contienen los metadatos resueltos.
- `tracking.db` tiene una fila en `S5_DONE` con el object id CMIS.
- Si `metadata.cache.enabled = true`, `document_cache` tiene la entrada.

**Condición de stop**: cualquier cosa mal. **Un doc es tu oportunidad
de alineación** — a escala estos problemas se componen.

### Paso 2 — 100 docs con TUI

```bash
cmcourier rvabrep-pipeline run -c config-staging.yaml --total 100 --tui
```

El TUI muestra throughput live, latencia p95, decisiones AIMD, uso de
bandwidth, slow ops.

**Qué mirar**:
- **Tab PREP**: cualquier stage S0-S4 que se tome significativamente
  más tiempo que su límite inferior teórico es un bug o una config
  mala.
- **Tab UPLOAD**: p95 debe ser < `cmis.auto_tune.target_p95_ms`
  (default 5 s). Si AIMD sigue achicando workers, el link CMIS staging
  o tu config es el bottleneck.
- **Gráfico de bandwidth**: actual vs techo. Si siempre en el techo, el
  cap de bandwidth es el bottleneck — bumpear `cmis.max_bandwidth_mbps`
  o aceptar el SLA.
- **Tasa de hit del cache** (si está habilitado): eventos
  estructurados `document_cache_hit / miss` en
  `logs/pipeline-<date>.jsonl`.

**Condición de stop**: fallos > 0, memoria monotonicamente creciente
más allá del tamaño staged-batch, AIMD oscila sin converger.

### Paso 3 — Analyze

```bash
cmcourier analyze batch <batch_id> -c config-staging.yaml
```

Por-stage p50/p95/p99, slow ops por kind (`cmis_upload`,
`s4_assembly`), rebalances de `lane` (si el modo dual está on), cache hits.

**Datos para decisiones**:
- `cmis.workers` — si AIMD convergió en un valor, usá ese como default
  estático en producción.
- `cmis.max_bandwidth_mbps` — bench-testeado con `--total 100`,
  documentar el headroom.
- `heavy_threshold_bytes` (036) — elegir el punto de inflexión de la
  distribución de tamaños observada.
- `metadata.cache.ttl_minutes` (037) — matchear el patrón de reuso
  observado.

### Paso 4 — 1000 docs (o sample completo)

```bash
cmcourier rvabrep-pipeline run -c config-staging.yaml --total 1000
```

Validación de escala. Los números del Paso 3 deberían mantenerse
linealmente. Si el throughput cae pasando N=500, cazá el bottleneck:

- Servidor CMIS saturado → preguntá al admin de staging
- IO de disco local → chequear `iostat`
- Contención de tracking SQLite → mirar la profundidad de cola del writer
- Limitador de bandwidth aguantando las cosas → chequear actual vs techo

### Paso 5 — Multi-batch (opcional, si shippea 028)

```bash
cmcourier rvabrep-pipeline run -c config-staging.yaml --batch-size 250 --total 1000 --tui
```

Dispara 4 batches × 250 docs con el orquestador multi-batch (overlap
N=2). Valida la tab `CHUNKS` + coordinación cross-batch.

### Paso 6 — Inyección de fallos (opcional)

Parar CMIS staging manualmente en medio de una corrida. Verificar:
- Los retries disparan (eventos `cmis_upload_retry` en el log de network).
- Después de que staging se recupera, ningún doc se sube doble
  (idempotencia cross-batch vía `tracking.is_uploaded`).
- `cmcourier batch retry-failed <batch_id>` resume limpiamente.

### Paso 7 — Firma

Documentar la corrida:

```bash
cmcourier batch show <batch_id> -c config-staging.yaml > runs/$(date -I)-batch-show.txt
cmcourier analyze batch <batch_id> -c config-staging.yaml --format json > runs/$(date -I)-analyze.json
```

Tagueá el hash del commit del build que corrió. Decidir: **luz verde
para migración productiva, o programar un sprint de fixes**.

---

## Findings comunes (catálogo)

Después de suficientes dry-runs empezás a ver patrones:

| Síntoma | Causa probable | Fix |
| --- | --- | --- |
| Doctor `cm_type_alignment` falla en todos los tipos | Staging no tiene los tipos IBM CM del banco (o estás contra Alfresco) | Usar override `cmis_type` (039) — setear `CMISType=cmis:document` en las filas del mapping solo para staging |
| Latencia S3 >> esperada | Una fuente de campo (query AS400 o CSV grande) re-corre por doc | Habilitar `metadata.cache.enabled` (037) o arreglar el path de lookup de la fuente del campo |
| Upload 400 "property not declared" | Alfresco staging sin un Content Model que declare propiedades custom | Desplegar `scripts/staging/cmcourier-model.xml` (ver local-staging-simulation.md) O setear staging para usar solo `cmis:document` y strippear propiedades custom |
| TUI muestra AIMD oscilando workers entre min/max | `target_p95_ms` está seteado más bajo de lo que el link staging puede entregar | Subir `cmis.auto_tune.target_p95_ms` |
| Multi-batch (028) cuelga después de 1 batch | La cola de writer de tracking drenó pero la coordinación de batch se quedó pegada | Chequear que `tracking.flush` se está llamando entre batches |
| Warnings random `Connection pool is full` | `cmis.workers > pool_size` (pre-038) | Actualizar a 0.39.0+; `pool_size` se auto-dimensiona a `auto_tune.max_threads` |

---

## Cross-references

- Simulación específica de Alfresco: `docs/how-to/local-staging-simulation.md`.
- Comando doctor: la spec, `src/cmcourier/cli/doctor.py`.
- Observabilidad de cache: `docs/how-to/document-cache.md`.
- Observabilidad multi-batch: `docs/how-to/multi-batch.md`.
- Análisis de logs: `docs/how-to/log-analysis.md`.
