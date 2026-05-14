"""End-to-end integration test for tier-5 system metrics (026, REQ-018).

Runs a real ``csv-trigger-pipeline`` and asserts that:

* ``logs/system-{today}.jsonl`` is written.
* At least one JSON line is present.
* Every line is valid JSON with the full ``SystemSample`` field set.
* The sampler thread has terminated by the time ``pipeline.run`` returns.
"""

from __future__ import annotations

import json
import threading
from datetime import date
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


def _write_csv_yaml(tmp_path: Path, *, system_metrics_interval_s: float = 1.0) -> Path:
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
            observability:
              log_dir: {tmp_path / "logs"}
              system_metrics:
                enabled: true
                sample_interval_s: {system_metrics_interval_s}
            """
        )
    )
    return yaml_path


_SAMPLE_KEYS = (
    "ts_iso",
    "cpu_pct",
    "ram_used_mb",
    "ram_total_mb",
    "disk_read_mbps",
    "disk_write_mbps",
    "net_in_mbps",
    "net_out_mbps",
    "process_pid",
    "process_threads",
    "process_cpu_pct",
    "process_rss_mb",
    "active_workers",
)


class TestSystemMetricsE2E:
    @responses.activate
    def test_pipeline_run_produces_system_jsonl(
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

        sys_file = tmp_path / "logs" / f"system-{date.today().isoformat()}.jsonl"
        assert sys_file.exists(), "system-<today>.jsonl was not produced"
        lines = sys_file.read_text().strip().splitlines()
        assert len(lines) >= 1
        for line in lines:
            parsed = json.loads(line)
            for key in _SAMPLE_KEYS:
                assert key in parsed, f"missing field {key!r} in sample line"

        # Sampler thread must not survive past pipeline.run.
        live = [t for t in threading.enumerate() if t.name == "cmcourier-syssampler"]
        assert live == []

    @responses.activate
    def test_disabled_yaml_skips_sampler(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _set_cmis_env(monkeypatch)
        _stub_cmis(["TXN_PIPE_001"])
        yaml_path = _write_csv_yaml(tmp_path)
        # Disable system_metrics explicitly in the YAML (post-dedent
        # indentation: 4 spaces for fields under ``observability:``).
        body = yaml_path.read_text().replace(
            "enabled: true",
            "enabled: false",
        )
        assert "system_metrics:\n    enabled: false" in body
        yaml_path.write_text(body)
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
        sys_file = tmp_path / "logs" / f"system-{date.today().isoformat()}.jsonl"
        assert not sys_file.exists()
