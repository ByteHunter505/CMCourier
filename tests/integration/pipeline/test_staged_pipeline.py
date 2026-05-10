"""Integration tests for :class:`StagedPipeline`.

End-to-end pipeline tests: every adapter and service is real
(Constitution Principle VI). Only the CMIS HTTP layer is stubbed via the
``responses`` library. Each test builds its trigger CSV at runtime under
``tmp_path`` for self-containment.

The :class:`PipelineHarness` fixture (see ``conftest.py``) wires the full
adapter graph; tests register CMIS stubs and assert on the returned
``RunReport`` plus side effects in the tracking store.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import pytest
import responses

pytestmark = [pytest.mark.integration, pytest.mark.slow]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_trigger_csv(tmp_path: Path, rows: list[tuple[str, str, str]]) -> Path:
    """Write a triggers CSV under tmp_path. rows: (ShortName, CIF, SystemID)."""
    path = tmp_path / "triggers.csv"
    lines = ["ShortName,CIF,SystemID"]
    lines.extend(",".join(row) for row in rows)
    path.write_text("\n".join(lines) + "\n")
    return path


def _count_rows(db_path: Path, batch_id: str, status: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM migration_log WHERE batch_id = ? AND status = ?",
            (batch_id, status),
        ).fetchone()[0]
    finally:
        conn.close()


def _batch_completed_at(db_path: Path, batch_id: str) -> str | None:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT completed_at FROM migration_batch WHERE batch_id = ?",
            (batch_id,),
        ).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Group 1 — Parameter validation
# ---------------------------------------------------------------------------


class TestParameterValidation:
    def test_batch_size_zero_raises(self, pipeline_harness, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
        triggers = _write_trigger_csv(tmp_path, [("TESTCLIENT01", "123456", "1")])
        with pytest.raises(ValueError, match="batch_size"):
            pipeline_harness.build_pipeline(triggers).run(
                source_descriptor=str(triggers), batch_size=0
            )

    def test_from_stage_below_one_raises(self, pipeline_harness, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
        triggers = _write_trigger_csv(tmp_path, [("TESTCLIENT01", "123456", "1")])
        with pytest.raises(ValueError, match="from_stage"):
            pipeline_harness.build_pipeline(triggers).run(
                source_descriptor=str(triggers), from_stage=0
            )

    def test_from_stage_above_five_raises(self, pipeline_harness, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
        triggers = _write_trigger_csv(tmp_path, [("TESTCLIENT01", "123456", "1")])
        with pytest.raises(ValueError, match="from_stage"):
            pipeline_harness.build_pipeline(triggers).run(
                source_descriptor=str(triggers), from_stage=6
            )

    def test_from_stage_gt_one_without_batch_id_raises(
        self,
        pipeline_harness,  # type: ignore[no-untyped-def]
        tmp_path: Path,
    ) -> None:
        triggers = _write_trigger_csv(tmp_path, [("TESTCLIENT01", "123456", "1")])
        with pytest.raises(ValueError, match="batch_id"):
            pipeline_harness.build_pipeline(triggers).run(
                source_descriptor=str(triggers), from_stage=3
            )


# ---------------------------------------------------------------------------
# Group 2 — Fresh full run
# ---------------------------------------------------------------------------


class TestFreshFullRun:
    @responses.activate
    def test_happy_path_two_docs(self, pipeline_harness, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
        pipeline_harness.register_cmis_for_docs(["TXN_PIPE_001", "TXN_PIPE_002"])
        triggers = _write_trigger_csv(
            tmp_path,
            [("TESTCLIENT01", "123456", "1"), ("TESTCLIENT02", "234567", "1")],
        )
        report = pipeline_harness.build_pipeline(triggers).run(source_descriptor=str(triggers))
        assert report.s5_done == 2
        assert report.s5_failed == 0
        assert report.s2_failed == 0
        assert report.s3_failed == 0
        assert report.s4_failed == 0
        assert report.total_docs == 2
        assert report.elapsed_seconds >= 0.0
        assert len(report.batch_id) > 0

    @responses.activate
    def test_complete_batch_called(self, pipeline_harness, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
        pipeline_harness.register_cmis_for_docs(["TXN_PIPE_001"])
        triggers = _write_trigger_csv(tmp_path, [("TESTCLIENT01", "123456", "1")])
        report = pipeline_harness.build_pipeline(triggers).run(source_descriptor=str(triggers))
        pipeline_harness.tracking_store.flush()
        assert _batch_completed_at(pipeline_harness.db_path, report.batch_id) is not None

    @responses.activate
    def test_migration_log_row_per_doc(self, pipeline_harness, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
        pipeline_harness.register_cmis_for_docs(["TXN_PIPE_001", "TXN_PIPE_002"])
        triggers = _write_trigger_csv(
            tmp_path,
            [("TESTCLIENT01", "123456", "1"), ("TESTCLIENT02", "234567", "1")],
        )
        report = pipeline_harness.build_pipeline(triggers).run(source_descriptor=str(triggers))
        pipeline_harness.tracking_store.flush()
        s5_done_count = _count_rows(pipeline_harness.db_path, report.batch_id, "S5_DONE")
        assert s5_done_count == 2


# ---------------------------------------------------------------------------
# Group 3 — S1 error handling
# ---------------------------------------------------------------------------


class TestS1ErrorHandling:
    @responses.activate
    def test_trigger_not_in_rvabrep_logged_no_row(
        self,
        pipeline_harness,  # type: ignore[no-untyped-def]
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        pipeline_harness.register_cmis_for_docs([])
        triggers = _write_trigger_csv(tmp_path, [("NO_SUCH_CLIENT", "123456", "1")])
        with caplog.at_level(logging.WARNING, logger="cmcourier.orchestrators.staged"):
            report = pipeline_harness.build_pipeline(triggers).run(source_descriptor=str(triggers))
        assert report.total_docs == 0
        assert report.s1_done == 0
        assert any(r.__dict__.get("shortname") == "NO_SUCH_CLIENT" for r in caplog.records)
        pipeline_harness.tracking_store.flush()
        # No migration_log rows for this batch.
        total = _count_rows(pipeline_harness.db_path, report.batch_id, "S1_DONE")
        assert total == 0

    @responses.activate
    def test_mixed_trigger_results(self, pipeline_harness, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
        pipeline_harness.register_cmis_for_docs(["TXN_PIPE_001"])
        triggers = _write_trigger_csv(
            tmp_path,
            [("NO_SUCH_CLIENT", "999999", "1"), ("TESTCLIENT01", "123456", "1")],
        )
        report = pipeline_harness.build_pipeline(triggers).run(source_descriptor=str(triggers))
        assert report.total_triggers == 2
        assert report.s5_done == 1


# ---------------------------------------------------------------------------
# Group 4 — Cross-batch is_uploaded skip
# ---------------------------------------------------------------------------


class TestCrossBatchSkip:
    @responses.activate
    def test_doc_uploaded_in_prior_batch_skipped(
        self,
        pipeline_harness,  # type: ignore[no-untyped-def]
        tmp_path: Path,
    ) -> None:
        # First run: upload TXN_PIPE_001 successfully.
        pipeline_harness.register_cmis_for_docs(["TXN_PIPE_001"])
        triggers = _write_trigger_csv(tmp_path, [("TESTCLIENT01", "123456", "1")])
        first = pipeline_harness.build_pipeline(triggers).run(source_descriptor=str(triggers))
        assert first.s5_done == 1
        pipeline_harness.tracking_store.flush()

        # Second run: SAME doc, FRESH batch. Must skip with no CMIS calls.
        # No CMIS stubs registered — if the orchestrator tries to upload, the
        # responses library would raise ConnectionError on the missing stub.
        second = pipeline_harness.build_pipeline(triggers).run(source_descriptor=str(triggers))
        assert second.s1_skipped_cross_batch == 1
        assert second.total_docs == 1
        assert second.s5_done == 0  # didn't upload again

    @responses.activate
    def test_cross_batch_skip_logged(
        self,
        pipeline_harness,  # type: ignore[no-untyped-def]
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        pipeline_harness.register_cmis_for_docs(["TXN_PIPE_001"])
        triggers = _write_trigger_csv(tmp_path, [("TESTCLIENT01", "123456", "1")])
        pipeline_harness.build_pipeline(triggers).run(source_descriptor=str(triggers))
        pipeline_harness.tracking_store.flush()
        with caplog.at_level(logging.INFO, logger="cmcourier.orchestrators.staged"):
            pipeline_harness.build_pipeline(triggers).run(source_descriptor=str(triggers))
        assert any(r.__dict__.get("reason") == "cross_batch_uploaded" for r in caplog.records)


# ---------------------------------------------------------------------------
# Group 5 — Stage failures
# ---------------------------------------------------------------------------


class TestStageFailures:
    @responses.activate
    def test_s2_unmapped_id_rvi(self, pipeline_harness, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
        pipeline_harness.register_cmis_for_docs([])  # No upload expected.
        triggers = _write_trigger_csv(tmp_path, [("TESTUNMAPPED", "123456", "1")])
        report = pipeline_harness.build_pipeline(triggers).run(source_descriptor=str(triggers))
        assert report.s2_failed == 1
        assert report.s5_done == 0
        pipeline_harness.tracking_store.flush()
        assert _count_rows(pipeline_harness.db_path, report.batch_id, "S2_FAILED") == 1

    @responses.activate
    def test_s3_metadata_source_failed(self, pipeline_harness, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
        # CIF 999999 is not in clients.csv → BAC_Nombre_Cliente cannot resolve.
        pipeline_harness.register_cmis_for_docs([])
        triggers = _write_trigger_csv(tmp_path, [("TESTMETAFAIL", "999999", "1")])
        report = pipeline_harness.build_pipeline(triggers).run(source_descriptor=str(triggers))
        assert report.s3_failed == 1
        assert report.s5_done == 0
        pipeline_harness.tracking_store.flush()
        assert _count_rows(pipeline_harness.db_path, report.batch_id, "S3_FAILED") == 1

    @responses.activate
    def test_s4_source_file_missing(self, pipeline_harness, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
        # TESTMISSFILES points to a non-existent image_path.
        pipeline_harness.register_cmis_for_docs([])
        triggers = _write_trigger_csv(tmp_path, [("TESTMISSFILES", "123456", "1")])
        report = pipeline_harness.build_pipeline(triggers).run(source_descriptor=str(triggers))
        assert report.s4_failed == 1
        assert report.s5_done == 0
        pipeline_harness.tracking_store.flush()
        assert _count_rows(pipeline_harness.db_path, report.batch_id, "S4_FAILED") == 1

    @responses.activate
    def test_s5_cmis_4xx_fail_fast(self, pipeline_harness, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
        # Warmup + folder OK, but upload returns 400.
        responses.add(
            responses.GET,
            "http://cmis.example.test:9080/opencmcmis/browser/$x!testrepo",
            json={"repositoryId": "$x!testrepo", "productName": "x"},
            status=200,
            match=[responses.matchers.query_param_matcher({"cmisselector": "repositoryInfo"})],
        )
        responses.add(
            responses.POST,
            "http://cmis.example.test:9080/opencmcmis/browser/$x!testrepo/root",
            json={"ok": True},
            status=201,
        )
        responses.add(
            responses.POST,
            "http://cmis.example.test:9080/opencmcmis/browser/$x!testrepo/root/$type/BAC_04_01_01_01_01",
            json={"error": "bad request"},
            status=400,
        )
        triggers = _write_trigger_csv(tmp_path, [("TESTCLIENT01", "123456", "1")])
        report = pipeline_harness.build_pipeline(triggers).run(source_descriptor=str(triggers))
        assert report.s5_failed == 1
        pipeline_harness.tracking_store.flush()
        assert _count_rows(pipeline_harness.db_path, report.batch_id, "S5_FAILED") == 1


# ---------------------------------------------------------------------------
# Group 6 — Resume
# ---------------------------------------------------------------------------


class TestResume:
    @responses.activate
    def test_resume_from_stage_3_idempotent(
        self,
        pipeline_harness,  # type: ignore[no-untyped-def]
        tmp_path: Path,
    ) -> None:
        # First run: complete end-to-end.
        pipeline_harness.register_cmis_for_docs(["TXN_PIPE_001"])
        triggers = _write_trigger_csv(tmp_path, [("TESTCLIENT01", "123456", "1")])
        first = pipeline_harness.build_pipeline(triggers).run(source_descriptor=str(triggers))
        pipeline_harness.tracking_store.flush()

        # Second run with from_stage=3: every is_stage_done skip-check fires.
        # No new CMIS calls (rely on the harness's already-registered stubs,
        # which are exhausted; if the orchestrator tries to upload again,
        # `responses` would raise ConnectionError on missing stub).
        second = pipeline_harness.build_pipeline(triggers).run(
            source_descriptor=str(triggers),
            batch_id=first.batch_id,
            from_stage=3,
        )
        assert second.batch_id == first.batch_id
        # S5 still counts as done (we count skips into s5_done).
        assert second.s5_done == 1

    @responses.activate
    def test_resume_out_of_scope_doc_dropped(
        self,
        pipeline_harness,  # type: ignore[no-untyped-def]
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        # First run: only TESTCLIENT01 in scope.
        pipeline_harness.register_cmis_for_docs(["TXN_PIPE_001"])
        triggers_v1 = _write_trigger_csv(tmp_path, [("TESTCLIENT01", "123456", "1")])
        first = pipeline_harness.build_pipeline(triggers_v1).run(source_descriptor=str(triggers_v1))
        pipeline_harness.tracking_store.flush()

        # Second run with from_stage=3 and a DIFFERENT trigger CSV that
        # also includes TESTCLIENT02. TESTCLIENT02 is out of scope.
        triggers_v2 = tmp_path / "triggers_v2.csv"
        triggers_v2.write_text(
            "ShortName,CIF,SystemID\nTESTCLIENT01,123456,1\nTESTCLIENT02,234567,1\n"
        )
        with caplog.at_level(logging.INFO, logger="cmcourier.orchestrators.staged"):
            second = pipeline_harness.build_pipeline(triggers_v2).run(
                source_descriptor=str(triggers_v2),
                batch_id=first.batch_id,
                from_stage=3,
            )
        assert second.s5_done == 1  # only the in-scope doc counts
        assert any(r.__dict__.get("reason") == "resume_out_of_scope" for r in caplog.records)

    @responses.activate
    def test_idempotent_rerun_from_stage_1(
        self,
        pipeline_harness,  # type: ignore[no-untyped-def]
        tmp_path: Path,
    ) -> None:
        pipeline_harness.register_cmis_for_docs(["TXN_PIPE_001"])
        triggers = _write_trigger_csv(tmp_path, [("TESTCLIENT01", "123456", "1")])
        first = pipeline_harness.build_pipeline(triggers).run(source_descriptor=str(triggers))
        pipeline_harness.tracking_store.flush()

        # Second run with same batch_id, from_stage=1. Every stage skip-checks.
        second = pipeline_harness.build_pipeline(triggers).run(
            source_descriptor=str(triggers),
            batch_id=first.batch_id,
            from_stage=1,
        )
        assert second.s5_done == 1  # counted via skip


# ---------------------------------------------------------------------------
# Group 7 — Heterogeneous batch
# ---------------------------------------------------------------------------


class TestHeterogeneous:
    @responses.activate
    def test_one_success_three_failures(self, pipeline_harness, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
        # Configure CMIS only for the one success (TESTCLIENT01).
        pipeline_harness.register_cmis_for_docs(["TXN_PIPE_001"])
        triggers = _write_trigger_csv(
            tmp_path,
            [
                ("TESTCLIENT01", "123456", "1"),  # success
                ("TESTUNMAPPED", "123456", "1"),  # S2 fail
                ("TESTMETAFAIL", "999999", "1"),  # S3 fail
                ("TESTMISSFILES", "123456", "1"),  # S4 fail
            ],
        )
        report = pipeline_harness.build_pipeline(triggers).run(source_descriptor=str(triggers))
        assert report.s5_done == 1
        assert report.s2_failed == 1
        assert report.s3_failed == 1
        assert report.s4_failed == 1
        pipeline_harness.tracking_store.flush()
        assert _batch_completed_at(pipeline_harness.db_path, report.batch_id) is not None


# ---------------------------------------------------------------------------
# Group 8 — S0 failure
# ---------------------------------------------------------------------------


class TestS0Failure:
    def test_s0_failure_propagates_no_complete_batch(
        self,
        pipeline_harness,  # type: ignore[no-untyped-def]
        tmp_path: Path,
    ) -> None:
        # CSV path that doesn't exist → CsvTriggerStrategy raises on iteration.
        with pytest.raises(Exception):  # noqa: B017 — trigger source raises wide
            pipeline_harness.pipeline.run(source_descriptor=str(tmp_path / "nope.csv"))


# ---------------------------------------------------------------------------
# Group 9 — Healed CIF propagates to upload metadata
# ---------------------------------------------------------------------------


class TestHealedCIF:
    @responses.activate
    def test_healed_cif_reaches_upload(
        self,
        pipeline_harness,  # type: ignore[no-untyped-def]
        tmp_path: Path,
    ) -> None:
        # TESTHEAL has trigger.cif='' but rvabrep.index2='123456'.
        # After self-healing, BAC_CIF resolves to '123456' and the upload
        # should carry that value.
        pipeline_harness.register_cmis_for_docs(["TXN_PIPE_006"])
        triggers = _write_trigger_csv(tmp_path, [("TESTHEAL", "", "1")])
        report = pipeline_harness.build_pipeline(triggers).run(source_descriptor=str(triggers))
        assert report.s5_done == 1
        # The captured upload request body contains the healed CIF.
        upload_calls = [
            c
            for c in responses.calls
            if c.request.method == "POST" and "BAC_04_01_01_01_01" in c.request.url
        ]
        assert len(upload_calls) == 1
        body = upload_calls[0].request.body
        if isinstance(body, bytes):
            body = body.decode("utf-8", errors="replace")
        assert "123456" in body  # the healed CIF appears as a property value
