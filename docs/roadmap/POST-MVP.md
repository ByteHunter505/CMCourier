# CMCourier — Roadmap Post-MVP

> **Estado**: Documento vivo. Actualizado a medida que se difieren o completan nuevas funcionalidades.
> **Última actualización**: 2026-05-14

Este documento captura toda funcionalidad, optimización e intención de diseño que está **diferida** más allá del MVP. **Nada acá está descartado** — todo es intencional, priorizado, y se va a implementar en cambios subsiguientes después de que el MVP esté operativo. Cada entrada está estructurada para estar lista para consumir como input para una futura propuesta `/sdd-new`.

---

## Qué significa "MVP" en este proyecto

El **MVP** entrega migración de documentos de punta a punta hacia IBM Content Manager a través de **tres pipelines productivas** (`csv-trigger`, `rvabrep`, `local-scan`) más la diagnóstica `single-doc`, con los ocho stages atómicos (`S0`–`S7`, ver `docs/domain/the project's domain spec §10.1`), un único worker pool S5 redimensionable para upload con **auto-tune AIMD**, ejecución basada en batches con resumabilidad stage-by-stage, TUI textual de dos tabs por default, logging estructurado en los niveles aplicación + pipeline + network + slow-ops, tracking SQLite idempotente, el comando pre-flight `doctor`, y el runner `background` cron-friendly.

> **Nota (048)**: ya no existe una pipeline `as400-trigger` separada. "AS400" es una elección de *fuente* en la pipeline `rvabrep` (`indexing.source.kind: as400`), no su propia pipeline — la pipeline `rvabrep` sirve tanto un archivo CSV como una query AS400 en vivo. Ver `CHANGELOG.md [0.51.0]`.

El MVP **excluye** explícitamente: cualquier scheduling de upload consciente del tamaño (lanes heavy/light), sampleo de recursos de sistema (nivel 5 con `psutil`), herramientas de análisis de log offline, tracking respaldado en AS400, paralelismo multi-batch más allá del overlap producer-consumer básico de dos batches, cuotas de bandwidth por-batch, y un cache cross-batch de metadatos.

Todo lo excluido vive abajo, con suficiente detalle para arrancar un nuevo cambio directamente.

### Snapshot de estado

- **Done (promocionado al MVP)**: §1 — lanes adaptativos heavy/light de upload (shippeado en cambio 036); §2 — métricas de sistema nivel 5 vía `psutil` (shippeado en cambio 026); §3 — herramientas de análisis de log offline `cmcourier analyze` (shippeado en cambio 027); §4 — idempotencia distribuida AS400 NIARVILOG (shippeado en cambio 034); §5 — auto-tuning adaptativo de workers AIMD (shippeado en cambio 025); §6 — pipelines adicionales csv / as400-trigger / local-scan (shippeado en cambios 012 / 014 / 016 — nota: 048 después fusionó `as400-trigger` en la pipeline `rvabrep` como una fuente); §7 (N=2) — overlap producer-consumer de dos batches (shippeado en cambio 028; N=3..5 diferido a un cambio futuro); §9 — cache cross-batch de metadatos `document_cache` (shippeado en cambio 037).
- **Todavía diferido**: §7 (N>2), §8, más la watchlist del §10.

### Shippeado desde que este snapshot se numeró por última vez (specs 038–049)

Las secciones numeradas con § arriba son el backlog post-MVP *original*. Los siguientes cambios shippearon después como specs standalone (cada uno en su propia branch `feat/NNN-*`, FF'd a `main`) — endurecimiento operacional, fixes de bugs, y refinamientos surgidos durante el shakedown de staging. **No** son secciones del roadmap; esta lista mantiene el snapshot honesto.

| Spec | Versión | Resumen |
|------|---------|---------|
| 038 — cmis-target-preflight | 0.41.0 | Checks pre-flight de destino CMIS + trace de payload de upload |
| 039 — mock-rvabrep-generator | 0.42.0 | `cmcourier mock rvabrep` — CSV RVABREP sintético a cualquier escala |
| 040 — alfresco-url-compat | 0.43.0 | Compatibilidad CMIS Alfresco (semántica `repo_id=""`, forma de URL) |
| 041 — tui-fix-and-features | 0.44.0 | TUI: dashboard limpio + progreso MB + breakdown CHUNKS |
| 042 — tui-metrics-bleed | 0.45.0 | Métricas TUI: aislamiento por-chunk + contadores UPLOAD live |
| 043 — aimd-multibatch-p95 | 0.46.0 | El auto-tune AIMD ve p95 real en modo multi-batch |
| 044 — robust-resume | 0.47.0 | Resume robusto tras `kill -9` en medio de S5 (detección de gap de stage) |
| 045 — idempotent-409 | 0.48.0 | Upload S5 idempotente ante conflicto CMIS 409 |
| 046 — polymorphic-trigger | 0.49.0 | Modelo `Trigger` polimórfico — cada pipeline emite su forma natural |
| 047 — persist-cm-object-id | 0.50.0 | Persistir `cm_object_id` en `S5_DONE` en la DB de tracking |
| 048 — pluggable-rvabrep-source | 0.51.0 | Fuente RVABREP pluggable (CSV ↔ AS400); pipeline `as400-trigger` removido |
| 049 — niarvilog-column-mapping | 0.52.0 | Nombres de columna / identificador NIARVILOG configurables por entorno |

Notá también: el cambio 039 (CHANGELOG `[0.39.0]`) shippeó el **ítem 2
de la watchlist §10** — warm-up eager del connection pool CMIS al inicio del proceso.

---

## §1. Lanes Adaptativos Heavy / Light de Upload — **SHIPPEADO en cambio 036 (2026-05-11)**

> Promocionado fuera de post-MVP y entregado como parte del cambio 036.
> Default off; habilitar vía `processing.heavy_light_lanes.enabled`.
> El target original de ≥ 30 % throughput era aspiracional; la ganancia
> medida de wall-clock en batches bimodales sintéticos es ~5-10 %. La
> ganancia real visible para el operador es la latencia por documento.
> Ver `specs/036-heavy-light-lanes/`, `docs/how-to/heavy-light-lanes.md`,
> y `CHANGELOG.md [0.37.0]`.

### Intención

Reemplazar el upload pool single-lane del MVP con **dos worker pools adaptativos** para eliminar el head-of-line blocking en batches heterogéneos. Los pools comparten un budget global de workers y rebalancean dinámicamente basados en la profundidad de cola.

El modelo mental es dos carriles:
- **Lane heavy**: pocos workers, archivos grandes, throughput por documento lento.
- **Lane light**: muchos workers, archivos chicos, throughput por documento alto.

Cuando un lane drena, sus workers migran al otro. Cuando un lane está vacío, todos los workers sirven al lane restante.

### Diseño

**Política de split** (heavy vs light por batch):
- Después de que S4 completa para un batch, la distribución de tamaños es conocida.
- Split default: **top 25% de archivos por tamaño → heavy**, el resto → light. Tanto el percentil como el threshold absoluto (`>= X MB → heavy`) son configurables; gana la regla que produzca menos items heavy (evita batches degenerados donde todo parece heavy).
- Un batch con muy pocos documentos (`< heavy_lane_min_batch`, default 50) saltea el split y usa upload single-lane.

**Budget de workers**:
- Workers totales = `processing.thread_count` (un único cap global, igual que el MVP).
- Asignación inicial: el lane heavy recibe `ceil(total * heavy_initial_ratio)` workers (default 0.2 = 20%), el light el resto.
- Rebalance cada `rebalance_interval_s` (default 10s) basado en la profundidad y throughput observado de cada cola.
- Regla de rebalance: si un lane está vacío por `idle_threshold_s` (default 15s), migrar todos sus workers al otro lane.

**Bandwidth compartido**:
- El `BandwidthLimiter` de `the project's domain spec §8.6` se vuelve un **token bucket compartido** entre lanes.
- El lane heavy pide chunks más grandes de tokens (matchea su tamaño de transferencia por doc); el lane light pide chunks más chicos.
- Sin cuota reservada por lane — ambos compiten por el mismo budget global.

**Integración con TUI**:
- La tab UPLOAD muestra dos sub-paneles: HEAVY y LIGHT.
- Cada sub-panel: workers activos, profundidad de cola, throughput (bytes/sec y docs/sec), latencia p95, operación actual por worker.
- Los eventos de rebalance se loguean como notificaciones del TUI.

### Placeholder MVP

Único worker pool S5 con `processing.thread_count` workers, sin consciencia de tamaño, sin rebalance. El campo de config `processing.heavy_light_lanes.enabled` existe en el schema de config con un default de `false` así adoptar la funcionalidad post-MVP es un flip de config, no un cambio de código.

### Por qué se difirió

1. **Multiplicador de complejidad**: pool dual + rebalanceador adaptativo + token bucket compartido + paneles TUI duales = aproximadamente 3× el code path de upload. Riesgoso para la primera migración funcionando.
2. **La validación requiere datos reales**: afinar el percentil de split, el intervalo de rebalance, y el threshold de idle requiere batches productivos reales. Elegir valores a ciegas es adivinanza.
3. **Single-lane no está mal** — solo no es óptimo. El MVP entrega resultados correctos; esto entrega resultados más rápidos.

### Criterios de aceptación para el cambio post-MVP

- [ ] El schema de config incluye el bloque `processing.heavy_light_lanes` completo validado por Pydantic.
- [ ] Un test de integración corre un batch sintético con distribución de tamaños bimodal contra un adapter CMIS mockeado y verifica que los lanes se asignen correctamente, que los workers rebalanceen cuando una cola drena, y que el throughput total exceda el baseline single-lane por ≥30%.
- [ ] El TUI muestra ambos sub-paneles live durante corridas heavy/light.
- [ ] Deshabilitar `heavy_light_lanes.enabled` cae al comportamiento single-lane palabra por palabra (test de regresión).
- [ ] El limitador de bandwidth es compartido (sin cuota reservada por lane); un test de propiedad confirma que el total bytes/sec nunca excede `cmis.max_bandwidth_mbps`.
- [ ] Los eventos de rebalance se loguean estructuralmente para análisis offline.

### Dependencias

- Requiere que el S5 del MVP esté limpiamente aislado (lo va a estar — Principio Constitucional I, Hexagonal).
- Requiere el layout de directorio de staging del MVP (tamaños de archivo completos conocidos después de S4).

---

## §2. Observabilidad de Métricas de Sistema (Sampleo psutil) — **SHIPPEADO en cambio 026 (2026-05-11)**

> Promocionado fuera de post-MVP y entregado como parte del cambio 026.
> Costo medido del sampler: ~0.10% CPU a intervalo de 5 s. Ver
> `specs/026-system-metrics-tier5/` y
> `CHANGELOG.md [0.28.0]`.

### Intención

Agregar un quinto nivel de logging que samplee la utilización de recursos del sistema (CPU, RAM, disk IO, network IO) a intervalos configurables para identificar bottlenecks empíricamente en lugar de por adivinanza.

### Diseño

- Un thread de fondo corre sampleo de `psutil` a intervalos de `observability.system_sample_interval_s` (default 5s).
- Cada sample emite una línea JSON a `./logs/system-{date}.jsonl`:
  ```json
  {"ts": "2026-05-08T10:23:45Z", "cpu_pct": 73.2, "ram_used_mb": 4120, "ram_total_mb": 8192,
   "disk_read_mbps": 12.4, "disk_write_mbps": 33.1, "net_in_mbps": 8.2, "net_out_mbps": 95.3,
   "process_pid": 12345, "process_threads": 42, "active_workers": 20}
  ```
- Las métricas a nivel proceso y a nivel host están separadas (host = la máquina entera; proceso = nuestro PID y children).
- El thread de sampleo termina limpiamente al shutdown del pipeline.

### Placeholder MVP

`observability.system_metrics: false` en la config. El campo del schema existe; el thread de sampleo no está implementado. Las métricas de network y pipeline (baratas) siguen activas.

### Por qué se difirió

1. El sampleo de `psutil` no es gratis — a 1Hz cuesta CPU medible. El MVP no puede permitirse debatir "¿nos ralentizamos solos con nuestra propia observabilidad?" mientras también debugea la lógica de migración.
2. La identificación de bottleneck requiere que las herramientas de análisis de log offline (§3) sean útiles — sin ellas, el archivo JSONL es solo datos que nadie lee.
3. El MVP va a demostrar si los bottlenecks existen en general — si la migración es upload-bound (lo cual es probable), las métricas de sistema no nos dicen nada nuevo.

### Criterios de aceptación para el cambio post-MVP

- [ ] El thread de sampleo arranca/para con el pipeline, nunca leakea.
- [ ] El toggle de config funciona (off → ningún thread spawnea, no se crea archivo).
- [ ] El formato es JSON Lines, un sample por línea, parseable por la herramienta §3.
- [ ] Overhead de sampleo medido: menos del 1% CPU al intervalo default; documentado.
- [ ] Documentado en `docs/how-to/observability.md` (creado en este cambio) incluyendo cómo leer el archivo.

### Dependencias

- Ninguna dura. Dependencia blanda con §3 (el analizador offline) para que los datos sean valiosos.

---

## §3. Herramientas de Análisis de Log Offline — **SHIPPEADO en cambio 027 (2026-05-11)**

> Promocionado fuera de post-MVP y entregado como parte del cambio 027.
> Ver `specs/027-log-analyzer/`, `docs/how-to/log-analysis.md`,
> y `CHANGELOG.md [0.29.0]`. Render HTML diferido a un
> follow-up futuro.

### Intención

Herramientas que consumen los niveles de log (app, pipeline, network, system) y producen **reportes de atribución de bottleneck**: ¿un batch lento fue CPU-bound, memory-bound, disk-IO-bound, o network-bound? ¿Qué stage se llevó más tiempo? ¿Qué documentos tardaron más?

### Diseño

Una suite de subcomando bajo `cmcourier analyze`:

```
cmcourier analyze batch <batch_id>
    Agrega todos los archivos de log de un batch en un reporte:
    - Distribución de tiempo por-stage
    - Tasa de fallo por-stage con agrupación de errores
    - Documentos más lentos con breakdown completo stage-by-stage
    - Utilización de recursos correlacionada con la timeline del batch
    - Clasificación de bottleneck (CPU / mem / disk / net) con confidence

cmcourier analyze compare <batch_id_a> <batch_id_b>
    Diff entre dos batches: delta de throughput, delta de latencia, dónde se gastó el tiempo distinto.

cmcourier analyze trends [--last N] [--pipeline <name>]
    Tendencias de throughput y p95 a través de los últimos N batches para una pipeline.
```

Formatos de salida: terminal legible para humanos, JSON, reporte HTML (opcional).

### Placeholder MVP

Ninguno. Los archivos de log existen pero leerlos es manual.

### Por qué se difirió

1. Las herramientas tienen valor cero hasta que §2 shippee y haya batches productivos reales con métricas de sistema para analizar.
2. El formato de cada nivel de log puede evolucionar durante el shakedown del MVP; congelar el analizador muy temprano crea churn.
3. Esto son herramientas del lado de operaciones, no herramientas de corrección de migración. La corrección del MVP shippea primero.

### Criterios de aceptación para el cambio post-MVP

- [ ] `cmcourier analyze batch <id>` produce un reporte completo a partir de los archivos de log de un batch sample.
- [ ] El clasificador de bottleneck está documentado (reglas + thresholds en `docs/how-to/log-analysis.md`).
- [ ] Los reportes son deterministas dados los mismos archivos de log de entrada (fixtures de test).
- [ ] El comando compare produce un lado-a-lado útil para corridas de tuning.

### Dependencias

- §2 (métricas de sistema) — blanda. Útil sin ella, mucho más útil con ella.

---

## §4. Tracking Store Respaldado en AS400 — **SHIPPEADO en cambio 034 (2026-05-11)**

> Refinado y entregado como un modelo **híbrido** en lugar de un
> reemplazo drop-in. La tabla existente `RVILIB.NIARVILOG` del banco
> coordina idempotencia cross-batch + evaluación Java paralela;
> SQLite queda como la máquina de estados por-batch.
> Toggleable vía `tracking.as400_sync.enabled`. Ver
> `specs/034-as400-niarvilog-sync/`,
> `docs/how-to/as400-sync.md`, y CHANGELOG [0.35.0].

### Intención

El port `ITrackingStore` tiene dos implementaciones: `SQLiteTrackingStore` (MVP) y `AS400TrackingStore` (post-MVP). Esta última routea el estado de idempotencia a una tabla centralizada `RVILIB.MIGRATION_LOG` en AS400, satisfaciendo entornos donde el banco requiere tracking centralizado en el sistema legacy en lugar de en un archivo de workstation.

### Diseño

- Implementa el mismo contrato `ITrackingStore` que SQLite.
- Manejo de conexiones vía el mismo patrón thread-local pyodbc que `AS400DataSource`.
- El schema espeja el schema de SQLite en `the project's domain spec §9.2` adaptado para DB2 for i (tipos de columna: `CHAR`, `TIMESTAMP`, `INTEGER`, etc.).
- El concepto de cola de writer async (`§9.4`) se preserva, pero los commits se batcheran en inserts AS400 vía `executemany`.
- Configuración: `tracking.backend: "as400:default"`.

### Placeholder MVP

`tracking.backend: "sqlite"` es el único backend soportado en el MVP. El campo del schema acepta `as400:<alias>` como valor pero levanta `NotImplementedError` al startup con un mensaje claro apuntando a esta entrada del roadmap.

### Por qué se difirió

1. El test de integración para tracking AS400 requiere acceso AS400 real (Principio Constitucional VI: AS400 no se mockea). Los tests del MVP ocurren contra CSV + SQLite + Alfresco, todos localmente disponibles.
2. SQLite cubre todas las necesidades de dev / staging y muchos escenarios de producción.
3. La migración de la implementación de tracking AS400 del codebase viejo es moderada (~300 líneas + tests) y se hace mejor después de que la forma del MVP esté asentada.

### Criterios de aceptación para el cambio post-MVP

- [ ] `AS400TrackingStore` pasa la misma suite de tests de contrato que `SQLiteTrackingStore`.
- [ ] Test de integración contra entorno AS400 staging real en CI nightly.
- [ ] Script de migración de schema (`scripts/install_as400_tracking_schema.sql`) idempotente.
- [ ] Comportamiento operacional documentado: fallos de conexión durante escrituras de tracking nunca crashean el pipeline (§10.1 stage S6 dice que el tracking es no-blocking).
- [ ] `cmcourier doctor --check tracking` valida el backend de tracking AS400 si está configurado.

### Dependencias

- Disponibilidad de entorno staging AS400 (operacional, no técnica).

---

## §5. Auto-Tuning Adaptativo de Workers AIMD — **SHIPPEADO en cambio 025 (2026-05-10)**

> Promocionado fuera de post-MVP y entregado como parte del cambio 025. La
> sección se mantiene por contexto histórico y para documentar la
> intención de diseño que la implementación honra. Ver
> `specs/025-tui-workers-autotune/` y `CHANGELOG.md [0.27.0]`.

### Intención

El MVP corre S5 con un conteo fijo de workers desde la config. Post-MVP, un controller **AIMD (Additive Increase / Multiplicative Decrease)** ajusta el conteo de workers online basado en la latencia p95 observada, espejando el control de congestión de TCP.

### Diseño

- Configuración:
  ```yaml
  processing:
    auto_tune:
      enabled: true
      min_threads: 2
      max_threads: 50
      target_p95_ms: 5000.0
      adjustment_interval_s: 30
      warmup_seconds: 60
      timeout_auto_adjust: true
      min_timeout_s: 30
      max_timeout_s: 600
  ```
- El controller monitorea el p95 rolling de la latencia de upload S5 sobre `adjustment_interval_s`.
- Si `p95 < target_p95_ms`: agregar 1 worker (additive increase) hasta `max_threads`.
- Si `p95 > target_p95_ms`: cortar workers a la mitad (multiplicative decrease), acotado por `min_threads`.
- Durante `warmup_seconds`, no ocurren ajustes (dejar que el sistema se estabilice primero).
- Integración con §1 (lanes heavy/light): el controller ajusta el budget **total** de workers; la asignación de lane queda como responsabilidad del rebalanceador de §1.

### Placeholder MVP

`processing.auto_tune.enabled: false`. Los workers son estáticos. El campo del schema existe.

### Por qué se difirió

1. AIMD requiere medición confiable de p95, que requiere §2 + §3 para validar que los targets elegidos son sensatos.
2. AIMD interactúa no trivialmente con el rebalanceador de lanes de §1; acoplarlos al MVP es optimización prematura.
3. Workers estáticos son lo correcto para la primera migración: predecibles, debuggeables, fáciles de razonar.

### Criterios de aceptación para el cambio post-MVP

- [ ] El controller AIMD tiene tests unitarios para las ramas additive y multiplicative.
- [ ] Un test de integración simula un slowdown de red a mitad de un batch y verifica que los workers se contraigan apropiadamente.
- [ ] El toggle de config funciona como esperado (off → workers estáticos).
- [ ] Documentado en `docs/how-to/auto-tuning.md`.
- [ ] Co-diseño con §1 revisado: quién es dueño del budget total, quién es dueño de la asignación.

### Dependencias

- §1 (lanes heavy/light) — debería shippear primero o juntos. Blanda.
- §2 (métricas de sistema) — para validar el target elegido.

---

## §6. Pipelines Adicionales (CSV / AS400 trigger / Local Scan) — **SHIPPEADO en cambios 012, 014, 016**

> Promocionado fuera de post-MVP y entregado adelantado.
> `csv-trigger-pipeline` shippeó en cambio 012,
> `as400-trigger-pipeline` en cambio 014, `local-scan-pipeline` en
> cambio 016. Las cuatro pipelines productivas más `single-doc` están
> en el MVP. Ver `CHANGELOG.md` para el detalle por-cambio.

### Intención

El MVP shippea con `rvabrep-pipeline` y `single-doc`. Las tres pipelines restantes de `the project's domain spec §10.2` son aditivas — mismos stages, distinta estrategia `S0`.

### Pipelines diferidas

| Pipeline | Estrategia S0 | Caso de uso |
|----------|-------------|----------|
| `csv-trigger-pipeline` | Leer TriggerRecords desde archivo CSV | Batches controlados, testing, exports regulatorios |
| `as400-trigger-pipeline` | Correr un SQL configurable contra AS400 | Producción con queries de discovery custom |
| `local-scan-pipeline` | Walkear una carpeta, cross-referenciar RVABREP para metadatos | Archivos ya extraídos al disco |

### Diseño

Cada uno es un nuevo comando CLI que registra una estrategia `S0` distinta. Los stages restantes (`S1`–`S7`) y el modelo producer-consumer de batch quedan sin cambios.

La interfaz Strategy para `S0` es parte del MVP (Principio Constitucional I: la abstracción debe existir desde el día uno aunque solo se construya una implementación primero).

### Placeholder MVP

`rvabrep-pipeline` y `single-doc` shippean en el MVP. La interfaz `S0Strategy` está definida; solo `RVABREPDirectStrategy` y `NoOpStrategy` (para `single-doc`) están implementadas. Intentar invocar una pipeline diferida muestra un error claro apuntando a esta entrada del roadmap.

### Por qué se difirió

1. Construir cuatro pipelines simultáneamente diluye el foco del MVP. Una pipeline de punta a punta que demonstrablemente funcione vale más que cuatro a medio funcionar.
2. Cada pipeline adicional agrega su propia superficie de test de integración y validación pre-flight (salud de la fuente S0, etc.).
3. Dos de las tres (CSV, AS400) son variaciones simples de la fuente de trigger; una vez que la primera está sólida, el resto son cambios cortos.

### Criterios de aceptación para cada cambio de pipeline

- [ ] El comando CLI existe con soporte completo de flags (`--batch-size`, `--batch <id>`, `--stage`, `--from`, `--resume`, `--skip-doctor`).
- [ ] La implementación de estrategia `S0` pasa tests de contrato (devuelve `Iterable<TriggerRecord>` correctamente bajo varios inputs).
- [ ] Test de integración contra fixtures en `tests/fixtures/<pipeline-name>/`.
- [ ] El comando `doctor` valida la salud de la fuente de la nueva pipeline.
- [ ] `docs/how-to/<pipeline-name>.md` actualizado.

### Dependencias

- `rvabrep-pipeline` del MVP shippeada y estable.

---

## §7. Paralelismo Multi-Batch de Pipeline (>2 Batches en Vuelo) — **N=2 SHIPPEADO en cambio 028 (2026-05-11)**

> El overlap producer-consumer de dos batches (el modelo canónico
> "siempre dos lotes en vuelo") shippeó en cambio 028.
> Elevar el cap por encima de 2 (el rango original `1..5`) requiere
> un refactor de pool compartido por-chunk que está diferido a un
> cambio futuro. Ver `specs/028-multi-batch-orchestrator/`,
> `docs/how-to/multi-batch.md`, y
> `CHANGELOG.md [0.30.0]`.

### Intención

El overlap del MVP es **dos batches en vuelo**: uno preparándose (S0–S4), uno subiendo (S5). Una extensión natural es **N batches en vuelo** donde N > 2 — múltiples batches en stages distintos simultáneamente, acotado por memoria disponible y concurrencia configurada.

### Diseño

- Configuración: `processing.batches_in_flight` (default 2).
- Un scheduler despacha batches a un pool de "batch workers", cada uno corriendo la secuencia S0–S5 de un batch independientemente.
- Contención de recursos manejada por:
  - Worker pool S5 compartido (así la concurrencia total de upload no cambia)
  - Directorios temp separados por batch
  - Transacciones del tracking store por-batch aíslan el estado
- El TUI gana una tab "BATCHES" listando todos los batches en vuelo y su stage actual.

### Placeholder MVP

`batches_in_flight = 2` (el overlap producer-consumer). El campo de config existe pero valores > 2 levantan error de validación apuntando a esta entrada del roadmap.

### Por qué se difirió

1. El paralelismo multi-batch brilla solo a escala (muchos batches chicos), pero el target del MVP es corrección en un único batch grande.
2. El uso de memoria escala con batches en vuelo × archivo staged más grande en cada batch. Sin las métricas de §2, dimensionar esto es peligroso.
3. La semántica de fallo se vuelve más sucia (un batch fallando mientras otros tienen éxito — ¿qué significa "exit code"?).

### Criterios de aceptación

- [ ] `batches_in_flight` configurable.
- [ ] Stress test con 5 batches en vuelo sobre datos sintéticos.
- [ ] La tab BATCHES del TUI muestra todos los batches en vuelo con stage actual.
- [ ] El fallo de un batch no bloquea a los otros.
- [ ] Fórmula de presupuestado de memoria documentada en `docs/how-to/scaling.md`.

### Dependencias

- §2 (métricas de sistema) para el tuning del presupuesto de memoria.

---

## §8. Cuota de Bandwidth Por-Batch

### Intención

El actual `cmis.max_bandwidth_mbps` es un cap global compartido por todos los uploads en vuelo. Post-MVP, permitir cuotas por-batch para que batches de alta prioridad reciban más bandwidth y batches de baja prioridad reciban menos.

### Diseño

- Nueva config: `processing.bandwidth_policy: global | per_batch | priority_weighted`.
- `per_batch`: cada batch reserva `cmis.max_bandwidth_mbps / batches_in_flight`.
- `priority_weighted`: los batches llevan un valor de prioridad; bandwidth asignado proporcionalmente.
- El TUI muestra la asignación de bandwidth actual por-batch.

### Placeholder MVP

Solo política de bandwidth global. Las otras políticas erroran con un puntero al roadmap.

### Por qué se difirió

1. Requiere §7 (paralelismo multi-batch) para ser significativo.
2. La política de bandwidth interactúa con el token bucket compartido de §1; el diseño es co-dependiente.
3. La operación solo-batch no tiene uso para esto.

### Criterios de aceptación

- [ ] Las tres políticas configurables y testeadas contra límites de bandwidth reales en integración.
- [ ] El limitador de bandwidth queda correcto bajo todas las políticas (el total nunca excede el cap global).
- [ ] Documentado en `docs/how-to/bandwidth.md`.

### Dependencias

- §1 (lanes), §7 (multi-batch). Blandas.

---

## §9. Cache Cross-Batch de Metadatos (Tabla `document_cache`) — **SHIPPEADO en cambio 037 (2026-05-11)**

> Promocionado fuera de post-MVP y entregado como parte del cambio 037.
> Default off; habilitar vía `metadata.cache.enabled`. Respaldado en SQLite,
> TTL vía `metadata.cache.ttl_minutes` (default 60). CLI:
> `cmcourier cache stats|clear`. Eventos estructurados
> `document_cache_hit` / `_miss` alimentados a `cmcourier analyze`.
> Ver `specs/037-document-cache/`, `docs/how-to/document-cache.md`,
> y `CHANGELOG.md [0.38.0]`.

### Intención

El codebase viejo tiene una tabla `document_cache` (ver `the project's domain spec §9.2`) que almacena metadatos resueltos por `txn_num` así una re-corrida en un modo distinto reusa trabajo previo de resolución. Post-MVP, formalizar esto como un cache cross-mode así el mismo documento no paga costos de query AS400 dos veces.

### Diseño

- Después de que S3 (Resolución de Metadatos) tiene éxito para un documento, los metadatos resueltos se upsertean en `document_cache`.
- Antes de que S3 empiece, el cache se consulta; en hit (y TTL válido), S3 se saltea y se usan los metadatos cacheados.
- Invalidación del cache: TTL (`metadata_cache_ttl_minutes` de `the project's domain spec §6.6`, default 60) más `cmcourier cache clear --txn <num>` manual.
- Persiste a través de invocaciones de pipeline vía SQLite (o AS400 en entornos §4).

### Placeholder MVP

S3 siempre consulta fresh. La tabla `document_cache` se crea en el schema con un comentario diciendo que está reservada para §9. El pre-fetch en memoria de metadatos de `the project's domain spec §6.6` es MVP — eso es por-proceso, no cross-batch.

### Por qué se difirió

1. Agrega una capa de cache con su propia historia de corrección (TTL, invalidación, qué cuenta como "stale"). Demasiado riesgo para el MVP.
2. El pre-fetch en `§6.6` ya da la mayor parte del beneficio durante una sola corrida. El re-uso cross-batch es un delta más chico.
3. Sin observabilidad (§2/§3) no podemos cuantificar la ganancia.

### Criterios de aceptación

- [ ] Tabla `document_cache` poblada después de cada S3 exitoso.
- [ ] S3 short-circuita en hit del cache (dentro del TTL).
- [ ] Métricas de hit/miss del cache logueadas.
- [ ] Existen los comandos `cmcourier cache clear` y `cmcourier cache stats`.
- [ ] Expiración del TTL testeada con reloj sintético.

### Dependencias

- Ninguna dura.

---

## §10. Cosas Que Pueden Volverse Funcionalidades (Watchlist)

Estas no son promesas — son observaciones del codebase original o el diseño que pueden crecer hacia funcionalidades si operaciones reales las demandan:

1. **Uploads CMIS concurrentes contra la misma carpeta** — se ha observado que IBM CM throttlea cuando demasiados uploads apuntan a una carpeta. Puede necesitar límites de concurrencia por-carpeta si pega en producción. **— todavía abierto.**
2. ~~**Warm-up del connection pool al inicio del proceso**~~ — **SHIPPEADO en cambio 039** (`CHANGELOG.md [0.39.0]`, tagueado `POST-MVP §10.2`). El pool ahora warm-eaa cada conexión al inicio del proceso en lugar de warm-up JSESSIONID lazy por-thread.
3. ~~**Resume tras crash total del host en medio de S5**~~ — **SHIPPEADO en cambios 044 + 045.** 044 agregó detección de gap de stage a la lógica de resume; 045 cerró la kill-race exacta "archivo subido a CMIS pero la escritura de tracking no aterrizó" — en el HTTP 409 del retry el uploader busca el objeto por `cmis:name` y lo trata como `S5_DONE`. Caracterizado empíricamente vía la verificación live §H.1 de kill-en-medio-de-S5. Ver `CHANGELOG.md [0.47.0]` + `[0.48.0]`.
4. **Budgets de retry configurables por pipeline** — el MVP usa una política de retry global. Distintas pipelines pueden querer distintos budgets. **— todavía abierto.**
5. **Snapshot periódico de estado para batches muy largos** — para un batch que toma horas, snapshots intermedios aceleran el análisis post-mortem. **— todavía abierto.**
6. ~~**Auto-completion CLI**~~ — **SHIPPEADO.** `cmcourier completion {bash|zsh|fish}` emite el script de shell-completion. (PowerShell no soportado — un gap conocido, no está en esta watchlist.)

Restantes abiertos: **ítems 1, 4, 5** — ninguno con fecha dura; cada uno espera un dolor operacional real (lo más probable que aparezca durante la primera migración productiva) antes de ganarse su propio cambio `/sdd-new`.

---

## Cómo Evoluciona Este Documento

- **Promoción al MVP**: si un ítem diferido resulta requerido para la primera migración, moverlo de este archivo a un cambio `/sdd-new`. Notar el movimiento en `CHANGELOG.md`.
- **Democión / remoción**: si un ítem resulta una mala idea después del shakedown del MVP, removerlo y explicar por qué en una nota breve acá. No dropear silenciosamente.
- **Nuevos diferimientos**: cuando el trabajo del MVP haga aparecer una funcionalidad que debería diferirse, agregarla como una nueva sección numerada acá. La numeración es append-only — nunca reusar un número.
- **Versión**: este documento es no-versionado (es un roadmap, no un contrato). Reorganizaciones mayores se notan en `CHANGELOG.md`.

---

## Cross-References

- Constitución: `.specify/memory/constitution.md`
- Verdad de dominio: la spec de dominio del proyecto
- Arquitectura de stages: `docs/domain/the project's domain spec §10`
- Niveles de observabilidad: `docs/domain/the project's domain spec §17.4`
- Schema de tracking: `docs/domain/the project's domain spec §9`
- Changelog: `CHANGELOG.md`
