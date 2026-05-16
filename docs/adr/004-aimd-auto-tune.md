> [← Volver al índice](../INDEX.md) · [ADRs](README.md)

# ADR-004: AIMD multiplicativo para auto-tune del pool S5

- **Estado**: Aceptado y vigente
- **Fecha**: 2026-05-15
- **Spec(s) relacionadas**: 025 (AIMD inicial), 043 (AIMD multi-batch p95), 061 (guardia `min_samples`), 068 (recalibración multiplicative-increase + soft-halve)
- **Versión donde se shipping**: 0.27.0 (initial AIMD); 0.70.0 (recalibración 068)

## Contexto

El stage S5 (upload CMIS) es el bottleneck dominante de la pipeline en producción. Los recursos que limitan su throughput están afuera de nuestro control directo:

- Ancho de banda corporativo del banco (compartido con otros sistemas, sin SLA dedicado).
- Latencia del Alfresco/IBM CM staging (TLS handshake, commit del repositorio, GC pauses del servidor).
- Capacidad de respuesta del cluster CM bajo carga real.

Fijar `cmis.workers` a un número estático era brutal en ambas direcciones:

- **Underprovisioned**: con `workers=8` contra un link rápido y un CM responsivo, el pipeline corría a una fracción de la capacidad disponible — desperdiciamos horas.
- **Overprovisioned**: con `workers=32` contra un link saturado o un CM que tardaba en commitear, los timeouts se disparaban y los retries amplificaban el problema (más cargas paralelas atrás de las que ya estaban timing-out → más timeouts).

La spec 025 introdujo el **AIMD** (Additive-Increase / Multiplicative-Decrease) — el mismo algoritmo que TCP usa para congestion control, adaptado a un pool de workers de upload. El controller corre en un thread daemon, observa la p95 de S5 contra un target configurable, y resize-ea el pool en consecuencia.

El esquema inicial era el canónico TCP: `+1 worker` cuando p95 < 0.8× target; `÷2` cuando p95 > 1.2× target. Bien conocido, bien estudiado. Pero la calibración no resistió la realidad de cargas con archivos pesados (10-30 MB): en una corrida `mockfiles-mixed` contra Alfresco staging, AIMD nunca alcanzaba su ceiling, quedaba clavado en `pool capacity 4-8` con `max_threads=50`. Un único outlier (40s, server commit + TLS re-handshake) tripleaba el umbral y `÷2`-aba el pool. La recuperación a +1 por tick tomaba ~6 minutos por halve.

## Decisión

Adoptamos AIMD como controlador de feedback **y** lo recalibramos con tres knobs configurables (spec 068):

1. **`growth_factor: float = 1.25`** (rango 1.0–4.0) — multiplicador por grow tick. El step es `max(current + 1, ceil(current × growth_factor))`. Con 1.25, sube de 6 → 50 workers en ~10 ticks (2.5 min a 15s/tick) vs ~11 min del esquema `+1` original. Setear `1.0` recupera el shape aditivo `+1` por compatibilidad.
2. **`halve_factor: float = 0.75`** (rango 0.05–1.0) — multiplicador por halve tick. El step es `max(min_threads, ceil(current × halve_factor))`. Default 0.75 baja un 25% por tick en lugar del 50% original. Un halve falso-positivo ya no cuesta 6 minutos de recuperación.
3. **`halve_threshold_ratio: float = 1.5`** (rango 1.05–10.0) — multiplicador de `target_p95_ms` por encima del cual disparamos halve. Default 1.5 da más tolerancia para la varianza natural de p95 con archivos pesados (vs el 1.2 original).

Adicionalmente, spec 061 agregó `min_samples: int = 20` como guard de cold-start: AIMD short-circuit-ea a `insufficient_data` si el recorder tiene < N samples. Esto previene que un único outlier de cold-connection (8-12s de TCP+TLS+JSESSIONID) sea visto como p95 cuando todavía hay 5 muestras.

El renombre semántico que viene con 068 — de "AI/MD" a "MI (Multiplicative-Increase) / Soft halve" — refleja honestamente que el algoritmo ya no es el AIMD libro de texto. La etiqueta de acción cambió de `"+1"` a `"+N"` en logs y TUI.

## Consecuencias

### Positivas

- **Auto-tune real para cargas mixtas.** El pipeline se adapta solo al link disponible. El operador no necesita re-tunear `cmis.workers` por entorno; AIMD lo hace en runtime.
- **Crecimiento rápido cuando hay capacidad.** El multiplicative-increase llega al ceiling de `max_threads=50` en ~3 min en producción, no en 11.
- **Halve suave evita oscilación.** Un único outlier no derrumba el pool. Los outliers reales sostenidos siguen disparando halves; los falsos positivos cuestan 25% por tick en lugar del 50% catastrófico.
- **Knobs operativos para casos extremos.** Si un operador encuentra un perfil donde el shape original era mejor, puede setear `growth_factor=1.0, halve_factor=0.5, halve_threshold_ratio=1.2` y recuperar exactamente pre-068. Cero pérdida de capacidad.
- **`min_samples` evita decisiones con datos malos.** Spec 061 cierra un bug reproducible donde AIMD halve-aba determinísticamente en el primer chunk.

### Negativas / Tradeoffs

- **No es AIMD canónico.** El paper de TCP asume `+1 / ÷2` por una razón teórica (fairness en links compartidos). Nuestra recalibración rompe esa propiedad. Aceptable porque no estamos compartiendo congestion control con otros procesos AIMD-aware — somos el único cliente.
- **Tres knobs nuevos amplían la superficie de configuración.** El operador tiene que entender qué hace cada uno o aceptar los defaults. Los defaults (1.25 / 0.75 / 1.5) están bien-tuneados para cargas mixtas reales; pero ajustarlos requiere experiencia.
- **`min_samples=20` retrasa la primera decisión.** En un dataset chico (< 20 docs), AIMD nunca se activa. Eso es deseable (la decisión sería ruido), pero hay que documentarlo.
- **Acoplamiento entre AIMD y `LaneController`.** Cuando heavy/light lanes están activas, AIMD opera contra el **total budget** y el `LaneController` distribuye internamente (ver [ADR-006](006-heavy-light-lanes.md)). Spec 070 unificó el controller entre batched y streaming para resolver un bug donde había dos instancias compitiendo.

### Neutras

- **`timeout_auto_adjust: True`** acompaña al worker resize. Cuando AIMD halve-a, también dobla el timeout de upload (cap a `max_timeout_s=600`). Cuando crece, lo divide entre 2 (floor a `min_timeout_s=30`). Lógica acoplada por diseño: si la red está mal, queremos menos workers Y más paciencia.

## Alternativas consideradas

- **PID controller (Proportional-Integral-Derivative).** Overkill: tres parámetros más para tunear, dinámicas oscilatorias que requieren expertise en sistemas de control. AIMD da el 95% del valor con un kink más simple.
- **AIMD aditivo (`+1` original).** Lo probamos en producción durante meses y falló para cargas heavy. El costo del halve falso-positivo era demasiado alto.
- **AIMD puro multiplicativo (sin floor de `current + 1`).** Sin el floor, `current × 1.25` con `current=1` da `1.25` que se cast-ea a `1` → cero crecimiento. El `max(current + 1, ceil(current × growth_factor))` garantiza progreso al menos lineal.
- **Estado externo (operador re-tunea entre runs).** Es lo que teníamos pre-025. No escala: cada entorno cambia, cada hora del día cambia, cada workload cambia.
- **Bandit (multi-armed) sobre `workers` discreto.** Más sofisticado, requiere explorar (sub-óptimo durante la exploración). AIMD aprovecha la estructura del problema (monotónico en una región y catastrófico en la otra) sin esa fase de exploración.

## Ver también

- [Explanation: AIMD auto-tuning](../explanation/aimd-auto-tuning.md)
- [Spec 025 — TUI workers + autotune](../../specs/025-tui-workers-autotune/)
- [Spec 043 — AIMD multi-batch p95](../../specs/043-aimd-multibatch-p95/)
- [Spec 061 — guardia min_samples](../../specs/061-aimd-min-samples/)
- [Spec 068 — recalibración agresiva](../../specs/068-aimd-aggressive-scaling/)
- [ADR-006: heavy/light lanes](006-heavy-light-lanes.md)
