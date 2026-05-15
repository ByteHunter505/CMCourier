# 043 — AIMD auto-tune: visibilidad de p95 por-chunk en modo multi-batch

## Por qué

La validación de staging §F.4 de 0.45.0 destapó una regresión
silenciosa introducida por la spec 028 (solapamiento multi-batch,
``batches_in_flight=2``): la observación de p95 del controlador de
AIMD auto-tune siempre reporta ``0.0`` a mitad de run, así que el
controlador nunca baja el throttle cuando el pool de uploads se
satura. Evidencia del run de F.4
(``batch_id=0a7bdf78-871b-42f4-8229-503efbf80578``, ``--total 200``):

* 91 eventos ``auto_tune_decision`` emitidos en 19 minutos.
* 85 de ellos son ``action="+1"`` (additive increase). Cero son
  ``"-1"``. Los workers subieron de 4 al techo ``max_threads=16`` y
  se quedaron ahí.
* Cada evento tiene ``p95_observed_ms = 0.0`` — incluyendo eventos
  mientras la latencia real de S5 era demostrablemente 700-1300 ms
  (visible en los frames del harness de verificación en vivo
  capturados durante 042).

Causa raíz: ``StagedPipeline._build_auto_tune_controller``
(``staged.py:255``) wirea el ``p95_provider`` del controlador a:

```python
p95_provider=lambda: self._metrics.current_stage_p95("S5")
```

``self._metrics`` es el ``MetricsRecorder`` propio del pipeline,
construido una sola vez en el build del pipeline. En **modo
single-batch (N=1)** los chunks escriben sus eventos de S5 en
``self._metrics`` — entonces el controlador ve p95 real. En **modo
multi-batch (N=2)** el orchestrator construye un recorder **por-chunk**
vía ``_build_chunk_recorder`` y rutea los eventos de S5 de cada
chunk ahí. El recorder ``self._metrics`` del pipeline no recibe nada
— entonces ``current_stage_p95("S5")`` devuelve ``0.0`` para siempre.

Es la misma clase de bug que spec 042 #3 (los percentiles S5 del tab
UPLOAD leían del recorder equivocado durante el solapamiento de
PREP). 042 lo arregló para la TUI introduciendo un slot
``upload_active_recorder``. 043 extiende el mismo fix arquitectónico
al controlador de AIMD.

## Qué

### 1. ``AutoTuneController.set_p95_provider(provider)``

Permitir que el callable ``p95_provider`` del controlador sea
intercambiado después de construcción. Espeja la superficie pública
de ``start()`` y ``stop()``. Thread-safe (reemplazo atómico de
referencia).

El default pre-043 (seteado en tiempo de construcción desde el
recorder propio del pipeline) queda como fallback para que el camino
single-batch quede sin cambios.

### 2. ``MultiBatchOrchestrator._run_overlapped`` wirea el upload provider

Antes de ``controller.start()`` dentro de ``_upload_loop``, el
orchestrator llama:

```python
controller.set_p95_provider(self._upload_p95_observer)
```

donde ``_upload_p95_observer`` lee desde
``self.upload_recorder()`` — el slot que 042 ya introdujo. Cuando
ningún chunk está todavía en UPLOAD (tick de warmup) el observer
devuelve ``0.0`` y el controlador lo trata como "hay slack
disponible, +1" — comportamiento idéntico a la primera ventana de
warmup de hoy.

Una vez que un chunk entra a UPLOAD, el observer devuelve el p95 de
S5 de ese chunk, el controlador ve latencia real, y la matemática
de AIMD se comporta correctamente: additive-increase por debajo del
target, multiplicative-decrease por arriba del target.

## Fuera de alcance

- Reestructurar el lifecycle del recorder. Los recorders por-chunk
  son el modelo correcto desde 028; el bug es el read path del AIMD,
  no el diseño del recorder.
- Surfaceear p95 a otros consumidores. La TUI ya bindea
  correctamente a través de la plomería ``upload_recorder()`` de 042.
  El AIMD es el único consumidor restante que leía del slot
  equivocado.
- ``timeout_auto_adjust`` por separado. El mismo provider impulsa
  tanto las decisiones de worker-count como las de timeout —
  arreglar el provider arregla los dos de un solo tiro.
- Un controlador "tune both prep + upload". La latencia del stage
  PREP es CPU-bound y no es interesante para las decisiones de
  presión de red del AIMD; fuera de alcance.

## Criterios de aceptación

- Un test unitario assertea que ``AutoTuneController.set_p95_provider``
  intercambia el read path y el siguiente tick usa el nuevo provider.
- Un test unitario que usa un ``MetricsRecorder`` real confirma que
  el controlador observa p95 no-cero una vez que los eventos de stage
  llegan.
- Un re-run en vivo del escenario §F.4
  (``--total 200 --batches-in-flight 2``) emite al menos un evento
  ``auto_tune_decision`` con ``p95_observed_ms > 0`` Y la cuenta de
  workers no crece monotónicamente todo el camino hasta
  ``max_threads`` (es decir, AIMD muestra actividad mixta de
  up/down).
- Entrada ``CHANGELOG.md [0.46.0]``.
- mypy + ruff limpios.

## Notas sobre estrategia de tests

Los tests unitarios usan un ``p95_provider`` falso (callable) que
devuelve valores enlatados para impulsar el controlador a través de
una secuencia conocida sin necesitar un ``MetricsRecorder`` real. La
verificación de integración reusa la invocación de F.4 (~19 min de
run) y grepea los mismos eventos ``auto_tune_decision`` usados para
identificar el bug — esa es la superficie de reproducción mínima y
la verificación más limpia.
