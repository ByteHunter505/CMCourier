"""Tests del progress de upload en tiempo real (077).

Pre-077 el ``_BandwidthSampler`` solo recibía datos cuando un upload
completaba. Para uploads grandes (500 MB+) la TUI no veía nada
durante varios segundos. Spec 077 agrega:

* ``_BandwidthSampler.record_progress(bytes_delta)`` — suma al
  bucket del segundo current.
* ``_BandwidthHandler.emit`` procesa eventos ``cmis_upload_progress``.
* El branch ``cmis_upload`` resta ``progress_bytes`` del total para
  evitar double-counting.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import pytest

from cmcourier.observability.metrics import (
    _BandwidthHandler,
    _BandwidthSampler,
)

pytestmark = pytest.mark.unit


def _make_record(
    *,
    kind: str,
    batch_id: str = "b1",
    **extra: Any,
) -> logging.LogRecord:
    """Construye un LogRecord como el que emite ``CmisUploader._emit_network``."""
    record = logging.LogRecord(
        name="cmcourier.metrics.network",
        level=logging.INFO,
        pathname=__file__,
        lineno=0,
        msg=kind,
        args=(),
        exc_info=None,
    )
    record.kind = kind  # type: ignore[attr-defined]
    record.batch_id = batch_id  # type: ignore[attr-defined]
    for k, v in extra.items():
        setattr(record, k, v)
    return record


class TestSamplerRecordProgress:
    """077: ``record_progress`` suma bytes al bucket del segundo current
    (a diferencia de ``record_upload`` que distribuye sobre una ventana
    al completion)."""

    def test_progress_adds_to_current_bucket(self) -> None:
        sampler = _BandwidthSampler()
        ts = time.time()
        # 1 MB de delta → 1 MB en el bucket de ese segundo.
        sampler.record_progress(1_048_576, ts=ts)
        # current_mbps() mira el bucket completo ANTERIOR. Para verificar
        # sin esperar 1 segundo, leemos directamente vía series().
        buckets_dict = {b[0]: b[1] for b in sampler.series(seconds=60)}
        # El sampler guarda en el segundo int(ts); series() es relativo
        # al "ahora", así que el bucket de hace 0..1 segundos debería
        # tener algo.
        total_in_window = sum(buckets_dict.values())
        # 1 MB = 1.048576 MB
        assert 1.04 <= total_in_window <= 1.06

    def test_progress_zero_or_negative_is_noop(self) -> None:
        sampler = _BandwidthSampler()
        sampler.record_progress(0)
        sampler.record_progress(-100)
        assert sampler.cumulative_bytes() == 0

    def test_progress_updates_cumulative_bytes(self) -> None:
        sampler = _BandwidthSampler()
        sampler.record_progress(500_000)
        sampler.record_progress(500_000)
        assert sampler.cumulative_bytes() == 1_000_000

    def test_progress_thread_safe(self) -> None:
        sampler = _BandwidthSampler()
        n_threads = 10
        deltas_per_thread = 100
        bytes_per_call = 1024

        def hammer() -> None:
            for _ in range(deltas_per_thread):
                sampler.record_progress(bytes_per_call)

        threads = [threading.Thread(target=hammer) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        expected = n_threads * deltas_per_thread * bytes_per_call
        assert sampler.cumulative_bytes() == expected


class TestHandlerProcessesProgressEvents:
    """077: ``_BandwidthHandler`` reconoce el nuevo kind
    ``cmis_upload_progress`` y delega a ``record_progress``."""

    def test_handler_routes_progress_event_to_sampler(self) -> None:
        sampler = _BandwidthSampler()
        handler = _BandwidthHandler(sampler, batch_id="b1")
        record = _make_record(
            kind="cmis_upload_progress",
            batch_id="b1",
            bytes_delta=2_097_152,  # 2 MB
        )
        handler.emit(record)
        assert sampler.cumulative_bytes() == 2_097_152

    def test_handler_drops_progress_with_wrong_batch_id(self) -> None:
        sampler = _BandwidthSampler()
        handler = _BandwidthHandler(sampler, batch_id="b1")
        record = _make_record(
            kind="cmis_upload_progress",
            batch_id="OTHER",
            bytes_delta=1_000_000,
        )
        handler.emit(record)
        assert sampler.cumulative_bytes() == 0

    def test_handler_drops_progress_with_missing_bytes_delta(self) -> None:
        sampler = _BandwidthSampler()
        handler = _BandwidthHandler(sampler, batch_id="b1")
        record = _make_record(kind="cmis_upload_progress", batch_id="b1")
        handler.emit(record)
        assert sampler.cumulative_bytes() == 0


class TestCompletionEventSubtractsProgressBytes:
    """077: el branch ``cmis_upload`` (completion) resta los
    ``progress_bytes`` ya reportados, para evitar double-counting con
    los eventos progress previos."""

    def test_completion_with_progress_bytes_only_records_residual(self) -> None:
        sampler = _BandwidthSampler()
        handler = _BandwidthHandler(sampler, batch_id="b1")
        # Simulamos: durante el upload se emitieron 8 progress events
        # de 1 MB cada uno → 8 MB ya reportados.
        for _ in range(8):
            handler.emit(
                _make_record(
                    kind="cmis_upload_progress",
                    batch_id="b1",
                    bytes_delta=1_048_576,
                )
            )
        # El completion event reporta size=10MB con progress_bytes=8MB.
        # El sampler debe agregar solo el residual de 2 MB.
        handler.emit(
            _make_record(
                kind="cmis_upload",
                batch_id="b1",
                size_bytes=10_485_760,  # 10 MB
                progress_bytes=8_388_608,  # 8 MB
                duration_ms=1000,
            )
        )
        # Total = 8 MB (progress) + 2 MB (residual) = 10 MB.
        assert sampler.cumulative_bytes() == 10_485_760

    def test_completion_without_progress_works_as_pre_077(self) -> None:
        # Upload chico (sin progress events) — el completion sigue
        # con la lógica 069 de distribuir el size completo.
        sampler = _BandwidthSampler()
        handler = _BandwidthHandler(sampler, batch_id="b1")
        handler.emit(
            _make_record(
                kind="cmis_upload",
                batch_id="b1",
                size_bytes=500_000,
                duration_ms=100,
                # sin progress_bytes
            )
        )
        assert sampler.cumulative_bytes() == 500_000

    def test_completion_when_all_bytes_already_reported_is_noop(self) -> None:
        # Edge: si por algún motivo progress_bytes == size_bytes
        # (alineación exacta de threshold), el completion no agrega
        # nada. cumulative_bytes ya está al día por los progress events.
        sampler = _BandwidthSampler()
        handler = _BandwidthHandler(sampler, batch_id="b1")
        handler.emit(
            _make_record(
                kind="cmis_upload_progress",
                batch_id="b1",
                bytes_delta=10_485_760,  # 10 MB
            )
        )
        before = sampler.cumulative_bytes()
        handler.emit(
            _make_record(
                kind="cmis_upload",
                batch_id="b1",
                size_bytes=10_485_760,
                progress_bytes=10_485_760,
                duration_ms=1000,
            )
        )
        # Sin cambio entre antes y después del completion.
        assert sampler.cumulative_bytes() == before == 10_485_760


class TestHandlerOnlyRespondsToKnownKinds:
    """077: el handler ignora kinds desconocidos (otros eventos de
    network como ``as400_query`` o ``cmis_request``)."""

    def test_handler_ignores_unrelated_kind(self) -> None:
        sampler = _BandwidthSampler()
        handler = _BandwidthHandler(sampler, batch_id="b1")
        handler.emit(_make_record(kind="as400_query", batch_id="b1"))
        handler.emit(_make_record(kind="cmis_request", batch_id="b1"))
        assert sampler.cumulative_bytes() == 0
