"""Tests de integración para los subcomandos ``cmcourier batch ...`` (021)."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest
from click.testing import CliRunner

from cmcourier.adapters.tracking import SQLiteTrackingStore
from cmcourier.cli.app import main
from cmcourier.domain.models import StageStatus

pytestmark = [pytest.mark.integration, pytest.mark.slow]

_TESTS_ROOT = Path(__file__).parent.parent.parent
_PIPELINE_FIXTURES = _TESTS_ROOT / "fixtures" / "pipeline"
_SERVICES_FIXTURES = _TESTS_ROOT / "fixtures" / "services"
_ASSEMBLY_FIXTURES = _TESTS_ROOT / "fixtures" / "assembly"

_CMIS_BASE_URL = "http://cmis.example.test:9080/opencmcmis/browser"
_CMIS_REPO_ID = "$x!testrepo"


def _write_yaml(tmp_path: Path) -> Path:
    triggers = tmp_path / "triggers.csv"
    triggers.write_text("ShortName,CIF,SystemID\nTESTCLIENT01,123456,1\n")
    yaml_path = tmp_path / "config.yaml"
    yaml_path.write_text(
        dedent(
            f"""\
            trigger:
              csv_path: {triggers}
            indexing:
              source:
                kind: csv
                csv_path: {_PIPELINE_FIXTURES / "rvabrep.csv"}
              columns:
                shortname_column: shortname
                system_id_column: system_id
                delete_code_column: delete_code
                txn_num_column: txn_num
                index2_column: index2
                index3_column: index3
                index4_column: index4
                index5_column: index5
                index6_column: index6
                index7_column: index7
                image_type_column: image_type
                image_path_column: image_path
                file_name_column: file_name
                creation_date_column: creation_date
                last_view_date_column: last_view_date
                total_pages_column: total_pages
            mapping:
              csv_path: {_SERVICES_FIXTURES / "modelo_documental.csv"}
            metadata:
              field_sources:
                BAC_CIF:
                  sources:
                    - source_type: trigger
                      lookup_value_column: cif
            assembly:
              source_root: {_ASSEMBLY_FIXTURES}
              temp_dir: {tmp_path / "stg"}
            cmis:
              base_url: {_CMIS_BASE_URL}
              repo_id: "{_CMIS_REPO_ID}"
            tracking:
              db_path: {tmp_path / "tracking.db"}
            observability:
              log_dir: {tmp_path / "logs"}
            """
        )
    )
    return yaml_path


def _seed_batch(
    db_path: Path,
    *,
    complete: bool = False,
    fail_stage: StageStatus | None = None,
) -> str:
    from datetime import datetime

    from cmcourier.domain.models import MigrationRecord

    store = SQLiteTrackingStore(db_path)
    try:
        batch_id = store.start_batch(total_records=1)
        record = MigrationRecord(
            trigger_shortname="TESTUSER001",
            trigger_cif="000000",
            trigger_system_id="1",
            rvabrep_txn_num="TXN_SEED",
            rvabrep_file_name="SEED.001",
            batch_id=batch_id,
            status=StageStatus.S2_PENDING,
            created_at=datetime(2026, 1, 1, 0, 0),
        )
        store.mark_stage_pending(record, StageStatus.S2_PENDING)
        if fail_stage is not None:
            store.mark_stage_failed("TXN_SEED", batch_id, fail_stage, "synthetic fail")
        else:
            store.mark_stage_done("TXN_SEED", batch_id, StageStatus.S2_DONE)
        if complete:
            store.complete_batch(batch_id)
        store.flush()
    finally:
        store.close()
    return batch_id


# ---------------------------------------------------------------------------
# batch list
# ---------------------------------------------------------------------------


class TestBatchList:
    def test_help(self) -> None:
        result = CliRunner().invoke(main, ["batch", "list", "--help"])
        assert result.exit_code == 0
        assert "--config" in result.stdout
        assert "--status" in result.stdout

    def test_empty_store(self, tmp_path: Path) -> None:
        yaml_path = _write_yaml(tmp_path)
        result = CliRunner().invoke(main, ["batch", "list", "-c", str(yaml_path)])
        assert result.exit_code == 0, result.output
        assert "No batches recorded." in result.stdout

    def test_lists_batches_with_status(self, tmp_path: Path) -> None:
        yaml_path = _write_yaml(tmp_path)
        db_path = tmp_path / "tracking.db"
        seed_a = _seed_batch(db_path, complete=True)
        seed_b = _seed_batch(db_path, complete=False)
        result = CliRunner().invoke(main, ["batch", "list", "-c", str(yaml_path)])
        assert result.exit_code == 0
        assert seed_a in result.stdout
        assert seed_b in result.stdout
        assert "STATUS" in result.stdout

    def test_filter_in_progress(self, tmp_path: Path) -> None:
        yaml_path = _write_yaml(tmp_path)
        db_path = tmp_path / "tracking.db"
        seed_a = _seed_batch(db_path, complete=True)
        seed_b = _seed_batch(db_path, complete=False)
        result = CliRunner().invoke(
            main, ["batch", "list", "-c", str(yaml_path), "--status", "in_progress"]
        )
        assert result.exit_code == 0
        assert seed_b in result.stdout
        assert seed_a not in result.stdout


# ---------------------------------------------------------------------------
# batch show
# ---------------------------------------------------------------------------


class TestBatchShow:
    def test_help(self) -> None:
        result = CliRunner().invoke(main, ["batch", "show", "--help"])
        assert result.exit_code == 0
        assert "BATCH_ID" in result.stdout

    def test_unknown_batch_exits_1(self, tmp_path: Path) -> None:
        yaml_path = _write_yaml(tmp_path)
        result = CliRunner().invoke(main, ["batch", "show", "-c", str(yaml_path), "ghost-123"])
        assert result.exit_code == 1
        assert "Batch not found" in result.stderr

    def test_show_known_batch(self, tmp_path: Path) -> None:
        yaml_path = _write_yaml(tmp_path)
        batch_id = _seed_batch(tmp_path / "tracking.db", complete=True)
        result = CliRunner().invoke(main, ["batch", "show", "-c", str(yaml_path), batch_id])
        assert result.exit_code == 0, result.output
        assert batch_id in result.stdout
        assert "STAGE" in result.stdout
        assert "S2" in result.stdout

    def test_show_failed_batch_lists_failures(self, tmp_path: Path) -> None:
        yaml_path = _write_yaml(tmp_path)
        batch_id = _seed_batch(tmp_path / "tracking.db", fail_stage=StageStatus.S5_FAILED)
        result = CliRunner().invoke(main, ["batch", "show", "-c", str(yaml_path), batch_id])
        assert result.exit_code == 0
        assert "FAILED records" in result.stdout
        assert "TXN_SEED" in result.stdout
        assert "S5_FAILED" in result.stdout


# ---------------------------------------------------------------------------
# batch retry-failed
# ---------------------------------------------------------------------------


class TestBatchRetryFailed:
    def test_help(self) -> None:
        result = CliRunner().invoke(main, ["batch", "retry-failed", "--help"])
        assert result.exit_code == 0
        assert "--batch" in result.stdout
        assert "--stage" in result.stdout

    def test_resets_all_failures(self, tmp_path: Path) -> None:
        yaml_path = _write_yaml(tmp_path)
        batch_id = _seed_batch(tmp_path / "tracking.db", fail_stage=StageStatus.S5_FAILED)
        result = CliRunner().invoke(
            main,
            [
                "batch",
                "retry-failed",
                "-c",
                str(yaml_path),
                "--batch",
                batch_id,
            ],
        )
        assert result.exit_code == 0
        assert "Reset 1 FAILED" in result.stdout

    def test_resets_only_specified_stage(self, tmp_path: Path) -> None:
        yaml_path = _write_yaml(tmp_path)
        batch_id = _seed_batch(tmp_path / "tracking.db", fail_stage=StageStatus.S5_FAILED)
        result = CliRunner().invoke(
            main,
            [
                "batch",
                "retry-failed",
                "-c",
                str(yaml_path),
                "--batch",
                batch_id,
                "--stage",
                "S5",
            ],
        )
        assert result.exit_code == 0
        assert "Reset 1 FAILED" in result.stdout
        assert "stage=S5" in result.stdout

    def test_no_failures_returns_zero(self, tmp_path: Path) -> None:
        yaml_path = _write_yaml(tmp_path)
        batch_id = _seed_batch(tmp_path / "tracking.db", complete=True)
        result = CliRunner().invoke(
            main,
            [
                "batch",
                "retry-failed",
                "-c",
                str(yaml_path),
                "--batch",
                batch_id,
            ],
        )
        assert result.exit_code == 0
        assert "Reset 0 FAILED" in result.stdout


# ---------------------------------------------------------------------------
# batch export-report (023)
# ---------------------------------------------------------------------------


class TestBatchExportReport:
    def test_help(self) -> None:
        result = CliRunner().invoke(main, ["batch", "export-report", "--help"])
        assert result.exit_code == 0
        for flag in ("--batch", "--format", "--output"):
            assert flag in result.stdout

    def test_csv_stdout(self, tmp_path: Path) -> None:
        yaml_path = _write_yaml(tmp_path)
        batch_id = _seed_batch(tmp_path / "tracking.db", fail_stage=StageStatus.S5_FAILED)
        result = CliRunner().invoke(
            main,
            [
                "batch",
                "export-report",
                "-c",
                str(yaml_path),
                "--batch",
                batch_id,
                "--format",
                "csv",
            ],
        )
        assert result.exit_code == 0, result.output
        # Header + 6 filas de stage.
        lines = result.stdout.strip().splitlines()
        assert lines[0].startswith("batch_id,status,started_at")
        assert len(lines) == 7
        # Cada fila tiene el batch_id en la columna 0.
        for line in lines[1:]:
            assert line.startswith(f"{batch_id},")
        # La fila S5 reporta la cantidad de fallos.
        s5_line = next(ln for ln in lines if ",S5," in ln)
        assert s5_line.endswith(",0,1,0")

    def test_json_stdout(self, tmp_path: Path) -> None:
        import json

        yaml_path = _write_yaml(tmp_path)
        batch_id = _seed_batch(tmp_path / "tracking.db", fail_stage=StageStatus.S5_FAILED)
        result = CliRunner().invoke(
            main,
            [
                "batch",
                "export-report",
                "-c",
                str(yaml_path),
                "--batch",
                batch_id,
                "--format",
                "json",
            ],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["batch_id"] == batch_id
        assert "stage_counts" in payload
        assert "failed_records" in payload
        assert payload["stage_counts"]["S5"]["FAILED"] == 1
        assert len(payload["failed_records"]) == 1
        assert payload["failed_records"][0]["txn_num"] == "TXN_SEED"

    def test_output_writes_file(self, tmp_path: Path) -> None:
        yaml_path = _write_yaml(tmp_path)
        batch_id = _seed_batch(tmp_path / "tracking.db", complete=True)
        out_path = tmp_path / "report.csv"
        result = CliRunner().invoke(
            main,
            [
                "batch",
                "export-report",
                "-c",
                str(yaml_path),
                "--batch",
                batch_id,
                "--format",
                "csv",
                "--output",
                str(out_path),
            ],
        )
        assert result.exit_code == 0, result.output
        assert "Report written to" in result.stdout
        assert out_path.exists()
        assert out_path.read_text().startswith("batch_id,status,")

    def test_unknown_batch_exits_1(self, tmp_path: Path) -> None:
        yaml_path = _write_yaml(tmp_path)
        result = CliRunner().invoke(
            main,
            [
                "batch",
                "export-report",
                "-c",
                str(yaml_path),
                "--batch",
                "ghost-batch",
                "--format",
                "json",
            ],
        )
        assert result.exit_code == 1
        assert "Batch not found" in result.stderr
