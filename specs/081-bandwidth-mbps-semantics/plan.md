# 081 — Plan

Cambios:
1. `TokenBucket.__init__`: rate = mbps × 125_000 (Mbps → bytes/s).
2. `TUIDataProvider`: dividir config mbps por 8 para el ceiling del chart.
3. Tests: ajustar viejos, agregar nuevos.

Migración para operadores:
- Si tenías `max_bandwidth_mbps: N` y querías ese N como MB/s,
  cambialo a `max_bandwidth_mbps: N*8`.
- Si lo querías como Mbps todo el tiempo, ya queda correcto sin cambio.
