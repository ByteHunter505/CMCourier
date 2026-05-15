# 044 — Resume robusto después de kill -9 a mitad de S5

## Por qué

La verificación en vivo §H.1 contra el testserver de Alfresco
atrapó tres bugs relacionados que se componen para hacer que el flujo
de resume documentado quede no-funcional después de un crash real:

1. **Falso positivo "resume is clean".** ``_apply_resume`` en
   ``cli/app.py:842-850`` solo mira filas ``FAILED`` o ``PENDING``
   en ``stage_counts`` para decidir si hace falta resume. Después de
   ``kill -9`` a mitad de S5, los docs que S4 terminó pero S5 nunca
   levantó quedan en estado ``S4_DONE`` — ni failed ni pending. El
   loop camina S1..S5, no ve FAILED/PENDING, y reporta
   *"Nothing to resume — batch is clean"* a pesar de que el conteo
   de ``S4_DONE`` es 543 y el de ``S5_DONE`` es solo 281. El
   operador pierde la segunda mitad de su batch silenciosamente.

2. **La flag ``--batch-id`` se descarta silenciosamente sin
   ``--resume``.** ``cli/app.py:711`` solo reenvía el ``--batch-id``
   del usuario al orchestrator cuando también se pasa ``--resume``
   (``resume_batch_id = pipeline_kwargs.get("batch_id") if
   resume_flag else None``). El escape hatch del operador
   ``--batch-id X --from-stage 5`` (pensado para "replay este stage
   de este batch") falla con el críptico
   ``ValueError("from_stage > 1 requires batch_id")`` porque la
   validación ve ``batch_id=None`` aunque el usuario lo pasó.

3. **``_apply_resume`` sale antes de honrar ``--from-stage``.**
   Cuando ``--resume`` está seteado junto a ``--from-stage N``, el
   early-exit "is clean" cortocircuita el camino de override
   explícito. Compuesto con los bugs #1 y #2 esto significa: no hay
   **ninguna combinación de CLI** que recupere los 543 docs trabados
   sin SQL manual.

Esto es una sola clase de bug — el modelo de resume asumía cobertura
total del estado in-flight vía marcadores FAILED/PENDING, pero con
un worker pool del tamaño menor al batch, la mayoría de los docs
encolados para S5 quedan en ``S4_DONE`` sin marcador de que
necesitan S5.

## Qué

### 1. Resume detecta gaps de stages S{N}_DONE (bug #1)

``_apply_resume`` gana un chequeo de continuación por-stage: para
cada stage ``N`` en 1..4, si ``stage_counts[S{N}][DONE] > 0`` Y
ningún stage anterior tiene trabajo FAILED/PENDING, el
``from_stage`` resuelto es ``N+1``. El chequeo existente de
FAILED/PENDING queda primero (esos son más prioritarios — necesitan
el camino de retry del mismo-stage).

Después de este fix: un batch con 543 docs en ``S4_DONE`` + 281 en
``S5_DONE`` resuelve a ``from_stage=5``, corre S5 sobre los 543 docs
faltantes, y saltea los 281 ya subidos (vía el cortocircuito por-doc
``is_stage_done`` existente en ``_stage_s5``).

### 2. ``--batch-id`` siempre se pasa al orchestrator (bug #2)

``cli/app.py`` descarta el condicional ``if resume_flag else None``
— el ``--batch-id`` del usuario se reenvía incondicionalmente. El
orchestrator ya acepta ``resume_batch_id`` semánticamente como "el
batch_id sobre el cual este run debe operar" — pasarlo cuando el
usuario lo nombró es solo honrar la intención del operador.

Esto hace que ``--batch-id X --from-stage 5`` funcione como está
documentado sin requerir ``--resume``. Con ``--resume`` mantiene el
mismo comportamiento de auto-detección.

### 3. ``--from-stage`` le gana al exit "is clean" (bug #3)

Cuando ``--from-stage`` es explícito (``!= 1``) Y ``--resume`` está
seteado, el valor explícito gana sin importar si ``_apply_resume``
hubiera salido como "clean" en otras condiciones. El orden en
``_apply_resume`` se da vuelta: el chequeo explicit-wins pasa ANTES
del exit "is clean". El nuevo orden es:

1. Validar que ``--batch-id`` esté presente.
2. Cargar detalles del batch desde el store.
3. Si se pasó ``--from-stage > 1``: honrarlo (log INFO), return.
4. Auto-detectar el stage resuelto desde el análisis de gaps.
5. Si la detección rinde un stage: log INFO, return.
6. Sino (verdaderamente limpio): imprimir "Nothing to resume" y exit 0.

## Fuera de alcance

- La ventana de race del kill entre un HTTP 200 de S5 y el commit
  ``mark_stage_done`` de SQLite. Esa `race condition` deja docs en
  Alfresco pero no en el migration_log; en el resume, el mismo doc
  intenta subir de nuevo y Alfresco devuelve 409. El fix (manejo
  idempotente de 409 en ``CmisUploader``) es una preocupación
  separada con su propia superficie de diseño — diferido a una spec
  de follow-up.
- Revertir las semánticas de ``--batch-id`` para el caso de uso "el
  operador quiere nombrar un batch nuevo". Hoy un batch_id no
  reconocido se rechaza en ``store.get_batch_details(...)`` —
  mantenemos ese camino de error. El fix solo afecta el caso donde
  el batch_id refiere a un batch existente.
- ``--resume`` + solapamiento multi-batch N=2. El orchestrator ya
  rutea ``resume_batch_id`` a través de ``_run_single`` sin importar
  el N pedido, así que el fix aterriza una vez para todos los
  caminos.

## Criterios de aceptación

- Un test unitario para ``_apply_resume`` assertea que un batch con
  ``stage_counts={S4: {DONE: 543}, S5: {DONE: 281}}`` resuelve a
  ``from_stage=5`` (no "is clean").
- Un test unitario assertea que ``stage_counts={S5: {DONE: 824}}``
  todavía resuelve a "clean" (sin falsos positivos en batches
  verdaderamente completos).
- Un test unitario assertea que ``--batch-id X --from-stage 5`` (sin
  ``--resume``) produce un ``RunReport`` contra el batch nombrado
  sin levantar ``ValueError``.
- Un test unitario assertea que ``--resume --batch-id X --from-stage 5``
  honra el ``5`` explícito y NO sale temprano como "clean" incluso
  cuando no hay filas FAILED/PENDING.
- Un re-run en vivo de §H.1 contra staging:
  - Run 1: ``--total 50``, killear después de ~25 filas S5_DONE.
  - Run 2: ``--resume --batch-id <captured>`` — NO debe imprimir
    "is clean" y debe subir los docs restantes a Alfresco.
  - El conteo final de docs de Alfresco debe matchear el total de
    txns distintos del batch (módulo la `race condition` diferida
    del 409 para ~4-10 docs).
- Entrada ``CHANGELOG.md [0.47.0]``.
- mypy + ruff limpios.

## Notas sobre estrategia de tests

Los tests unitarios ejercitan ``_apply_resume`` directamente con un
retorno falso de ``SQLiteTrackingStore.get_batch_details`` — eso nos
deja cubrir los cuatro caminos de código (prioridad
FAILED/PENDING, gap S{N}_DONE, override explícito, verdaderamente
clean) sin orquestar un run real. El re-run en vivo reproduce el
escenario de staging original de §H.1 end to end.
