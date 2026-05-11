"""Integration tests for the rvabrep-pipeline and as400-trigger-pipeline CLI."""

from __future__ import annotations

import logging
from pathlib import Path
from textwrap import dedent

import pytest
import responses
from click.testing import CliRunner

from cmcourier.cli.app import main

pytestmark = [pytest.mark.integration, pytest.mark.slow]

_TESTS_ROOT = Path(__file__).parent.parent.parent
_PIPELINE_FIXTURES = _TESTS_ROOT / "fixtures" / "pipeline"
_SERVICES_FIXTURES = _TESTS_ROOT / "fixtures" / "services"
_ASSEMBLY_FIXTURES = _TESTS_ROOT / "fixtures" / "assembly"

_CMIS_BASE_URL = "http://cmis.example.test:9080/opencmcmis/browser"
_CMIS_REPO_ID = "$x!testrepo"


def _set_cmis_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CMIS_USERNAME", "tester")
    monkeypatch.setenv("CMIS_PASSWORD", "secret-not-real")


def _stub_cmis_for_docs(txn_nums: list[str]) -> None:
    responses.add(
        responses.GET,
        f"{_CMIS_BASE_URL}/{_CMIS_REPO_ID}",
        json={"repositoryId": _CMIS_REPO_ID, "productName": "IBM"},
        status=200,
        match=[responses.matchers.query_param_matcher({"cmisselector": "repositoryInfo"})],
    )
    responses.add(
        responses.POST,
        f"{_CMIS_BASE_URL}/{_CMIS_REPO_ID}/root",
        json={"ok": True},
        status=201,
    )
    for txn in txn_nums:
        responses.add(
            responses.POST,
            f"{_CMIS_BASE_URL}/{_CMIS_REPO_ID}/root/$type/BAC_04_01_01_01_01",
            json={"succinctProperties": {"cmis:objectId": f"cm-{txn}"}},
            status=201,
        )


def _common_blocks(tmp_path: Path) -> str:
    return dedent(
        f"""\
        indexing:
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
          field_aliases:
            CIF: BAC_CIF
            Nombre_Cliente: BAC_Nombre_Cliente
          field_sources:
            BAC_CIF:
              sources:
                - source_type: trigger
                  lookup_value_column: cif
                - source_type: rvabrep
                  lookup_value_column: index2
            BAC_Nombre_Cliente:
              sources:
                - source_type: "csv:clients"
                  lookup_value_column: Nombre_Cliente
                  lookup_key_column: CIF
          sources:
            - alias: clients
              csv_path: {_SERVICES_FIXTURES / "metadata" / "clients.csv"}
        assembly:
          source_root: {_ASSEMBLY_FIXTURES}
          temp_dir: {tmp_path / "stg"}
        cmis:
          base_url: {_CMIS_BASE_URL}
          repo_id: "{_CMIS_REPO_ID}"
          retry_base_delay_s: 0.0
          retry_max_attempts: 2
        tracking:
          db_path: {tmp_path / "tracking.db"}
        """
    )


def _write_rvabrep_yaml(tmp_path: Path) -> Path:
    yaml_path = tmp_path / "config.yaml"
    yaml_path.write_text(
        "trigger:\n"
        '  kind: "rvabrep"\n'
        "  filters:\n"
        '    systems: ["1"]\n'
        '    document_types: ["CC03"]\n' + _common_blocks(tmp_path)
    )
    return yaml_path


def _write_as400_yaml(tmp_path: Path) -> Path:
    yaml_path = tmp_path / "config.yaml"
    yaml_path.write_text(
        "trigger:\n"
        '  kind: "as400"\n'
        '  query: "SELECT SHORTNAME, CIF, SYSTEMID FROM TRIGGERS"\n'
        "  as400_connection:\n"
        '    host: "10.0.0.1"\n' + _common_blocks(tmp_path)
    )
    return yaml_path


# ---------------------------------------------------------------------------
# rvabrep-pipeline
# ---------------------------------------------------------------------------


class TestRvabrepPipeline:
    @responses.activate
    def test_help(self, cli_runner: CliRunner) -> None:
        result = cli_runner.invoke(main, ["rvabrep-pipeline", "run", "--help"])
        assert result.exit_code == 0
        assert "--config" in result.stdout

    @responses.activate
    def test_happy_path(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _set_cmis_env(monkeypatch)
        # The rvabrep fixture has 2 active TESTCLIENT_NN docs with index7=CC03.
        # DirectRvabrepStrategy yields one trigger per unique (shortname, system_id).
        _stub_cmis_for_docs(["TXN_PIPE_001", "TXN_PIPE_002"])
        yaml_path = _write_rvabrep_yaml(tmp_path)
        result = cli_runner.invoke(
            main,
            ["rvabrep-pipeline", "run", "--no-tui", "--skip-doctor", "--config", str(yaml_path)],
        )
        assert result.exit_code == 0, result.stderr
        assert "s5_done=" in result.stdout

    def test_rejects_mismatched_kind(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _set_cmis_env(monkeypatch)
        # YAML uses kind: csv but the command expects kind: rvabrep.
        triggers = tmp_path / "triggers.csv"
        triggers.write_text("ShortName,CIF,SystemID\n")
        yaml_path = tmp_path / "config.yaml"
        yaml_path.write_text(f"trigger:\n  csv_path: {triggers}\n" + _common_blocks(tmp_path))
        result = cli_runner.invoke(
            main,
            ["rvabrep-pipeline", "run", "--no-tui", "--skip-doctor", "--config", str(yaml_path)],
        )
        assert result.exit_code == 2
        assert "trigger.kind" in result.stderr


# ---------------------------------------------------------------------------
# as400-trigger-pipeline
# ---------------------------------------------------------------------------


class _FakeCursor:
    def __init__(self, rows: list[tuple[str, str, str]], columns: tuple[str, ...]) -> None:
        self._rows = [list(r) for r in rows]
        self._columns = columns
        self.closed = False

    @property
    def description(self) -> list[tuple[str, ...]]:
        return [(c,) for c in self._columns]

    def execute(self, sql: str, params: list[object] | None = None) -> _FakeCursor:
        return self

    def fetchall(self) -> list[list[object]]:
        out = self._rows
        self._rows = []
        return out

    def fetchmany(self, size: int) -> list[list[object]]:
        chunk = self._rows[:size]
        self._rows = self._rows[size:]
        return chunk

    def fetchone(self) -> list[object] | None:
        return self._rows.pop(0) if self._rows else None

    def close(self) -> None:
        self.closed = True


class _FakeConn:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self) -> _FakeCursor:
        return self._cursor

    def close(self) -> None:
        pass


class _FakePyodbcModule:
    class Error(Exception):
        pass

    def __init__(self, connect_fn: object) -> None:
        self._connect_fn = connect_fn

    def connect(self, cs: str) -> object:
        return self._connect_fn(cs)  # type: ignore[operator]


class TestAs400TriggerPipeline:
    @responses.activate
    def test_help(self, cli_runner: CliRunner) -> None:
        result = cli_runner.invoke(main, ["as400-trigger-pipeline", "run", "--help"])
        assert result.exit_code == 0
        assert "--config" in result.stdout

    def test_rejects_missing_env(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _set_cmis_env(monkeypatch)
        monkeypatch.delenv("AS400_USERNAME", raising=False)
        monkeypatch.delenv("AS400_PASSWORD", raising=False)
        yaml_path = _write_as400_yaml(tmp_path)
        result = cli_runner.invoke(
            main,
            [
                "as400-trigger-pipeline",
                "run",
                "--no-tui",
                "--skip-doctor",
                "--config",
                str(yaml_path),
            ],
        )
        assert result.exit_code == 2
        assert "AS400" in result.stderr

    @responses.activate
    def test_happy_path(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _set_cmis_env(monkeypatch)
        monkeypatch.setenv("AS400_USERNAME", "as400tester")
        monkeypatch.setenv("AS400_PASSWORD", "as400secret")
        # Mock pyodbc so the AS400 trigger query returns 1 row matching the rvabrep fixture.
        import cmcourier.adapters.sources.as400 as as400_module

        cursor = _FakeCursor(
            rows=[("TESTCLIENT01", "123456", "1")],
            columns=("SHORTNAME", "CIF", "SYSTEMID"),
        )

        def _fake_connect(cs: str) -> _FakeConn:
            return _FakeConn(cursor)

        monkeypatch.setattr(as400_module, "pyodbc", _FakePyodbcModule(_fake_connect))
        _stub_cmis_for_docs(["TXN_PIPE_001"])
        yaml_path = _write_as400_yaml(tmp_path)
        result = cli_runner.invoke(
            main,
            [
                "as400-trigger-pipeline",
                "run",
                "--no-tui",
                "--skip-doctor",
                "--config",
                str(yaml_path),
            ],
        )
        assert result.exit_code == 0, result.stderr
        assert "s5_done=1" in result.stdout


# ---------------------------------------------------------------------------
# Root help
# ---------------------------------------------------------------------------


class TestRootHelp:
    def test_lists_all_pipeline_commands(self, cli_runner: CliRunner) -> None:
        result = cli_runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        for cmd in (
            "csv-trigger-pipeline",
            "rvabrep-pipeline",
            "as400-trigger-pipeline",
            "local-scan-pipeline",
            "single-doc",
            "doctor",
        ):
            assert cmd in result.stdout


# ---------------------------------------------------------------------------
# local-scan-pipeline
# ---------------------------------------------------------------------------


def _write_local_scan_yaml(tmp_path: Path, scan_dir: Path) -> Path:
    yaml_path = tmp_path / "config.yaml"
    yaml_path.write_text(
        f'trigger:\n  kind: "local_scan"\n  scan_path: {scan_dir}\n' + _common_blocks(tmp_path)
    )
    return yaml_path


class TestLocalScanPipeline:
    def test_help(self, cli_runner: CliRunner) -> None:
        result = cli_runner.invoke(main, ["local-scan-pipeline", "run", "--help"])
        assert result.exit_code == 0
        assert "--config" in result.stdout

    def test_rejects_mismatched_kind(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _set_cmis_env(monkeypatch)
        # YAML uses kind=csv but the command expects local_scan.
        triggers = tmp_path / "triggers.csv"
        triggers.write_text("ShortName,CIF,SystemID\n")
        yaml_path = tmp_path / "config.yaml"
        yaml_path.write_text(f"trigger:\n  csv_path: {triggers}\n" + _common_blocks(tmp_path))
        result = cli_runner.invoke(
            main,
            ["local-scan-pipeline", "run", "--no-tui", "--skip-doctor", "--config", str(yaml_path)],
        )
        assert result.exit_code == 2
        assert "trigger.kind" in result.stderr

    @responses.activate
    def test_happy_path(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _set_cmis_env(monkeypatch)
        # Scan dir contains a file whose name matches a row in rvabrep.csv
        # (TESTCLIENT01 → DAAAH9X4.001).
        scan_dir = tmp_path / "scan"
        scan_dir.mkdir()
        (scan_dir / "DAAAH9X4.001").touch()
        _stub_cmis_for_docs(["TXN_PIPE_001"])
        yaml_path = _write_local_scan_yaml(tmp_path, scan_dir)
        result = cli_runner.invoke(
            main,
            ["local-scan-pipeline", "run", "--no-tui", "--skip-doctor", "--config", str(yaml_path)],
        )
        assert result.exit_code == 0, result.stderr
        assert "s5_done=" in result.stdout


# ---------------------------------------------------------------------------
# single-doc (REBIRTH §10.2 diagnostic)
# ---------------------------------------------------------------------------


def _write_single_doc_yaml(tmp_path: Path) -> Path:
    yaml_path = tmp_path / "config.yaml"
    yaml_path.write_text('trigger:\n  kind: "single_doc"\n' + _common_blocks(tmp_path))
    return yaml_path


class TestSingleDocPipeline:
    def test_help(self, cli_runner: CliRunner) -> None:
        result = cli_runner.invoke(main, ["single-doc", "run", "--help"])
        assert result.exit_code == 0
        assert "--config" in result.stdout
        assert "--shortname" in result.stdout
        assert "--system" in result.stdout
        assert "--cif" in result.stdout

    def test_rejects_mismatched_kind(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _set_cmis_env(monkeypatch)
        # YAML kind=csv (defaulted) but command expects single_doc.
        triggers = tmp_path / "triggers.csv"
        triggers.write_text("ShortName,CIF,SystemID\n")
        yaml_path = tmp_path / "config.yaml"
        yaml_path.write_text(f"trigger:\n  csv_path: {triggers}\n" + _common_blocks(tmp_path))
        result = cli_runner.invoke(
            main,
            [
                "single-doc",
                "run",
                "--no-tui",
                "--skip-doctor",
                "--config",
                str(yaml_path),
                "--shortname",
                "TESTCLIENT01",
                "--system",
                "1",
            ],
        )
        assert result.exit_code == 2
        assert "single_doc" in result.stderr

    @responses.activate
    def test_happy_path(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _set_cmis_env(monkeypatch)
        _stub_cmis_for_docs(["TXN_PIPE_001"])
        yaml_path = _write_single_doc_yaml(tmp_path)
        result = cli_runner.invoke(
            main,
            [
                "single-doc",
                "run",
                "--no-tui",
                "--skip-doctor",
                "--config",
                str(yaml_path),
                "--shortname",
                "TESTCLIENT01",
                "--system",
                "1",
                "--cif",
                "123456",
            ],
        )
        assert result.exit_code == 0, result.stderr
        assert "s5_done=1" in result.stdout


# ---------------------------------------------------------------------------
# --resume (022)
# ---------------------------------------------------------------------------


def _seed_resume_batch(db_path: Path, *, failed_at_stage: int | None = None) -> str:
    """Create a synthetic batch in the tracking store with optional FAILED row."""
    from datetime import datetime

    from cmcourier.adapters.tracking import SQLiteTrackingStore
    from cmcourier.domain.models import MigrationRecord, StageStatus

    store = SQLiteTrackingStore(db_path)
    try:
        batch_id = store.start_batch(total_records=1)
        record = MigrationRecord(
            trigger_shortname="TESTCLIENT01",
            trigger_cif="123456",
            trigger_system_id="1",
            rvabrep_txn_num="TXN_PIPE_001",
            rvabrep_file_name="DAAAH9X4.001",
            batch_id=batch_id,
            status=StageStatus.S1_PENDING,
            created_at=datetime(2026, 1, 1, 0, 0),
        )
        store.mark_stage_pending(record, StageStatus.S1_PENDING)
        store.mark_stage_done("TXN_PIPE_001", batch_id, StageStatus.S1_DONE)
        if failed_at_stage is not None:
            failed_status = StageStatus(f"S{failed_at_stage}_FAILED")
            store.mark_stage_failed("TXN_PIPE_001", batch_id, failed_status, "synthetic")
        store.flush()
    finally:
        store.close()
    return batch_id


def _write_csv_yaml_with_db(tmp_path: Path) -> Path:
    """Reuse the rvabrep YAML shape but flip the trigger to csv for simplicity."""
    triggers = tmp_path / "triggers.csv"
    triggers.write_text("ShortName,CIF,SystemID\nTESTCLIENT01,123456,1\n")
    yaml_path = tmp_path / "config.yaml"
    yaml_path.write_text(f"trigger:\n  csv_path: {triggers}\n" + _common_blocks(tmp_path))
    return yaml_path


class TestResumeFlag:
    def test_resume_without_batch_id_exits_2(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _set_cmis_env(monkeypatch)
        yaml_path = _write_csv_yaml_with_db(tmp_path)
        result = cli_runner.invoke(
            main,
            [
                "csv-trigger-pipeline",
                "run",
                "--no-tui",
                "--skip-doctor",
                "--config",
                str(yaml_path),
                "--resume",
            ],
        )
        assert result.exit_code == 2
        assert "--resume requires --batch-id" in result.stderr

    def test_resume_unknown_batch_exits_1(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _set_cmis_env(monkeypatch)
        yaml_path = _write_csv_yaml_with_db(tmp_path)
        result = cli_runner.invoke(
            main,
            [
                "csv-trigger-pipeline",
                "run",
                "--no-tui",
                "--skip-doctor",
                "--config",
                str(yaml_path),
                "--batch-id",
                "ghost-123",
                "--resume",
            ],
        )
        assert result.exit_code == 1
        assert "Batch not found" in result.stderr

    def test_resume_clean_batch_exits_0(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _set_cmis_env(monkeypatch)
        yaml_path = _write_csv_yaml_with_db(tmp_path)
        # Seed a batch with only S1_DONE (no failed/pending after that).
        batch_id = _seed_resume_batch(tmp_path / "tracking.db")
        result = cli_runner.invoke(
            main,
            [
                "csv-trigger-pipeline",
                "run",
                "--no-tui",
                "--skip-doctor",
                "--config",
                str(yaml_path),
                "--batch-id",
                batch_id,
                "--resume",
            ],
        )
        assert result.exit_code == 0
        assert "Nothing to resume" in result.stdout

    @responses.activate
    def test_resume_picks_lowest_failed_stage(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        _set_cmis_env(monkeypatch)
        _stub_cmis_for_docs(["TXN_PIPE_001"])
        yaml_path = _write_csv_yaml_with_db(tmp_path)
        batch_id = _seed_resume_batch(tmp_path / "tracking.db", failed_at_stage=5)
        with caplog.at_level(logging.INFO, logger="cmcourier"):
            result = cli_runner.invoke(
                main,
                [
                    "csv-trigger-pipeline",
                    "run",
                    "--no-tui",
                    "--skip-doctor",
                    "--config",
                    str(yaml_path),
                    "--batch-id",
                    batch_id,
                    "--resume",
                ],
            )
        assert result.exit_code == 0, result.stderr
        # The resume helper logged its inference.
        resolved = next(
            (
                getattr(r, "resume_inferred", None)
                for r in caplog.records
                if r.message == "resume_resolved"
            ),
            None,
        )
        assert resolved == 5
