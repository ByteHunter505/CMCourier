"""Integration tests for ``cmcourier background --pipeline <kind>`` (024)."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest
import responses
from click.testing import CliRunner

from cmcourier.cli.app import main
from cmcourier.cli.commands._lock import acquire_config_lock

pytestmark = [pytest.mark.integration, pytest.mark.slow]

# Cron-canonical "transient failure" exit code. Hardcoded because ``os.EX_TEMPFAIL``
# only exists on POSIX Python builds; the production code in
# ``cli/commands/background.py`` uses the same literal.
_EXIT_TEMPFAIL = 75

_TESTS_ROOT = Path(__file__).parent.parent.parent
_PIPELINE_FIXTURES = _TESTS_ROOT / "fixtures" / "pipeline"
_SERVICES_FIXTURES = _TESTS_ROOT / "fixtures" / "services"
_ASSEMBLY_FIXTURES = _TESTS_ROOT / "fixtures" / "assembly"

_CMIS_BASE_URL = "http://cmis.example.test:9080/opencmcmis/browser"
_CMIS_REPO_ID = "$x!testrepo"


@pytest.fixture(autouse=True)
def isolated_runtime_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Pin XDG_RUNTIME_DIR per test so lock files don't collide."""
    runtime = tmp_path / "xdg-runtime"
    runtime.mkdir()
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    return runtime


def _set_cmis_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CMIS_USERNAME", "tester")
    monkeypatch.setenv("CMIS_PASSWORD", "secret-not-real")


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
            """
        )
    )
    return yaml_path


class TestBackgroundHelp:
    def test_help_lists_flags(self) -> None:
        result = CliRunner().invoke(main, ["background", "--help"])
        assert result.exit_code == 0
        for flag in (
            "--pipeline",
            "--config",
            "--batch-id",
            "--from-stage",
            "--batch-size",
            "--skip-doctor",
            "--resume",
            "--log-level",
        ):
            assert flag in result.stdout

    def test_unknown_pipeline_rejected(self, tmp_path: Path) -> None:
        yaml_path = _write_yaml(tmp_path)
        result = CliRunner().invoke(
            main,
            [
                "background",
                "--pipeline",
                "single-doc",
                "-c",
                str(yaml_path),
            ],
        )
        assert result.exit_code == 2


class TestBackgroundHappyPath:
    @responses.activate
    def test_quiet_success(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _set_cmis_env(monkeypatch)
        _register_cmis_for_docs(["TXN_PIPE_001"])
        yaml_path = _write_yaml(tmp_path)
        result = CliRunner().invoke(
            main,
            [
                "background",
                "--pipeline",
                "csv-trigger",
                "-c",
                str(yaml_path),
                "--skip-doctor",
            ],
        )
        assert result.exit_code == 0, result.output
        # Quiet mode: no batch summary line on stdout.
        assert "s5_done=" not in result.stdout
        assert "batch_id=" not in result.stdout


class TestBackgroundLockContention:
    def test_lock_held_exits_75(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _set_cmis_env(monkeypatch)
        yaml_path = _write_yaml(tmp_path)
        # Hold the lock; the CLI invocation below should reject.
        with acquire_config_lock(yaml_path) as lock_path:
            result = CliRunner().invoke(
                main,
                [
                    "background",
                    "--pipeline",
                    "csv-trigger",
                    "-c",
                    str(yaml_path),
                    "--skip-doctor",
                ],
            )
        assert result.exit_code == _EXIT_TEMPFAIL
        assert "Another instance is running" in result.stderr
        assert str(lock_path) in result.stderr

    def test_lock_released_after_run(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _set_cmis_env(monkeypatch)
        yaml_path = _write_yaml(tmp_path)
        # Pre-run: acquire and release.
        with acquire_config_lock(yaml_path):
            pass
        # Post-release: same config can be acquired again immediately.
        with acquire_config_lock(yaml_path):
            pass
