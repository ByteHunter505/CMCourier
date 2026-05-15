# 042 — Métricas de TUI: aislamiento por-chunk + contadores UPLOAD en vivo

## Por qué

Una verificación en vivo de 041 contra el testserver de Alfresco
(`--total 100 --batches-in-flight 2`) destapó tres bugs que los tests
unitarios de 041 no pudieron atrapar porque todos requieren un
solapamiento multi-batch real para reproducirse:

1. **La columna UPLOAD de la fila CHUNKS queda en `0/0/0` durante todo
   el stage S5.** Los operadores que miran el dashboard no ven
   progreso en los contadores por-chunk hasta que el chunk transiciona
   a DONE. La subida real SÍ está ocurriendo (el contador local
   `s5_done` del orchestrator avanza), pero
   ``MultiBatchOrchestrator._update_chunk_state`` solo escribe los
   contadores en ``ChunkState`` en la transición a DONE
   (`multi_batch.py:451`). La llamada intermedia de UPLOAD a
   ``_update_chunk_state(status="UPLOAD")`` (`:426`) deja
   ``s5_done`` y ``s5_failed`` en sus defaults de 0.

2. **`bandwidth.cumulative_bytes` se filtra entre chunks solapados.**
   Con ``batches_in_flight=2``, el frame final del run de
   verificación mostraba ``S5 UPLOAD ... 77.3 MB / 40.4 MB`` — MB
   subidos mayor que el total del chunk, lo cual es imposible si el
   aislamiento funciona. Causa raíz: ``_BandwidthHandler.emit``
   filtra solo por ``kind=="cmis_upload"`` y **no** filtra por
   ``batch_id``. Cuando el chunk #0 está subiendo mientras el
   recorder del chunk #1 ya arrancó (PREP), AMBOS handlers de
   bandwidth están attacheados al logger
   ``cmcourier.metrics.network``; cada evento ``cmis_upload``
   incrementa ambos contadores. El chunk #1 termina con los bytes del
   chunk #0 contados en su total acumulado. Nota:
   ``_SlowOpHandler`` lo hizo bien — lleva ``batch_id`` y
   cortocircuita en ``record.batch_id != self._batch_id``. El
   handler de bandwidth es la excepción.

3. **Los percentiles de S5 en el tab UPLOAD pueden bindearse al
   recorder del chunk equivocado durante el solapamiento.** El frame
   65 del run de verificación mostraba
   ``S5 UPLOAD ... 5.6 MB / 34.7 MB ... p50 0.0 ms`` — los bytes se
   habían acumulado pero las latencias de los percentiles eran cero.
   Causa raíz: ``MultiBatchOrchestrator._active_recorder`` es un
   único slot. Tanto ``_prep_loop`` como ``_upload_loop`` llaman a
   ``_set_active_recorder`` cuando su stage arranca. Cuando el chunk
   #1 entra a PREP mientras el chunk #0 está en UPLOAD, el active
   recorder se da vuelta al del chunk #1 (que todavía no tiene
   actividad S5). El tab UPLOAD lee los datos de percentiles del
   bucket S5 vacío del chunk #1.

## Qué

### 1. Aislamiento del handler de bandwidth por-chunk (bug #2)

``_BandwidthHandler`` gana un parámetro requerido ``batch_id`` en
``__init__`` y cortocircuita en ``emit`` cuando
``record.batch_id != self._batch_id``. ``MetricsRecorder.start_batch``
construye el handler con su propio ``batch_id``, replicando el patrón
de ``_SlowOpHandler`` que funciona desde 025.

Después de este fix, con N chunks solapados cada evento cmis_upload
sigue disparando en N handlers, pero solo el handler que matchea
incrementa su sampler — los bytes quedan aislados por chunk.

### 2. Contadores S5 en vivo propagados a la fila CHUNKS (bug #1)

Dos cambios:

- ``MetricsRecorder`` gana ``record_upload_done()`` y
  ``record_upload_failed()`` (espejo de ``record_upload_skipped``
  agregado en 041 Fase 3) con contadores thread-safe y métodos getter
  ``upload_done_count()`` / ``upload_failed_count()``.
- ``_stage_5_single`` y ``_stage_5_dual`` los llaman en las ramas de
  outcome ``"done"`` / ``"failed"``.
- ``data_provider._chunks_state_snapshot`` lee el upload recorder
  activo cuando ``status == "UPLOAD"`` y surface
  ``s5_done`` / ``s5_failed`` en vivo (el recorder es por-chunk en
  multi-batch, así que los contadores por-recorder SON los números
  por-chunk). Cuando ``status == "DONE"``, los valores vienen de
  ``ChunkState`` como hoy (congelados en la transición).

### 3. Active recorder separado para el lado UPLOAD (bug #3)

``MultiBatchOrchestrator`` mantiene el slot ``_active_recorder``
existente para el binding del tab PREP pero agrega un segundo slot
``_upload_active_recorder`` seteado solo en ``_upload_loop``.
Expuesto vía callback ``upload_recorder()`` junto al callback
``active_recorder()`` existente. El data provider usa
``upload_recorder()`` para todo lo de forma S5:

- Campos ``current_chunk_*`` de bytes / elapsed / avg / ETA
- El bloque de percentiles S5 del tab UPLOAD

El tab PREP sigue usando ``active_recorder()`` (el chunk más reciente
en PREP-o-UPLOAD). Esto desacopla los dos bindings de tab para que el
giro del recorder del lado PREP ya no perturbe el display del lado
UPLOAD.

Cuando ningún chunk entró a UPLOAD todavía, ``upload_recorder()``
devuelve ``None`` y el data provider hace fallback al recorder propio
del pipeline (el camino single-batch queda byte-idéntico al de hoy).

## Fuera de alcance

- Re-arquitecturar el lifecycle del recorder. El modelo de recorder
  por-chunk de 028 queda tal cual.
- Agregar un slot dedicado de recorder por-chunk del lado PREP. El
  tab PREP ya agrega bien; este spec solo toca el binding del lado
  UPLOAD.
- Series del chart de bandwidth (``bandwidth.series()``). La ventana
  de 60s decae per-handler también, pero el bug de cumulative_bytes
  es el de impacto visible para el operador. La exactitud de las
  series del chart se puede revisitar si aparece en reportes de
  campo.
- ``aggregator_snapshot`` (slow-ops) — ya aislado correctamente vía
  el filtro de batch_id del ``_SlowOpHandler`` (el comportamiento
  pre-042 está bien).

## Criterios de aceptación

- Un nuevo test unitario assertea que ``_BandwidthHandler.emit``
  ignora un record ``cmis_upload`` cuyo ``batch_id`` no matchea.
- Un nuevo test unitario assertea que
  ``MetricsRecorder.upload_done_count()`` avanza cuando se llama a
  ``record_upload_done()`` y es thread-safe bajo contención.
- Un nuevo test de snapshot de TUI assertea que ``render_chunks``
  muestra un ``s5_done`` no-cero para una fila en estado UPLOAD
  cuyo recorder reporta uploads.
- Un nuevo test estilo integración (usa ``MultiBatchOrchestrator``
  con un pipeline falso) assertea que con dos chunks solapados los
  ``cumulative_bytes`` por-chunk no se filtran entre recorders.
- mypy + ruff limpios.
- Entrada ``CHANGELOG.md [0.45.0]``.

## Notas sobre estrategia de tests

Agregamos un nuevo test de integración que corre
``MultiBatchOrchestrator`` end-to-end con un pipeline stub que
dispara eventos ``cmis_upload`` sintéticos para cada chunk. Esa es
la superficie de reproducción mínima para el bleed entre chunks y
el flip del active recorder — ninguno se podía testear en aislamiento
puro porque ambos dependen del wiring del lifecycle de
handler/recorder del orchestrator.
