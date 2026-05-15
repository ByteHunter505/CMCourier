# 057 — Dimensionar el thread pool de S5 al techo de AIMD

## Por qué

En un run de staging el operador miró la capacidad del pool del
tab UPLOAD trepando — 4 → 8 → 12 — mientras "in use" quedaba
clavado en **4**. El AIMD auto-tune cree que escaló hacia
arriba; el operador ve workers idle que no existen; las subidas
siguen corriendo de 4 en 4. La palanca de auto-tune está
desconectada del motor.

### El bug — dos limitadores, apilados en el orden equivocado

La concurrencia de upload de S5 está gateada por **dos** cosas:

1. **El `ThreadPoolExecutor`** — el límite *duro*.
   `_stage_5_single` (`staged.py`) lo crea con
   `max_workers=self._workers`, y `self._workers` es
   `cmis.workers` — fijo, capturado en construcción (default
   4). Solo esa cantidad de threads existen físicamente.
   `_stage_5_dual` tiene el mismo bug, dos veces (un pool por
   lane).
2. **El `ResizableSemaphore`** (`self._concurrency_limit`) —
   el límite *blando*, adquirido *adentro* de `_upload_one`.
   AIMD redimensiona **este** vía
   `_on_pool_resize → set_capacity(new_total)`, hasta
   `auto_tune.max_threads` (default **50**).

El semáforo vive *adentro* del thread pool. Solo
`cmis.workers` threads alguna vez llegan a `acquire()`. Por
más alto que AIMD levante el semáforo, no hay threads para
usar los slots extra — **el semáforo nunca puede ser el cuello
de botella; `max_workers` siempre lo es.**

La TUI lee `pool_capacity` de `_concurrency_limit.capacity`
(el semáforo — trepa) y `pool_in_use` de
`WorkerPoolStats.busy` (llamadas a `mark_busy` — topadas en
`cmis.workers`). De ahí el síntoma exacto: la capacity crece,
el in-use clavado en 4, el idle crece ficticiamente.

El docstring de `ResizableSemaphore` declara la intención
textual — resize "*sin tirar abajo el `ThreadPoolExecutor`
subyacente*" — y el docstring de `_stage_5_dual` dice que
cada pool está "*dimensionado al budget de workers TOTAL*". La
intención era un techo generoso de pool con el semáforo
regulando por debajo; el código dimensionó el pool al valor
*inicial* en vez de al *techo*.

## Qué

### `_pool_ceiling()` — el upper bound real

Un nuevo helper devuelve la cuenta máxima de threads que S5
podría llegar a necesitar:

- AIMD habilitado (`auto_tune` presente y `enabled`) →
  `max(self._workers, auto_tune.max_threads)`.
- AIMD deshabilitado → `self._workers` (sin cambios — el
  valor pre-057 ya es correcto cuando nada redimensiona el
  semáforo).

### Dimensionar ambos pools de S5 al techo

- `_stage_5_single` —
  `ThreadPoolExecutor(max_workers=self._pool_ceiling())`.
- `_stage_5_dual` — los `ThreadPoolExecutor` de heavy y light
  ambos reciben `max_workers=self._pool_ceiling()`. Los
  semáforos per-lane del `LaneController` ya topan la
  concurrencia *efectiva* per-lane y AIMD ya redimensiona el
  budget de lane — solo necesitan threads reales detrás. (Dos
  pools al techo significa que hasta `2 × techo` threads
  pueden existir, pero el `LaneController` topa el uso
  efectivo al budget total compartido; los threads excedentes
  se sientan idle a costo casi-cero — un thread parqueado.)

El `ResizableSemaphore` / `LaneController` pasan así a ser el
limitador *efectivo*, que es lo que las specs 025 / 036 / 043
siempre intentaron. Los threads idle en un
`ThreadPoolExecutor` son baratos — bloquean en la cola de
trabajo y consumen cero CPU.

`WorkerPoolStats.set_pool_size` en `_stage_5_single` se
actualiza al techo por consistencia interna (no se surface en
modo single-lane, pero dejarlo en el valor inicial obsoleto
sería engañoso).

## Fuera de alcance

- Cambiar el algoritmo de AIMD, su cadencia, sus bounds
  min/max, o el default de `auto_tune.max_threads`. 057 solo
  conecta la palanca existente a un pool que la pueda
  honrar.
- Un hard cap configurable distinto de
  `auto_tune.max_threads` — el techo de AIMD ya *es* el
  máximo intencional; sin nuevo campo de config.
- El renderizado de la TUI — el `data_provider` ya lee las
  fuentes correctas (`_concurrency_limit.capacity`,
  `pool.busy`); una vez que existan threads reales,
  `pool_in_use` sube solo. Sin cambio de TUI necesario.

## Criterios de aceptación

- `_pool_ceiling()` devuelve `auto_tune.max_threads` cuando
  AIMD está habilitado y `cmis.workers` cuando está
  deshabilitado — un test unitario assertea ambos (incluyendo
  el guard de `max(...)` cuando
  `cmis.workers > max_threads`).
- El `ThreadPoolExecutor` en `_stage_5_single` se construye
  con `max_workers == _pool_ceiling()` — un test captura el
  argumento del constructor en un run real con AIMD
  habilitado (`max_threads = 16`, `cmis.workers = 4`) y
  assertea que es `16`, y en un run con AIMD deshabilitado
  assertea que es `4`.
- Ambos `ThreadPoolExecutor` en `_stage_5_dual` se construyen
  con `max_workers == _pool_ceiling()` — un test lo
  assertea.
- Con AIMD deshabilitado, el comportamiento queda sin cambios
  — las suites existentes `test_s5_worker_pool` / dual-lane
  quedan verdes sin tocarlas.
- Suite completa unit + integration verde; mypy + ruff
  limpios.
- `CHANGELOG.md [0.60.0]`; `pyproject.toml` 0.59.0 → 0.60.0.

## Notas sobre estrategia de tests

El gap que dejó pasar esto: los tests de AIMD (043)
assertean que el *semáforo* se redimensiona — nunca que
existan threads reales para usar la capacity extra. 057 lo
cierra capturando el `max_workers` real pasado al
`ThreadPoolExecutor` (parchear la clase en el namespace del
módulo `staged` con un wrapper grabador que delega al real)
en un run real del pipeline. Eso es determinístico — sin
timing, sin sampling de concurrencia pico — y clava el hecho
estructural exacto que estaba mal. El test unitario de
`_pool_ceiling()` clava la computación.
