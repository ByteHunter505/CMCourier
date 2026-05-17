# 081 — `max_bandwidth_mbps` honra la convención de networking (Mbps reales)

## Por qué

Bug de naming + semántica descubierto durante las pruebas
productivas. El field ``cmis.max_bandwidth_mbps`` se llama "mbps"
(convención estándar de networking = **megabits per second**) pero
el código lo trataba como **megabytes per second** (MB/s):

```python
# Pre-081 en TokenBucket.__init__:
self._rate = mbps * 1_000_000.0   # bytes/s — asume MB/s, no Mbps
```

Si el operador configuraba ``max_bandwidth_mbps: 50`` esperando
**50 Mbps = 6.25 MB/s**, el código throttleaba a **50 MB/s = 400 Mbps**,
**8x más permisivo** que lo pedido. El throttle prácticamente no
aplicaba en links productivos típicos.

Y peor: en spec 079 yo agregué la detección de link speed via
``psutil.net_if_stats()`` que devuelve **Mbps reales**, y la
dividí por 8 para mostrarla en MB/s en el chart Y. Eso era correcto.
Pero el ceiling del config (``max_bandwidth_mbps`` del YAML) no se
dividía — quedaba 8x sobreestimado en el chart Y vs el sampler en MB/s.

## Qué

### Cambios

1. **``TokenBucket.__init__``**: cambia ``self._rate = mbps × 1_000_000``
   por ``self._rate = mbps × 125_000``. (1 Mbps = 1_000_000 bits/s =
   125_000 bytes/s.)
2. **``TUIDataProvider``**: divide ``cmis_config.max_bandwidth_mbps``
   por 8 para obtener MB/s antes de cachear como
   ``self._bandwidth_ceiling_mbps``. El chart Y queda consistente
   con el sampler que mide en MB/s.

### Tests

* 5 nuevos en ``test_bandwidth_mbps_semantics.py`` verifican la
  conversión exacta: 8 Mbps = 1 MB/s, 80 Mbps = 10 MB/s, 1 Mbps =
  125_000 bytes/s, throttling real respeta la tasa Mbps.
* Tests existentes de ``TestTokenBucket`` y ``TestBandwidthLimiter``
  actualizados: los valores ``mbps=0.5``, ``mbps=1.0`` se cambian a
  ``mbps=4.0`` y ``mbps=8.0`` respectivamente para conservar el
  throughput de prueba (0.5 MB/s y 1 MB/s).
* Test de ``test_data_provider`` actualizado: ``50.0`` → ``6.25``
  para el ceiling (50 Mbps / 8).

## Criterios de aceptación

1. ``TokenBucket(mbps=8.0)._rate == 1_000_000.0`` (8 Mbps = 1 MB/s).
2. ``TokenBucket(mbps=1.0)._rate == 125_000.0``.
3. Throttling de 1 MB con ``mbps=8.0`` tarda ~1 s (no ~0.125 s ni
   ~8 s).
4. Chart Y ceiling cuando ``max_bandwidth_mbps=50`` → 6.25 MB/s.
5. ``pytest -m unit`` pasa.

## Riesgos

* **Breaking change semántico**. Operadores que tenían
  ``max_bandwidth_mbps: N`` y obtenían N MB/s post-081 obtienen
  N Mbps = N/8 MB/s — 8x más estricto. El operador productivo
  tiene que **ajustar su YAML × 8** si quiere mantener el throughput
  real. Documentado en CHANGELOG con la fórmula de migración.
* **Nomenclatura interna inconsistente**: ``_BandwidthSampler``
  todavía expone ``current_mbps()`` / ``peak_mbps()`` que devuelven
  MB/s. Esos nombres siguen siendo confusos pero su renombre toca
  más superficie (callsites del TUI). Pendiente para spec futura
  si genera más confusión.

## Notas

Spec 080 (el fix del ``fileno()`` del ``BandwidthLimiter``) y
081 son independientes pero relacionadas. 080 desbloqueó el path
del throttle activo (era 100% broken antes); 081 corrige la
semántica del valor que el operador configura. Sin 080 el
throttle nunca aplicaba; sin 081 cuando aplicaba era 8x más
permisivo.
