"""Integration tests for ``--batches-in-flight`` (028, REQ-024)."""

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


def _set_cmis_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CMIS_USERNAME", "tester")
    monkeypatch.setenv("CMIS_PASSWORD", "secret-not-real")


def _stub_cmis(txn_nums: list[str]) -> None:
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


def _write_yaml(tmp_path: Path, *, batches_in_flight: int = 2) -> Path:
    triggers = tmp_path / "triggers.csv"
    triggers.write_text("ShortName,CIF,SystemID\nTESTCLIENT01,123456,1\n")
    yaml_path = tmp_path / "config.yaml"
    yaml_path.write_text(
        dedent(
            f"""\
            trigger:
              csv_path: {triggers}
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
            processing:
              batches_in_flight: {batches_in_flight}
            """
        )
    )
    return yaml_path


class TestBatchesInFlight:
    @responses.activate
    def test_n_one_legacy_output(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _set_cmis_env(monkeypatch)
        _stub_cmis(["TXN_PIPE_001"])
        yaml_path = _write_yaml(tmp_path, batches_in_flight=1)
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
        # N=1 must produce the legacy summary line, no TOTALS.
        assert "s5_done=1" in result.stdout
        assert "TOTALS" not in result.stdout

    @responses.activate
    def test_n_two_multi_chunk_output(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _set_cmis_env(monkeypatch)
        _stub_cmis(["TXN_PIPE_001"])
        # Force chunking: batch_size=1 over a single-trigger source = 1 chunk.
        # To get >1 chunk, we'd need >1 trigger. Instead, verify N=2 with
        # one trigger still works (degenerate single-chunk path through
        # the orchestrator with overlap enabled).
        yaml_path = _write_yaml(tmp_path, batches_in_flight=2)
        result = CliRunner().invoke(
            main,
            [
                "csv-trigger-pipeline",
                "run",
                "--no-tui",
                "--skip-doctor",
                "--config",
                str(yaml_path),
                "--batch-size",
                "1",
            ],
        )
        assert result.exit_code == 0, result.stderr
        # Single chunk → legacy output. (Multi-chunk requires >1 trigger.)
        assert "s5_done=1" in result.stdout

    @responses.activate
    def test_n_two_two_chunks_emits_totals(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _set_cmis_env(monkeypatch)
        _stub_cmis(["TXN_PIPE_001", "TXN_PIPE_002"])
        yaml_path = _write_yaml(tmp_path, batches_in_flight=2)
        # _write_yaml seeds a 1-row CSV; overwrite it with 2 rows AFTER.
        triggers = tmp_path / "triggers.csv"
        triggers.write_text(
            "ShortName,CIF,SystemID\nTESTCLIENT01,123456,1\nTESTCLIENT02,123456,1\n"
        )
        assert triggers.read_text().count("\n") >= 2, triggers.read_text()
        result = CliRunner().invoke(
            main,
            [
                "csv-trigger-pipeline",
                "run",
                "--no-tui",
                "--skip-doctor",
                "--config",
                str(yaml_path),
                "--batch-size",
                "1",
            ],
        )
        assert result.exit_code == 0, result.stderr
        # Two chunks → multi-chunk output with TOTALS line.
        assert "TOTALS" in result.stdout
        assert "batch_count=2" in result.stdout

    @responses.activate
    def test_cli_flag_overrides_config(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _set_cmis_env(monkeypatch)
        _stub_cmis(["TXN_PIPE_001"])
        yaml_path = _write_yaml(tmp_path, batches_in_flight=2)
        result = CliRunner().invoke(
            main,
            [
                "csv-trigger-pipeline",
                "run",
                "--no-tui",
                "--skip-doctor",
                "--batches-in-flight",
                "1",
                "--config",
                str(yaml_path),
            ],
        )
        assert result.exit_code == 0, result.stderr
        assert "TOTALS" not in result.stdout  # forced N=1 → legacy output

    def test_help_lists_batches_in_flight_on_every_pipeline(self) -> None:
        for group in (
            "csv-trigger-pipeline",
            "rvabrep-pipeline",
            "as400-trigger-pipeline",
            "local-scan-pipeline",
            "single-doc",
        ):
            result = CliRunner().invoke(main, [group, "run", "--help"])
            assert result.exit_code == 0
            assert "--batches-in-flight" in result.stdout
