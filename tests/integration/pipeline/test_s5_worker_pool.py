"""Integration tests for the S5 worker pool (025).

Exercises the concurrent upload path with mocked CMIS responses.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest
import responses
from click.testing import CliRunner

from cmcourier.adapters.tracking import SQLiteTrackingStore
from cmcourier.cli.app import main
from cmcourier.domain.models import MigrationRecord, StageStatus

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


def _write_yaml(tmp_path: Path, *, workers: int) -> Path:
    triggers = tmp_path / "triggers.csv"
    triggers.write_text("ShortName,CIF,SystemID\nTESTCLIENT01,123456,1\n")
    yaml_path = tmp_path / "config.yaml"
    yaml_path.write_text(
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
  workers: {workers}
tracking:
  db_path: {tmp_path / "tracking.db"}
observability:
  log_dir: {tmp_path / "logs"}
"""
    )
    return yaml_path


@pytest.fixture
def cli_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("CMIS_USERNAME", "tester")
    monkeypatch.setenv("CMIS_PASSWORD", "secret-not-real")
    yield


class TestS5WorkerPool:
    @responses.activate
    def test_workers_1_sequential_equivalent(self, tmp_path: Path, cli_env: None) -> None:
        _stub_cmis(["TXN_PIPE_001"])
        yaml_path = _write_yaml(tmp_path, workers=1)
        result = CliRunner().invoke(
            main,
            [
                "csv-trigger-pipeline",
                "run",
                "--skip-doctor",
                "--config",
                str(yaml_path),
            ],
        )
        assert result.exit_code == 0, result.stderr
        assert "s5_done=1" in result.stdout

    @responses.activate
    def test_workers_4_parallel_happy_path(self, tmp_path: Path, cli_env: None) -> None:
        _stub_cmis(["TXN_PIPE_001"])
        yaml_path = _write_yaml(tmp_path, workers=4)
        result = CliRunner().invoke(
            main,
            [
                "csv-trigger-pipeline",
                "run",
                "--skip-doctor",
                "--config",
                str(yaml_path),
            ],
        )
        assert result.exit_code == 0, result.stderr
        assert "s5_done=1" in result.stdout

    def test_worker_label_in_slow_op(self, tmp_path: Path) -> None:
        """Synthetic slow-op via the aggregator; assert worker label flows through."""
        from cmcourier.observability.metrics import SlowOpAggregator

        agg = SlowOpAggregator(threshold_ms=0.0, top_n=5)
        agg.consider(
            kind="cmis_upload",
            duration_ms=1000.0,
            txn_num="TXN_TEST",
            worker="cmcourier-s5_3",
        )
        top = agg.top()
        assert len(top) == 1
        assert top[0]["worker"] == "cmcourier-s5_3"

    def test_workers_default_4_when_omitted(self, tmp_path: Path) -> None:
        """Regression: existing YAMLs without cmis.workers default to 4."""
        from cmcourier.config.loader import load_config

        yaml_path = tmp_path / "config.yaml"
        # Build a minimal YAML without cmis.workers.
        triggers = tmp_path / "triggers.csv"
        triggers.write_text("ShortName,CIF,SystemID\n")
        yaml_path.write_text(
            f"""\
trigger:
  csv_path: {triggers}
indexing:
  csv_path: {_PIPELINE_FIXTURES / "rvabrep.csv"}
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
  base_url: http://x:9080/cmis
  repo_id: "$x!t"
tracking:
  db_path: {tmp_path / "tracking.db"}
"""
        )
        config = load_config(yaml_path)
        assert config.cmis.workers == 4

    def test_pool_stats_track_pool_size(self, tmp_path: Path) -> None:
        """Direct check: orchestrator publishes pool_size via WorkerPoolStats."""
        from cmcourier.services.worker_pool_stats import WorkerPoolStats

        stats = WorkerPoolStats()
        stats.set_pool_size(8)
        snap = stats.snapshot()
        assert snap.pool_size == 8

    @responses.activate
    def test_worker_label_logged_in_network_event(self, tmp_path: Path, cli_env: None) -> None:
        """A real workers=4 run writes network events with worker labels to disk."""
        import datetime as _dt
        import json

        _stub_cmis(["TXN_PIPE_001"])
        yaml_path = _write_yaml(tmp_path, workers=4)
        result = CliRunner().invoke(
            main,
            [
                "csv-trigger-pipeline",
                "run",
                "--skip-doctor",
                "--config",
                str(yaml_path),
            ],
        )
        assert result.exit_code == 0, result.stderr
        net_path = tmp_path / "logs" / f"network-{_dt.date.today().isoformat()}.jsonl"
        assert net_path.exists()
        records = [json.loads(ln) for ln in net_path.read_text().splitlines()]
        upload_workers = {r.get("worker") for r in records if r.get("kind") == "cmis_upload"}
        assert any(label and label.startswith("cmcourier-s5") for label in upload_workers), (
            f"no cmis_upload event with S5 worker label; got {upload_workers}"
        )


class TestAutoTuneIntegration:
    @responses.activate
    def test_auto_tune_logs_decision_when_enabled(self, tmp_path: Path, cli_env: None) -> None:
        """End-to-end: enable auto-tune with tight cadence + zero warmup;
        a real run emits at least one ``auto_tune_decision`` log line."""
        import datetime as _dt
        import json
        import time as _time

        _stub_cmis(["TXN_PIPE_001"])
        # Build a YAML with auto-tune enabled + very tight cadence so it
        # fires during the (very short) test run. target_p95_ms is set
        # absurdly high so the AI/noop path triggers immediately.
        triggers = tmp_path / "triggers.csv"
        triggers.write_text("ShortName,CIF,SystemID\nTESTCLIENT01,123456,1\n")
        yaml_path = tmp_path / "config.yaml"
        yaml_path.write_text(
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
  workers: 4
  auto_tune:
    enabled: true
    min_threads: 1
    max_threads: 16
    target_p95_ms: 10000.0
    adjustment_interval_s: 1
    warmup_seconds: 0
    timeout_auto_adjust: true
    min_timeout_s: 30
    max_timeout_s: 600
tracking:
  db_path: {tmp_path / "tracking.db"}
observability:
  log_dir: {tmp_path / "logs"}
"""
        )
        # The S5 stage on a 1-doc batch finishes too fast to give the
        # auto-tune thread a chance to tick (cadence=1s). Patch the
        # uploader's upload() to sleep briefly so S5 is long enough.
        from cmcourier.adapters.upload import cmis_uploader as _cmis_mod

        original_upload = _cmis_mod.CmisUploader.upload

        def slow_upload(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            _time.sleep(1.2)
            return original_upload(self, *args, **kwargs)

        _cmis_mod.CmisUploader.upload = slow_upload  # type: ignore[method-assign]
        try:
            result = CliRunner().invoke(
                main,
                [
                    "csv-trigger-pipeline",
                    "run",
                    "--skip-doctor",
                    "--config",
                    str(yaml_path),
                ],
            )
        finally:
            _cmis_mod.CmisUploader.upload = original_upload  # type: ignore[method-assign]
        assert result.exit_code == 0, result.stderr
        # The app log should record at least one ``auto_tune_decision``.
        app_log = tmp_path / "logs" / f"app-{_dt.date.today().isoformat()}.log"
        assert app_log.exists()
        lines = [json.loads(ln) for ln in app_log.read_text().splitlines()]
        decisions = [ln for ln in lines if ln.get("msg") == "auto_tune_decision"]
        assert decisions, "expected at least one auto_tune_decision event"
        # Action must be one of the documented values.
        actions = {d.get("action") for d in decisions}
        assert actions & {"+1", "halve", "noop", "warmup"}


def test_worker_pool_thread_safety_under_writes(tmp_path: Path) -> None:
    """SQLite store stays consistent under 4 concurrent worker writes."""
    import threading

    store = SQLiteTrackingStore(tmp_path / "concurrent.db")
    try:
        batch_id = store.start_batch(total_records=20)
        records = [
            MigrationRecord(
                trigger_shortname=f"SHORT{i:02d}",
                trigger_cif=f"{i:06d}",
                trigger_system_id="1",
                rvabrep_txn_num=f"TXN_{i:03d}",
                rvabrep_file_name=f"F{i:03d}.001",
                batch_id=batch_id,
                status=StageStatus.S1_PENDING,
                created_at=datetime(2026, 1, 1, 0, 0),
            )
            for i in range(20)
        ]

        def worker(start: int, step: int) -> None:
            for i in range(start, len(records), step):
                store.mark_stage_pending(records[i], StageStatus.S5_PENDING)
                store.mark_stage_done(records[i].rvabrep_txn_num, batch_id, StageStatus.S5_DONE)

        threads = [threading.Thread(target=worker, args=(i, 4)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        store.flush()
        # All 20 should be at S5_DONE.
        for rec in records:
            assert store.is_stage_done(rec.rvabrep_txn_num, batch_id, StageStatus.S5_DONE)
    finally:
        store.close()
