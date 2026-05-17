"""Tests de la semántica Mbps del TokenBucket (081).

Pre-081 ``TokenBucket(mbps=N).consume(...)`` interpretaba ``N`` como
megabytes/s (``rate = N × 1_000_000``) a pesar de que el nombre del
field y del parámetro decía ``mbps`` (megabits/s, convención estándar
de networking). El operador configuraba ``cmis.max_bandwidth_mbps: 50``
esperando 50 Mbps (6.25 MB/s) y obtenía 50 MB/s (400 Mbps), 8x más
permisivo de lo que pedía.

Post-081 ``mbps`` se interpreta como megabits/s reales — la conversión
interna es ``rate = mbps × 125_000`` (1 Mbps = 125_000 bytes/s).
"""

from __future__ import annotations

import time

import pytest

from cmcourier.adapters.upload.cmis_uploader import TokenBucket

pytestmark = pytest.mark.unit


class TestMbpsSemantics:
    def test_8_mbps_equals_1_megabyte_per_second(self) -> None:
        """8 Mbps = 8_000_000 bits/s = 1_000_000 bytes/s = 1 MB/s."""
        bucket = TokenBucket(mbps=8.0)
        # Verificar la tasa interna directa: 1 MB/s.
        assert bucket._rate == 1_000_000.0

    def test_80_mbps_equals_10_megabytes_per_second(self) -> None:
        """80 Mbps = 10 MB/s."""
        bucket = TokenBucket(mbps=80.0)
        assert bucket._rate == 10_000_000.0

    def test_1_mbps_equals_125000_bytes_per_second(self) -> None:
        """1 Mbps = 125_000 bytes/s exactos."""
        bucket = TokenBucket(mbps=1.0)
        assert bucket._rate == 125_000.0

    def test_zero_disables_throttling(self) -> None:
        bucket = TokenBucket(mbps=0.0)
        assert not bucket._enabled
        assert bucket._rate == 0.0


class TestThrottlingBehavesAtMbpsRate:
    def test_8mbps_drains_1mb_in_about_1_second(self) -> None:
        # 8 Mbps = 1 MB/s. 1 MB tarda ~1 s.
        bucket = TokenBucket(mbps=8.0)
        start = time.monotonic()
        for _ in range(10):
            bucket.consume(100_000)
        elapsed = time.monotonic() - start
        assert 0.7 < elapsed < 1.5, elapsed
