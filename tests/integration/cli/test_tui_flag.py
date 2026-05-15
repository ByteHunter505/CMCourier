"""REQ-043: CLI `--tui` / `--no-tui` integration tests.

These check the three semantics promised by spec 025:

* ``--no-tui`` works on the pipeline commands (REQ-031).
* The default `tui=True` auto-disables when stderr is not a TTY,
  so existing CliRunner-based tests stay green (REQ-034).
* An *explicit* ``--tui`` in a non-TTY context exits with code 2
  and a clear ``ConfigurationError`` (REQ-034 explicit branch).
"""

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


def _set_cmis_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CMIS_USERNAME", "tester")
    monkeypatch.setenv("CMIS_PASSWORD", "secret-not-real")


def _stub_cmis(txn_nums: list[str]) -> None:
    respx.get(f"{_CMIS_BASE_URL}/{_CMIS_REPO_ID}").mock(
        return_value=httpx.Response(200, json={"repositoryId": _CMIS_REPO_ID, "productName": "IBM"})
    )
    respx.post(f"{_CMIS_BASE_URL}/{_CMIS_REPO_ID}/root").mock(
        return_value=httpx.Response(201, json={"ok": True})
    )
    for txn in txn_nums:
        respx.post(f"{_CMIS_BASE_URL}/{_CMIS_REPO_ID}/root/$type/BAC_04_01_01_01_01").mock(
            return_value=httpx.Response(
                201, json={"succinctProperties": {"cmis:objectId": f"cm-{txn}"}}
            )
        )


def _write_csv_yaml(tmp_path: Path) -> Path:
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


class TestNoTuiHeadless:
    @respx.mock
    def test_csv_trigger_no_tui(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _set_cmis_env(monkeypatch)
        _stub_cmis(["TXN_PIPE_001"])
        yaml_path = _write_csv_yaml(tmp_path)
        result = CliRunner().invoke(
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

    @respx.mock
    def test_single_doc_no_tui(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _set_cmis_env(monkeypatch)
        _stub_cmis(["TXN_PIPE_001"])
        # Override the csv config's kind to single_doc.
        yaml_path = _write_csv_yaml(tmp_path)
        body = yaml_path.read_text().replace(
            f"trigger:\n  csv_path: {tmp_path / 'triggers.csv'}",
            'trigger:\n  kind: "single_doc"\n',
        )
        yaml_path.write_text(body)
        result = CliRunner().invoke(
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

    def test_help_lists_no_tui_flag(self) -> None:
        for group in (
            "csv-trigger-pipeline",
            "rvabrep-pipeline",
            "local-scan-pipeline",
            "single-doc",
        ):
            result = CliRunner().invoke(main, [group, "run", "--help"])
            assert result.exit_code == 0, result.stderr
            assert "--tui" in result.stdout
            assert "--no-tui" in result.stdout


class TestExplicitTuiNonTtyExits2:
    """REQ-034 explicit branch: ``--tui`` in a non-TTY context exits 2."""

    def test_explicit_tui_in_clirunner_exits_2(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _set_cmis_env(monkeypatch)
        yaml_path = _write_csv_yaml(tmp_path)
        result = CliRunner().invoke(
            main,
            [
                "csv-trigger-pipeline",
                "run",
                "--tui",
                "--skip-doctor",
                "--config",
                str(yaml_path),
            ],
        )
        assert result.exit_code == 2, result.stderr
        assert "ConfigurationError" in result.stderr
        assert "TTY" in result.stderr
