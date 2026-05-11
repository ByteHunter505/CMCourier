"""End-to-end integration tests for observability tiers.

Exercises ``observability.setup.configure`` plus the orchestrator
and adapters as a unit. Asserts the right JSON Lines files come out
of a real pipeline run with mocked CMIS network (responses lib).
"""

from __future__ import annotations

import datetime as _dt
import json
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


def _stub_cmis(txns: list[str]) -> None:
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
    for txn in txns:
        responses.add(
            responses.POST,
            f"{_CMIS_BASE_URL}/{_CMIS_REPO_ID}/root/$type/BAC_04_01_01_01_01",
            json={"succinctProperties": {"cmis:objectId": f"cm-{txn}"}},
            status=201,
        )


def _write_yaml(tmp_path: Path, *, slow_op_threshold_ms: int = 0) -> Path:
    """Build a working csv-trigger config + observability block."""
    triggers = tmp_path / "triggers.csv"
    triggers.write_text("ShortName,CIF,SystemID\nTESTCLIENT01,123456,1\n")
    log_dir = tmp_path / "logs"
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
            observability:
              log_dir: {log_dir}
              slow_op_threshold_ms: {slow_op_threshold_ms}
              slow_op_top_n: 5
            """
        )
    )
    return yaml_path


def _cli_runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def cmis_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CMIS_USERNAME", "tester")
    monkeypatch.setenv("CMIS_PASSWORD", "secret-not-real")


# ---------------------------------------------------------------------------
# End-to-end emissions
# ---------------------------------------------------------------------------


class TestPipelineEmits:
    @responses.activate
    def test_pipeline_run_writes_app_log_and_metrics(self, tmp_path: Path, cmis_env: None) -> None:
        _stub_cmis(["TXN_PIPE_001"])
        yaml_path = _write_yaml(tmp_path)
        result = _cli_runner().invoke(
            main, ["csv-trigger-pipeline", "run", "--config", str(yaml_path)]
        )
        assert result.exit_code == 0, result.output
        log_dir = tmp_path / "logs"
        today = _dt.date.today().isoformat()
        app_log = log_dir / f"app-{today}.log"
        metrics_log = log_dir / f"metrics-{today}.jsonl"
        network_log = log_dir / f"network-{today}.jsonl"
        assert app_log.exists()
        assert metrics_log.exists()
        # One batch summary line.
        summary_lines = metrics_log.read_text().splitlines()
        assert len(summary_lines) == 1
        summary = json.loads(summary_lines[0])
        assert summary["kind"] == "batch_summary"
        assert summary["pipeline"] == "csv-trigger"
        assert summary["total_docs"] >= 1
        assert "S5" in summary["stages"]
        # Network log got at least one cmis_upload + cmis_get warmup.
        assert network_log.exists()
        net_lines = [json.loads(ln) for ln in network_log.read_text().splitlines()]
        kinds = {ln["kind"] for ln in net_lines}
        assert "cmis_upload" in kinds
        assert "cmis_get" in kinds

    @responses.activate
    def test_slow_ops_file_created_with_low_threshold(self, tmp_path: Path, cmis_env: None) -> None:
        _stub_cmis(["TXN_PIPE_001"])
        yaml_path = _write_yaml(tmp_path, slow_op_threshold_ms=0)
        result = _cli_runner().invoke(
            main, ["csv-trigger-pipeline", "run", "--config", str(yaml_path)]
        )
        assert result.exit_code == 0, result.output
        log_dir = tmp_path / "logs"
        slow_files = list(log_dir.glob("slow-ops-*.jsonl"))
        assert len(slow_files) == 1
        entries = [json.loads(ln) for ln in slow_files[0].read_text().splitlines()]
        # threshold=0 means everything is a slow op; top_n=5 → at most 5 lines.
        assert 1 <= len(entries) <= 5
        # Each entry has rank + kind + duration_ms.
        for entry in entries:
            assert "rank" in entry
            assert "kind" in entry
            assert "duration_ms" in entry

    @responses.activate
    def test_pii_value_never_appears_in_app_log(self, tmp_path: Path, cmis_env: None) -> None:
        _stub_cmis(["TXN_PIPE_001"])
        yaml_path = _write_yaml(tmp_path)
        _ = _cli_runner().invoke(main, ["csv-trigger-pipeline", "run", "--config", str(yaml_path)])
        # Directly emit a record with a PII extra to verify masking.
        cif_value = "SECRET_CIF_999"
        logging.getLogger("cmcourier").info("test_event_with_pii", extra={"cif": cif_value})
        # Flush handlers so the file is up to date.
        for h in logging.getLogger("cmcourier").handlers:
            h.flush()
        today = _dt.date.today().isoformat()
        app_log = tmp_path / "logs" / f"app-{today}.log"
        content = app_log.read_text(encoding="utf-8")
        # The original CIF value must not appear anywhere in the file.
        assert cif_value not in content
        # The event itself is logged (we can find the marker msg) but the
        # PII payload — masked or not — was dropped by the schema-stable
        # formatter that only promotes whitelisted fields. Either way,
        # the customer's CIF value is unreachable.
        assert "test_event_with_pii" in content
