"""Integration tests for ``--total <N>`` flag (033 phase 1).

The flag caps the total number of triggers processed in one
``cmcourier ... run`` invocation. Useful for validating a config
+ environment by running a tiny subset before the full migration.
"""

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
    yaml_path = tmp_path / "config.yaml"
    yaml_path.write_text(
        dedent(
            f"""\
            trigger:
              csv_path: {tmp_path / "triggers.csv"}
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


class TestTotalFlag:
    @responses.activate
    def test_total_caps_n_one(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """N=1 path: 2 triggers in source, --total 1 processes only 1."""
        _set_cmis_env(monkeypatch)
        # Source has both TESTCLIENT01 + TESTCLIENT02.
        triggers = tmp_path / "triggers.csv"
        triggers.write_text(
            "ShortName,CIF,SystemID\nTESTCLIENT01,123456,1\nTESTCLIENT02,123456,1\n"
        )
        _stub_cmis(["TXN_PIPE_001"])  # only one upload expected
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
                "--total",
                "1",
            ],
        )
        assert result.exit_code == 0, result.stderr
        # Only one doc reached S5 — the second trigger was sliced off.
        assert "s5_done=1" in result.stdout
        assert "total_triggers=1" in result.stdout

    @responses.activate
    def test_total_caps_n_two_with_chunks(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """N=2 path: 2 triggers, --total 1, --batch-size 1 → 1 chunk."""
        _set_cmis_env(monkeypatch)
        triggers = tmp_path / "triggers.csv"
        triggers.write_text(
            "ShortName,CIF,SystemID\nTESTCLIENT01,123456,1\nTESTCLIENT02,123456,1\n"
        )
        _stub_cmis(["TXN_PIPE_001"])
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
                "--total",
                "1",
                "--batch-size",
                "1",
            ],
        )
        assert result.exit_code == 0, result.stderr
        # 1 chunk of 1 trigger → legacy single-line output, no TOTALS.
        assert "TOTALS" not in result.stdout
        assert "s5_done=1" in result.stdout

    @responses.activate
    def test_total_larger_than_source_is_noop(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """--total 100 over a 1-trigger source processes the 1 trigger."""
        _set_cmis_env(monkeypatch)
        triggers = tmp_path / "triggers.csv"
        triggers.write_text("ShortName,CIF,SystemID\nTESTCLIENT01,123456,1\n")
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
                "--total",
                "100",
            ],
        )
        assert result.exit_code == 0, result.stderr
        assert "s5_done=1" in result.stdout

    def test_total_zero_rejected(self, tmp_path: Path) -> None:
        """--total 0 is invalid (must be ≥1)."""
        triggers = tmp_path / "triggers.csv"
        triggers.write_text("ShortName,CIF,SystemID\n")
        yaml_path = _write_yaml(tmp_path)
        result = CliRunner().invoke(
            main,
            [
                "csv-trigger-pipeline",
                "run",
                "--config",
                str(yaml_path),
                "--total",
                "0",
            ],
        )
        # Click's IntRange rejects with exit 2.
        assert result.exit_code == 2

    def test_help_lists_total_flag(self) -> None:
        for group in (
            "csv-trigger-pipeline",
            "rvabrep-pipeline",
            "as400-trigger-pipeline",
            "local-scan-pipeline",
        ):
            result = CliRunner().invoke(main, [group, "run", "--help"])
            assert result.exit_code == 0
            assert "--total" in result.stdout, f"--total missing on {group}"
