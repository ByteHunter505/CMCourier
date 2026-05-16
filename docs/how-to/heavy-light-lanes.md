# How-to: Lanes heavy / light de upload (036, POST-MVP §1)

> [← Volver al índice](../INDEX.md) · [How-to](README.md)

Habilitar dos `lane`s adaptativos de upload cuando una porción conocida
por el operador de tu batch es **sustancialmente más grande** que el resto,
y podés afrontar el pequeño costo extra de coordinación a cambio de
latencia predecible por documento.

**Default OFF** (`processing.heavy_light_lanes.enabled = false`).
El comportamiento single-lane es byte-idéntico a pre-036.

## Cuándo activar esto

Activalo cuando:

- Los batches son bimodales — una cola de documentos grandes (PDFs
  multi-página, TIFFs de alta resolución) mezclados con muchos
  pequeños.
- A los operadores les importa la latencia de docs livianos, no solo
  el wall clock total. Los docs livianos shippean en **milisegundos**
  en vez de encolarse detrás de un slot de upload pesado.
- Podés elegir un valor `heavy_threshold_bytes` que separe limpiamente
  las dos poblaciones.

Dejalo OFF cuando:

- Los tamaños de documento son uniformes.
- El batch es chico (debajo de `heavy_lane_min_batch`, default 50 — el
  splitter cae automáticamente a single-lane).
- El throughput total es lo único que importa y la cola pesada domina
  igualmente.

## Qué ganás realmente

Sé realista con la ganancia:

- **Latencia para docs livianos**: significativa. Dejan de encolarse
  detrás de pesados.
- **Wall clock total**: modesto. Benchmarks sintéticos muestran **~5-10%**
  en batches bimodales dominados por pesados con `N=4` workers. La cola
  sigue siendo la cola.

El criterio de aceptación original POST-MVP §1 escribía ≥ 30 %
de throughput — eso fue aspiracional. Las heurísticas productivas se
afinarán en la fase de dry-run con datos reales.

## Configuración

`config.yaml`:

```yaml
processing:
  heavy_light_lanes:
    enabled: true                         # default: false
    heavy_threshold_bytes: 10485760       # default: 10 MB
    heavy_lane_min_batch: 50              # default: 50
    heavy_initial_ratio: 0.2              # default: 0.2 (20 % heavy)
    rebalance_interval_s: 10.0            # default: 10 s
    idle_threshold_s: 15.0                # default: 15 s
```

### Referencia de perillas

| Campo                  | Qué hace                                          | Hint de tuning                                 |
| ---------------------- | ----------------------------------------------------- | ------------------------------------------- |
| `heavy_threshold_bytes` | Un archivo staged ≥ este tamaño va al `lane` heavy.    | Elegí el punto de inflexión en tu histograma de tamaños. 10 MB es un default seguro para migraciones PDF/TIFF mixtas. |
| `heavy_lane_min_batch`  | Batches más chicos que esto saltean el split entero.   | Default 50. Por debajo de eso, el costo de coordinación > ganancia de paralelismo. |
| `heavy_initial_ratio`   | Share de `cmis.workers` reservado para pesados al arrancar. | 0.2 significa que 20 % de los workers arrancan en pesados. Más alto cuando la mayor parte del wall-clock son pesados; más bajo cuando los livianos son >90 % del batch. |
| `rebalance_interval_s`  | Período del tick del thread daemon.                            | Mantené el default 10 s. Más chico = más responsivo pero más CPU. |
| `idle_threshold_s`      | Tiempo que un `lane` debe quedar vacío antes de migrar workers. | Default 15 s evita flapping en pausas cortas. Bajalo a 1-2 s para batches muy rápidos; subilo para pesados grandes cuyo `lane` debe quedar reservado. |

## Cómo funciona el rebalance

El `LaneController` trackea cuándo la cola de cada `lane` llega a
cero por primera vez (`*_first_empty_at`). En cada tick de
`rebalance_interval_s`, si el tiempo elapsed desde ese stamp excede
`idle_threshold_s` para un `lane` y el otro `lane` todavía tiene
trabajo, el controller migra la capacidad del `lane` drenado al activo.
El lado drenado conserva un piso de 1 (el mínimo del `ResizableSemaphore`)
pero no quedan items para adquirirlo, así que el slot está efectivamente
dormido.

**Acoplamiento con AIMD**: cuando `cmis.auto_tune.enabled = true`, AIMD
dirige el budget TOTAL de workers; el controller redistribuye entre los
`lane`s preservando el ratio heavy/light actual. Los dos controllers no
pelean entre sí.

## Leyendo el TUI

Cuando el modo dual-lane está activo para un batch, la tab UPLOAD
intercambia el panel WORKERS único por dos sub-paneles apilados
HEAVY / LIGHT:

```
 WORKERS (heavy/light · budget total 8)
  HEAVY  capacity   2   in-use   2   idle   0   queue    3
         done    17   failed    1
  LIGHT  capacity   6   in-use   5   idle   1   queue   42
         done   134   failed    0
```

Las secciones NETWORK + gráfico de bandwidth + slow-ops quedan sin
cambios.

## Leyendo los logs

Cada rebalance emite una línea de log estructurada con
`event=lane_rebalance`:

```json
{
  "event": "lane_rebalance",
  "from": "light",
  "to": "heavy",
  "previous_heavy": 2,
  "previous_light": 6,
  "new_heavy": 8,
  "new_light": 1
}
```

`cmcourier analyze batch <id>` los expone en su conteo de rebalance.

## Deshabilitar en runtime

Seteá `enabled: false` (o eliminá el bloque entero) y reiniciá.
El modo single-lane corre byte-idéntico a pre-036; los batches existentes
en vuelo en el nuevo code path ya habrán terminado para cuando reinicies.

## Limitador de bandwidth

El `TokenBucket` compartido del cambio 029 (`cmis.max_bandwidth_mbps`)
limita la tasa de transferencia **combinada** entre ambos `lane`s. El
modo dual **no** duplica tu budget de bandwidth — ambos `lane`s extraen
del mismo techo global. El test unitario de 029
`test_throttles_via_shared_bucket` ya cubre la propiedad.

## Cross-references

- Spec: `specs/036-heavy-light-lanes/`.
- Entrada POST-MVP: `docs/roadmap/POST-MVP.md §1`.
- Relacionados: cambio 025 (`worker pool` S5 + AIMD), cambio 029 (limitador
  de bandwidth compartido), cambio 030 (vista TUI multi-batch).
