"""Tests de resilencia del writer thread del SQLiteTrackingStore (082).

Bug productivo: pre-082 el ``_writer_loop`` capturaba **solo
``sqlite3.Error``**. Si una excepción inesperada ocurría dentro del
loop, escapaba y mataba el daemon thread silenciosamente. Resultado:
todas las escrituras subsiguientes a la queue se perdían — los
uploads completaban, los eventos ``cmis_upload`` se logueaban, pero
``mark_stage_done`` quedaba colgado en la queue eternamente y los
docs quedaban en su último stage persistido (típicamente
``S4_DONE``) sin ningún error visible en los logs.

Post-082 el loop captura ``Exception`` global y mantiene el thread
vivo.
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

import pytest

from cmcourier.adapters.tracking.sqlite import SQLiteTrackingStore
from cmcourier.domain.models import MigrationRecord, StageStatus

pytestmark = pytest.mark.unit


def _make_record(txn: str = "TXN001", batch: str = "B1") -> MigrationRecord:
    return MigrationRecord(
        trigger_shortname="SHORT",
        trigger_cif="12345",
        trigger_system_id="SYS",
        rvabrep_txn_num=txn,
        rvabrep_file_name="DOC.pdf",
        batch_id=batch,
        status=StageStatus.S5_PENDING,
        created_at=datetime.now(),
    )


class TestWriterSurvivesUnexpectedException:
    """082: el writer thread tiene que sobrevivir cualquier exception
    no esperada y seguir drenando la queue."""

    def test_unexpected_exception_in_drain_does_not_kill_writer(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        store = SQLiteTrackingStore(db_path)
        try:
            store.start_batch(total_records=10)
            store.mark_stage_pending(_make_record(txn="BEFORE"), StageStatus.S5_PENDING)
            time.sleep(0.3)
            assert store._writer_thread.is_alive()

            # 082: inyectamos un RuntimeError una vez en ``_drain_batch``.
            # Pre-082 el outer loop no atrapaba esto y el thread moría.
            original_drain = store._drain_batch
            calls = {"n": 0}

            def boom_once() -> list:
                calls["n"] += 1
                if calls["n"] == 1:
                    raise RuntimeError("synthetic non-sqlite error")
                return original_drain()

            store._drain_batch = boom_once  # type: ignore[method-assign]
            time.sleep(0.5)  # let the writer hit the boom

            # 082: el thread debe seguir vivo.
            assert store._writer_thread.is_alive(), (
                "writer thread died after non-sqlite exception — 082 regression"
            )

            # Restaurar el método real y encolar una escritura.
            store._drain_batch = original_drain  # type: ignore[method-assign]
            store.mark_stage_pending(_make_record(txn="AFTER"), StageStatus.S5_PENDING)
            time.sleep(0.3)
            assert store._writer_thread.is_alive()
        finally:
            store.close()

    def test_writer_still_alive_after_normal_operations(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        store = SQLiteTrackingStore(db_path)
        try:
            store.start_batch(total_records=5)
            for i in range(5):
                store.mark_stage_pending(_make_record(txn=f"DOC{i}"), StageStatus.S5_PENDING)
            time.sleep(0.3)
            assert store._writer_thread.is_alive()
        finally:
            store.close()
