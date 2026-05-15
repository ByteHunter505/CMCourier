# 061 — Guard de min-samples para AIMD: dejar de halvear ante outlier-con-pocas-muestras

## Por qué

El operador reportó que el controlador AIMD **siempre** emite
`halve` poco después de que arranca el upload de S5 del primer
chunk. Repro verificado — y es determinístico.

### La causa

El stage S5 graba duraciones per-doc en un `MetricsRecorder`
per-chunk. `current_stage_p95("S5")` devuelve el p95
nearest-rank de las muestras que tenga. El AIMD compara ese
p95 contra `1.2 × target_p95_ms` y halvea la cantidad de
workers cuando lo cruza.

Con **pocas muestras** y un **outlier**, el p95 nearest-rank
**pasa a ser el outlier**. Verificación empírica (target=6000,
halvear cuando p95 > 7200):

```
6 uploads (5 normales 1.5s, 1 handshake 12s) → p95 = 12000ms  → HALVE
3 uploads (2 normales 1.5s, 1 handshake  8s) → p95 =  8000ms  → HALVE
1 muestra sola de 10s                          → p95 = 10000ms  → HALVE
```

El primer chunk produce confiablemente ese outlier:

1. `warm_connection_pool(cmis.workers)` calienta solo la
   cuenta inicial de workers de conexiones HTTP.
2. El warmup de AIMD termina a los 60 s; el primer tick
   post-warmup dispara.
3. Para entonces solo un puñado de uploads completaron; al
   menos uno de los primeros uploads pagó el handshake
   TCP+TLS+JSESSIONID (conexión fría, `race condition`, o la
   primera conexión del día al server).
4. p95 nearest-rank con N chico y un pico grande = el pico.
5. AIMD lee "p95 = 12000 ms", piensa que el server está
   prendido fuego, y halvea el pool a `current_workers // 2`.

Los chunks subsiguientes no sufren — las conexiones quedan
calientes en el pool, todas las muestras son uniformes, sin
outlier, p95 ≈ p50 ≈ 1.5 s.

El bug no está en ningún commit específico — es una propiedad
del algoritmo AIMD interactuando con un régimen de pocas
muestras. Las implementaciones estándar de AIMD gateean las
decisiones sobre un conteo mínimo de muestras exactamente por
esta razón.

## Qué

### 1. Configuración — `min_samples`

`AutoTuneConfig` gana un campo nuevo:

```python
min_samples: int = Field(default=20, ge=1)
```

Default `20` es suficiente para que un solo outlier de 30
segundos entre ~20 muestras normales de 1.5 segundos no pueda
dominar el p95 — y suficientemente chico para que AIMD
todavía reaccione rápido a carga sostenida genuina.

### 2. `decide()` — nueva rama de cortocircuito

`decide()` toma un nuevo argumento keyword `sample_count: int`
y devuelve
`Decision(action="insufficient_data", workers=current, timeout_s=current)`
**antes** de la comparación de banda cuando
`sample_count < config.min_samples`.

La nueva acción se sienta al lado de `"warmup"`
semánticamente: representa "escuchamos la pregunta pero no
tenemos suficiente data para contestar responsablemente". Como
`"warmup"`, NO actualiza `last_decision` en el controlador,
así la línea "last move" de la TUI muestra la decisión **real**
más reciente, no el stall temporario.

### 3. Firma del provider — tupla

`p95_provider: Callable[[], float]` pasa a
`p95_provider: Callable[[], tuple[float, int]]` — devuelve
`(p95_ms, sample_count)`. Tanto el provider de tiempo de
construcción en `StagedPipeline.__init__` como el target de
swap `MultiBatchOrchestrator._upload_p95_observer` devuelven
la tupla.

`MetricsRecorder` gana
`current_stage_p95_with_count(stage) -> tuple[float, int]`
que lee el dict `_StageBucket.summary()` y devuelve
`(p95_ms, count)` — el lock ya se sostiene dentro de
`summary()` así que es atómico para ambos campos.

### 4. Los 3 YAMLs de staging

`sample/config-staging-rvabrep.yaml`,
`sample/config-staging-rvabrep-mega-heavy.yaml`,
`sample/config-staging-rvabrep-frequent-heavy-lanes.yaml` —
agregar `min_samples: 20` bajo `cmis.auto_tune` con un
comentario apuntando a esta spec.

## Fuera de alcance

- Cambiar `_percentile` (el algoritmo nearest-rank). El
  percentil mismo es correcto; el bug es usarlo en muy pocas
  muestras.
- p95 trimmed/winsorized en el analyzer (`analyze batch`). El
  p95 reportado se queda puro; solo el AIMD gateea sobre
  min_samples.
- Remover o acortar el guard `warmup_seconds` existente. Los
  dos guards se capean: warmup gateea sobre tiempo
  transcurrido, min_samples gateea sobre conteo de muestras.
  Los dos son necesarios.

## Criterios de aceptación

- `AutoTuneConfig.min_samples` default a 20, rechaza `< 1`.
- `decide(..., sample_count=0, ...)` →
  `Decision(action="insufficient_data", ...)`
  independientemente de `observed_p95_ms`. Un test lo clava.
- `decide(..., sample_count=5, observed_p95_ms=12000, ...)`
  con `min_samples=20` → `"insufficient_data"`, NO `"halve"`.
  **Test de regresión nombrado para el bug**.
- `decide(..., sample_count=20, observed_p95_ms=12000, ...)`
  con `min_samples=20` → `"halve"`. El guard es un piso, no
  un techo.
- `AutoTuneController._tick` trata la nueva acción como
  `"warmup"` — sin mutación de `last_decision`, sin llamada a
  `on_pool_resize` / `on_timeout_change` (los workers/timeout
  se quedan iguales).
- `MetricsRecorder.current_stage_p95_with_count("S5")`
  devuelve `(0.0, 0)` para un stage vacío; la tupla correcta
  para uno poblado.
- Los 3 YAMLs de staging llevan `min_samples: 20` bajo
  `auto_tune`.
- Suite completa unit + integration verde; mypy + ruff
  limpios.
- `CHANGELOG.md [0.63.0]`; `pyproject.toml` 0.62.0 → 0.63.0;
  `config-reference.yaml` documenta el campo.

## Notas sobre estrategia de tests

El test de regresión es la piedra angular: `decide` con
`sample_count=5` + `observed_p95_ms` alto NO debe halvear
bajo el default `min_samples=20`. Este es el test que habría
agarrado el bug. Los tests AIMD existentes reciben un
`sample_count=100` constante chico (bien arriba del default
min) así sus aserciones sobre `"halve" / "+1" / "noop"`
siguen sosteniéndose.
