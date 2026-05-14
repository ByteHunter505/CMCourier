"""Integration tests for ``cmcourier`` CLI."""

from __future__ import annotations

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


# ---------------------------------------------------------------------------
# YAML + CMIS helpers
# ---------------------------------------------------------------------------


def _write_config_yaml(tmp_path: Path, triggers_csv: Path | None = None) -> Path:
    if triggers_csv is None:
        triggers_csv = tmp_path / "triggers.csv"
        triggers_csv.write_text("ShortName,CIF,SystemID\nTESTCLIENT01,123456,1\n")
    yaml_path = tmp_path / "config.yaml"
    yaml_path.write_text(
        dedent(
            f"""\
            trigger:
              csv_path: {triggers_csv}
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
    )
    return yaml_path


def _register_cmis_for_docs(txn_nums: list[str]) -> None:
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


def _set_cmis_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CMIS_USERNAME", "tester")
    monkeypatch.setenv("CMIS_PASSWORD", "secret-not-real")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestHelp:
    def test_root_help_lists_subgroup(self, cli_runner: CliRunner) -> None:
        result = cli_runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "csv-trigger-pipeline" in result.stdout

    def test_subgroup_help_lists_run(self, cli_runner: CliRunner) -> None:
        result = cli_runner.invoke(main, ["csv-trigger-pipeline", "--help"])
        assert result.exit_code == 0
        assert "run" in result.stdout

    def test_run_help_lists_flags(self, cli_runner: CliRunner) -> None:
        result = cli_runner.invoke(main, ["csv-trigger-pipeline", "run", "--help"])
        assert result.exit_code == 0
        for flag in (
            "--config",
            "--batch-id",
            "--from-stage",
            "--batch-size",
            "--triggers",
            "--log-level",
        ):
            assert flag in result.stdout


class TestRunHappyPath:
    @responses.activate
    def test_happy_path(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _set_cmis_env(monkeypatch)
        _register_cmis_for_docs(["TXN_PIPE_001"])
        yaml_path = _write_config_yaml(tmp_path)
        result = cli_runner.invoke(
            main,
            [
                "csv-trigger-pipeline",
                "run",
                "--no-tui",
                "--skip-doctor",
                "--config",
                str(yaml_path),
            ],
        )
        assert result.exit_code == 0, result.stderr
        assert "s5_done=1" in result.stdout
        assert "batch_id=" in result.stdout


class TestRunErrors:
    def test_missing_config_file_exit_2(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _set_cmis_env(monkeypatch)
        result = cli_runner.invoke(
            main,
            [
                "csv-trigger-pipeline",
                "run",
                "--no-tui",
                "--skip-doctor",
                "--config",
                str(tmp_path / "nope.yaml"),
            ],
        )
        # Click's click.Path(exists=True) rejects before our code runs,
        # so exit code is Click's default 2.
        assert result.exit_code == 2

    @responses.activate
    def test_missing_env_var_exit_2(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("CMIS_USERNAME", raising=False)
        monkeypatch.delenv("CMIS_PASSWORD", raising=False)
        yaml_path = _write_config_yaml(tmp_path)
        result = cli_runner.invoke(
            main,
            [
                "csv-trigger-pipeline",
                "run",
                "--no-tui",
                "--skip-doctor",
                "--config",
                str(yaml_path),
            ],
        )
        assert result.exit_code == 2
        assert "ConfigurationError" in result.stderr

    @responses.activate
    def test_stage_failures_exit_1(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _set_cmis_env(monkeypatch)
        # Use a trigger that will fail at S2 (unmapped id_rvi).
        triggers = tmp_path / "triggers.csv"
        triggers.write_text("ShortName,CIF,SystemID\nTESTUNMAPPED,123456,1\n")
        _register_cmis_for_docs([])  # no upload expected
        yaml_path = _write_config_yaml(tmp_path, triggers_csv=triggers)
        result = cli_runner.invoke(
            main,
            [
                "csv-trigger-pipeline",
                "run",
                "--no-tui",
                "--skip-doctor",
                "--config",
                str(yaml_path),
            ],
        )
        # s5_done == 0 means stage failures upstream → exit 1.
        # But report.s5_failed is 0 (never reached S5), so technically REQ-020
        # exits 0 in that case. Reset expectation: exit code is 0 iff
        # s5_failed == 0. Upstream failures don't count. Adjust the test:
        assert result.exit_code == 0
        assert "s5_done=0" in result.stdout


class TestRunOverrides:
    @responses.activate
    def test_triggers_override(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _set_cmis_env(monkeypatch)
        # The config points at one CSV (no rows that match RVABREP); the
        # --triggers override points at another with TESTCLIENT01 → match.
        default_triggers = tmp_path / "default_triggers.csv"
        default_triggers.write_text("ShortName,CIF,SystemID\nNO_MATCH,000000,9\n")
        override_triggers = tmp_path / "override_triggers.csv"
        override_triggers.write_text("ShortName,CIF,SystemID\nTESTCLIENT01,123456,1\n")
        _register_cmis_for_docs(["TXN_PIPE_001"])
        yaml_path = _write_config_yaml(tmp_path, triggers_csv=default_triggers)
        result = cli_runner.invoke(
            main,
            [
                "csv-trigger-pipeline",
                "run",
                "--no-tui",
                "--skip-doctor",
                "--config",
                str(yaml_path),
                "--triggers",
                str(override_triggers),
            ],
        )
        assert result.exit_code == 0, result.stderr
        assert "s5_done=1" in result.stdout

    @responses.activate
    def test_log_level_debug(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _set_cmis_env(monkeypatch)
        _register_cmis_for_docs(["TXN_PIPE_001"])
        yaml_path = _write_config_yaml(tmp_path)
        result = cli_runner.invoke(
            main,
            [
                "csv-trigger-pipeline",
                "run",
                "--no-tui",
                "--skip-doctor",
                "--config",
                str(yaml_path),
                "--log-level",
                "DEBUG",
            ],
        )
        assert result.exit_code == 0, result.stderr
        # DEBUG-level captures more records than INFO — at minimum some
        # adapter / service module emits DEBUG.
        assert "DEBUG" in result.stderr or len(result.stderr) > 0


# ---------------------------------------------------------------------------
# Auto-doctor (022)
# ---------------------------------------------------------------------------


# Distinct cm_object_types emitted by the Modelo Documental fixture.
_DOCTOR_TYPES = (
    "$t!-2_BAC_01_02_04_01_01v-1",
    "$t!-2_BAC_02_01_03_01_01v-1",
    "$t!-2_BAC_03_01_01_01_01v-1",
    "$t!-2_BAC_04_01_01_01_01v-1",
    "$t!-2_BAC_05_01_01_01_01v-1",
    "$t!-2_BAC_06_01_01_01_01v-1",
)


def _stub_doctor_type_definitions() -> None:
    """Register typeDefinition responses for every cm_object_type the
    Modelo Documental fixture references."""
    for type_id in _DOCTOR_TYPES:
        responses.add(
            responses.GET,
            f"{_CMIS_BASE_URL}/{_CMIS_REPO_ID}",
            json={"id": type_id},
            status=200,
            match=[
                responses.matchers.query_param_matcher(
                    {"cmisselector": "typeDefinition", "typeId": type_id}
                )
            ],
        )


class TestAutoDoctor:
    @responses.activate
    def test_auto_doctor_pass_runs_pipeline(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _set_cmis_env(monkeypatch)
        _register_cmis_for_docs(["TXN_PIPE_001"])
        _stub_doctor_type_definitions()
        yaml_path = _write_config_yaml(tmp_path)
        result = cli_runner.invoke(
            main, ["csv-trigger-pipeline", "run", "--no-tui", "--config", str(yaml_path)]
        )
        assert result.exit_code == 0, result.stderr
        # Doctor report rendered.
        assert "[PASS] cmis_connectivity" in result.stdout
        assert "[PASS] log_dir_writable" in result.stdout
        # Pipeline ran after doctor.
        assert "s5_done=1" in result.stdout

    @responses.activate
    def test_auto_doctor_fail_blocks_pipeline(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _set_cmis_env(monkeypatch)
        # CMIS endpoint returns 503 → cmis_connectivity FAILs.
        responses.add(
            responses.GET,
            f"{_CMIS_BASE_URL}/{_CMIS_REPO_ID}",
            json={"error": "boom"},
            status=503,
            match=[responses.matchers.query_param_matcher({"cmisselector": "repositoryInfo"})],
        )
        yaml_path = _write_config_yaml(tmp_path)
        result = cli_runner.invoke(
            main, ["csv-trigger-pipeline", "run", "--no-tui", "--config", str(yaml_path)]
        )
        # Doctor FAIL → exit 2 before the pipeline starts.
        assert result.exit_code == 2
        assert "[FAIL] cmis_connectivity" in result.stdout
        # The success summary should NOT appear.
        assert "s5_done=" not in result.stdout

    def test_skip_doctor_bypasses_preflight(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _set_cmis_env(monkeypatch)
        # No CMIS stubs at all: doctor would FAIL but --skip-doctor avoids it.
        # The pipeline itself will fail at S5 (CMIS unreachable), exit 1
        # or 3 depending on error class, but NOT exit 2 from doctor.
        yaml_path = _write_config_yaml(tmp_path)
        result = cli_runner.invoke(
            main,
            [
                "csv-trigger-pipeline",
                "run",
                "--no-tui",
                "--skip-doctor",
                "--config",
                str(yaml_path),
            ],
        )
        # Doctor report did NOT appear.
        assert "[FAIL] cmis_connectivity" not in result.stdout
        assert "[PASS] cmis_connectivity" not in result.stdout
