# 036 — Carriles adaptativos `heavy` / `light` para subida (POST-MVP §1)

## Por qué

Hoy S5 usa un único `ThreadPoolExecutor` compartido entre todos los
documentos de un `batch`. En `batches` heterogéneos (unos pocos PDFs
de 50 MB + muchos JPEGs de 200 KB), los documentos grandes
**acaparan los `worker`s** mientras los pequeños se mueren de hambre
— clásico bloqueo de cabeza de fila.

la especificación + POST-MVP §1 describen un modelo de subida de dos
`lane`s que divide el `batch` por tamaño de archivo, corre cada
`lane` en su porción del presupuesto de `worker`s, y rebalancea a
medida que un `lane` se drena.

## Qué

### Configuración

Nuevo bloque de esquema bajo `ProcessingConfig`:

```python
class HeavyLightLanesConfig(BaseModel):
    enabled: bool = False
    heavy_threshold_bytes: int = 10 * 1024 * 1024  # 10 MB
    heavy_lane_min_batch: int = 50
    heavy_initial_ratio: float = 0.2  # 20% of total workers to heavy
    rebalance_interval_s: float = 10.0
    idle_threshold_s: float = 15.0
```

`enabled = False` por defecto — comportamiento de un único `lane`
(pre-036) sin cambios.

### Splitter

Servicio de función pura `LaneSplitter.split(items, threshold_bytes,
min_batch) -> (heavy, light)`. Reglas:

1. Si `len(items) < min_batch` → todos `light`, ninguno `heavy`.
   Devuelve `(heavy=[], light=items)` y el llamador cae al modo de
   un único `lane`.
2. De lo contrario: particionar por
   `item.file_size_bytes >= threshold_bytes`.
3. **Fallback degenerado**: si alguna partición queda vacía,
   colapsar de vuelta a un único `lane` (`(heavy=[], light=items)`
   o `(heavy=items, light=[])` se normaliza río abajo a un único
   `lane`).

### LaneController

Posee dos `ResizableSemaphore` — `heavy_sem`, `light_sem` — más un
acoplamiento `AIMD` sobre el presupuesto total.

* **Asignación inicial**:
  `heavy_workers = ceil(total * heavy_initial_ratio)`,
  `light_workers = total - heavy_workers`. Cada `lane` recibe al
  menos 1 si `total ≥ 2`.
* **Integración `AIMD`** (restricción del usuario: `AIMD` posee el
  presupuesto global, el `rebalance` posee la división): cuando
  `AIMD` cambia el presupuesto total, el controlador redistribuye
  proporcionalmente a la división actual (preserva el ratio
  heavy:light vigente).
* **Loop de `rebalance`** corre en un `thread` daemon cada
  `rebalance_interval_s`. Dos reglas de disparo:
  - Si la cola `heavy` está vacía por ≥ `idle_threshold_s`:
    migrar todos los `worker`s `heavy` a `light` (heavy queda en 0,
    light recibe total).
  - Si la cola `light` está vacía por ≥ `idle_threshold_s`:
    migrar todos los `worker`s `light` a `heavy` (viceversa).
  - De lo contrario: mantener la división actual.
* **El `rebalance` es no-apropiativo**: las subidas en vuelo siguen
  corriendo en el `worker` donde estén. Los topes del `semaphore`
  determinan de qué cola toman los próximos `worker`s.
* **Eventos estructurados de `rebalance`**: cada migración emite una
  línea JSON vía el `logger` estándar del `pipeline` con
  `{"event": "lane_rebalance", "from": "heavy", "to": "light",
   "previous_heavy": N, "previous_light": M, "new_heavy": 0,
   "new_light": N + M}`. Recogida por `cmcourier analyze` (027).

### Despacho en S5

`StagedPipeline._stage_5` extendido:

* Si `heavy_light_lanes.enabled` es `False` **O** el `splitter` cae
  a un único `lane` → camino existente de pool único (cero cambio
  de comportamiento).
* De lo contrario → dividir + despachar a un ÚNICO
  `ThreadPoolExecutor(max_workers=total)`; cada `_upload_one` lleva
  su `lane` y adquiere el `semaphore` del `lane`. Dos instancias de
  `WorkerPoolStats` (una por `lane`) alimentan la TUI.

### TUI

La pestaña UPLOAD gana sub-paneles duales condicionales (solo cuando
el modo dual está activo para el `batch` actual):

* Panel HEAVY: `worker`s activos, profundidad de cola, bytes/seg,
  docs/seg, p95, operación actual por `worker`.
* Panel LIGHT: mismo layout.
* El layout de panel único se mantiene exactamente igual para
  corridas de un solo `lane`.

Los eventos de `rebalance` se muestran como notificaciones de la TUI
(`pipeline.notify("lane rebalance: 4→light")`).

### Limitador de ancho de banda

Ya es compartido globalmente desde 029. Ambos `lane`s usan el mismo
`BandwidthLimiter`. Un nuevo `property test` verifica que el total
de bytes/seg se mantenga bajo `cmis.max_bandwidth_mbps` incluso bajo
carga dual-`lane` pesada.

### Aceptación — prueba sintética de throughput

POST-MVP §1 exige ≥ 30% de mejora de `throughput` vs único `lane`
en un `batch` bimodal. Alcanzable vía prueba sintética:

* 30 documentos `light` (1 MB cada uno) + 5 documentos `heavy`
  (50 MB cada uno) = 280 MB en total.
* Uploader CMIS `mock`: `time.sleep(file_size_mb * 0.05s)` (50 ms/MB).
  Predecible; el bloqueo de cabeza de fila ES el cuello de botella.
* Tiempo total de un solo `lane`: ~17.5 s (serializado por un pool
  pequeño de `worker`s).
* Tiempo total dual-`lane`: ~12 s.
* Aserción: `dual_lane_time ≤ single_lane_time * 0.7` (30% de
  ganancia).

Si la aserción es inestable en CI, encerrar la prueba detrás de un
decorador `@pytest.mark.slow` + correr nightly.

## Compatibilidad hacia atrás

`heavy_light_lanes.enabled` por defecto en `False` → camino S5
byte-idéntico a pre-036. Una prueba de regresión corre el mismo
fixture de único `lane` dos veces (una con `enabled=False`, otra
sin el bloque de config) y verifica resultados idénticos.

## Fuera de alcance

- Tuning en producción de `heavy_threshold_bytes`,
  `idle_threshold_s`, etc. Esos se ajustan por el operador después
  del dry-run con datos reales.
- Presupuestos de reintento por `lane` — ambos `lane`s comparten la
  política de reintento CMIS existente (Tenacity).
- Cuota de ancho de banda por `lane` — eso es POST-MVP §8, cambio
  separado.
