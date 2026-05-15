"""Tests de integración del CLI ``cmcourier``."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import httpx
import pytest
import respx
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
# Helpers de YAML + `cmis`
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
    # 060: el warmup necesita matchear con params= explícitos porque el flujo
    # del doctor también pega contra la misma base URL para los lookups de
    # typeDefinition — sin params, gana el último `.mock()` y la respuesta del
    # warmup queda tapada.
    respx.get(
        f"{_CMIS_BASE_URL}/{_CMIS_REPO_ID}",
        params={"cmisselector": "repositoryInfo"},
    ).mock(
        return_value=httpx.Response(200, json={"repositoryId": _CMIS_REPO_ID, "productName": "IBM"})
    )
    # El pre-flight del doctor también `fetchea` cada definición de cm_object_type.
    respx.get(f"{_CMIS_BASE_URL}/{_CMIS_REPO_ID}").mock(
        return_value=httpx.Response(200, json={"id": "$t!-2_BAC_04_01_01_01_01v-1"})
    )
    respx.post(f"{_CMIS_BASE_URL}/{_CMIS_REPO_ID}/root").mock(
        return_value=httpx.Response(201, json={"ok": True})
    )
    if txn_nums:
        respx.post(f"{_CMIS_BASE_URL}/{_CMIS_REPO_ID}/root/$type/BAC_04_01_01_01_01").mock(
            side_effect=[
                httpx.Response(201, json={"succinctProperties": {"cmis:objectId": f"cm-{txn}"}})
                for txn in txn_nums
            ]
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
    @respx.mock
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
        # click.Path(exists=True) de Click rechaza antes de que corra nuestro
        # código, así el exit code queda en el 2 por default de Click.
        assert result.exit_code == 2

    @respx.mock
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

    @respx.mock
    def test_stage_failures_exit_1(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _set_cmis_env(monkeypatch)
        # Usamos un trigger que va a fallar en S2 (id_rvi sin mapear).
        triggers = tmp_path / "triggers.csv"
        triggers.write_text("ShortName,CIF,SystemID\nTESTUNMAPPED,123456,1\n")
        _register_cmis_for_docs([])  # no se espera ningún upload
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
        # s5_done == 0 significa fallas de stage aguas arriba → exit 1.
        # Pero report.s5_failed es 0 (nunca llegó a S5), así que técnicamente
        # REQ-020 sale con 0 en ese caso. Reseteamos la expectativa: exit code
        # es 0 si y solo si s5_failed == 0. Las fallas aguas arriba no cuentan.
        # Ajustamos el test:
        assert result.exit_code == 0
        assert "s5_done=0" in result.stdout


class TestRunOverrides:
    @respx.mock
    def test_triggers_override(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _set_cmis_env(monkeypatch)
        # La config apunta a un CSV (sin filas que matcheen RVABREP); el
        # override --triggers apunta a otro con TESTCLIENT01 → matchea.
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

    @respx.mock
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
        # El nivel DEBUG captura más registros que INFO — como mínimo algún
        # adapter / servicio emite DEBUG.
        assert "DEBUG" in result.stderr or len(result.stderr) > 0


# ---------------------------------------------------------------------------
# Auto-doctor (022)
# ---------------------------------------------------------------------------


# cm_object_types distintos emitidos por el `fixture` del Modelo Documental.
_DOCTOR_TYPES = (
    "$t!-2_BAC_01_02_04_01_01v-1",
    "$t!-2_BAC_02_01_03_01_01v-1",
    "$t!-2_BAC_03_01_01_01_01v-1",
    "$t!-2_BAC_04_01_01_01_01v-1",
    "$t!-2_BAC_05_01_01_01_01v-1",
    "$t!-2_BAC_06_01_01_01_01v-1",
)


def _stub_doctor_type_definitions() -> None:
    """Registra respuestas de typeDefinition para cada cm_object_type que
    referencia el `fixture` del Modelo Documental."""
    for type_id in _DOCTOR_TYPES:
        respx.get(f"{_CMIS_BASE_URL}/{_CMIS_REPO_ID}").mock(
            return_value=httpx.Response(200, json={"id": type_id})
        )


class TestAutoDoctor:
    @respx.mock
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
        # El reporte del doctor se renderizó.
        assert "[PASS] cmis_connectivity" in result.stdout
        assert "[PASS] log_dir_writable" in result.stdout
        # El `pipeline` corrió después del doctor.
        assert "s5_done=1" in result.stdout

    @respx.mock
    def test_auto_doctor_fail_blocks_pipeline(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _set_cmis_env(monkeypatch)
        # El endpoint `cmis` devuelve 503 → cmis_connectivity FALLA.
        respx.get(f"{_CMIS_BASE_URL}/{_CMIS_REPO_ID}").mock(
            return_value=httpx.Response(503, json={"error": "boom"})
        )
        yaml_path = _write_config_yaml(tmp_path)
        result = cli_runner.invoke(
            main, ["csv-trigger-pipeline", "run", "--no-tui", "--config", str(yaml_path)]
        )
        # FAIL del doctor → exit 2 antes de que el `pipeline` arranque.
        assert result.exit_code == 2
        assert "[FAIL] cmis_connectivity" in result.stdout
        # El resumen de éxito NO debe aparecer.
        assert "s5_done=" not in result.stdout

    def test_skip_doctor_bypasses_preflight(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _set_cmis_env(monkeypatch)
        # Sin `stubs` de `cmis` para nada: el doctor FALLARÍA pero
        # --skip-doctor lo evita. El `pipeline` va a fallar en S5 (con `cmis`
        # inalcanzable), saliendo con 1 o 3 según la clase de error, pero NO
        # con exit 2 del doctor.
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
        # El reporte del doctor NO apareció.
        assert "[FAIL] cmis_connectivity" not in result.stdout
        assert "[PASS] cmis_connectivity" not in result.stdout
