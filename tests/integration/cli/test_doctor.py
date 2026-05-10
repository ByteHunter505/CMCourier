"""Integration tests for ``cmcourier doctor``."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest
import responses
from click.testing import CliRunner

from cmcourier.cli.app import main
from cmcourier.cli.doctor import CheckStatus, run_doctor
from cmcourier.config.loader import Secrets, load_config

pytestmark = [pytest.mark.integration, pytest.mark.slow]

_TESTS_ROOT = Path(__file__).parent.parent.parent
_PIPELINE_FIXTURES = _TESTS_ROOT / "fixtures" / "pipeline"
_SERVICES_FIXTURES = _TESTS_ROOT / "fixtures" / "services"
_ASSEMBLY_FIXTURES = _TESTS_ROOT / "fixtures" / "assembly"

_CMIS_BASE_URL = "http://cmis.example.test:9080/opencmcmis/browser"
_CMIS_REPO_ID = "$x!testrepo"

# The Modelo Documental fixture has these distinct cm_object_types after
# the FF17 duplicate is dropped (first-wins).
_DISTINCT_TYPES: tuple[str, ...] = (
    "$t!-2_BAC_01_02_04_01_01v-1",
    "$t!-2_BAC_02_01_03_01_01v-1",
    "$t!-2_BAC_03_01_01_01_01v-1",
    "$t!-2_BAC_04_01_01_01_01v-1",
    "$t!-2_BAC_05_01_01_01_01v-1",
    "$t!-2_BAC_06_01_01_01_01v-1",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_yaml(
    tmp_path: Path,
    *,
    triggers_csv: Path | None = None,
    mapping_csv: Path | None = None,
    clients_csv: Path | None = None,
) -> Path:
    if triggers_csv is None:
        triggers_csv = tmp_path / "triggers.csv"
        triggers_csv.write_text("ShortName,CIF,SystemID\nTESTCLIENT01,123456,1\n")
    if mapping_csv is None:
        mapping_csv = _SERVICES_FIXTURES / "modelo_documental.csv"
    if clients_csv is None:
        clients_csv = _SERVICES_FIXTURES / "metadata" / "clients.csv"
    yaml_path = tmp_path / "config.yaml"
    yaml_path.write_text(
        dedent(
            f"""\
            trigger:
              csv_path: {triggers_csv}
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
              csv_path: {mapping_csv}
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
                  csv_path: {clients_csv}
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


def _secrets() -> Secrets:
    return Secrets(cmis_username="tester", cmis_password="secret-not-real")


def _stub_warmup_ok() -> None:
    responses.add(
        responses.GET,
        f"{_CMIS_BASE_URL}/{_CMIS_REPO_ID}",
        json={"repositoryId": _CMIS_REPO_ID, "productName": "IBM"},
        status=200,
        match=[responses.matchers.query_param_matcher({"cmisselector": "repositoryInfo"})],
    )


def _stub_type_definitions_ok(types: tuple[str, ...] = _DISTINCT_TYPES) -> None:
    for type_id in types:
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


# ---------------------------------------------------------------------------
# run_doctor happy path
# ---------------------------------------------------------------------------


class TestRunDoctorHappyPath:
    @responses.activate
    def test_all_checks_pass(self, tmp_path: Path) -> None:
        _stub_warmup_ok()
        _stub_type_definitions_ok()
        config = load_config(_write_yaml(tmp_path))
        report = run_doctor(config, _secrets())
        assert not report.has_failures, [
            f"{r.name}: {r.status.value} — {r.message}"
            for r in report.results
            if r.status == CheckStatus.FAIL
        ]
        # PASS for every check except sample_dry_run which depends on
        # filesystem fixtures (also PASS here).
        assert report.passed_count >= 5

    @responses.activate
    def test_check_order_is_stable(self, tmp_path: Path) -> None:
        _stub_warmup_ok()
        _stub_type_definitions_ok()
        config = load_config(_write_yaml(tmp_path))
        report = run_doctor(config, _secrets())
        names = [r.name for r in report.results]
        assert names == [
            "cmis_connectivity",
            "tracking_openable",
            "mapping_completeness",
            "metadata_sources",
            "cm_type_alignment",
            "sample_dry_run",
        ]


# ---------------------------------------------------------------------------
# Individual check failures
# ---------------------------------------------------------------------------


class TestCmisFailures:
    @responses.activate
    def test_cmis_unreachable(self, tmp_path: Path) -> None:
        responses.add(
            responses.GET,
            f"{_CMIS_BASE_URL}/{_CMIS_REPO_ID}",
            json={"error": "boom"},
            status=503,
            match=[responses.matchers.query_param_matcher({"cmisselector": "repositoryInfo"})],
        )
        config = load_config(_write_yaml(tmp_path))
        report = run_doctor(config, _secrets())
        conn_check = next(r for r in report.results if r.name == "cmis_connectivity")
        assert conn_check.status == CheckStatus.FAIL
        # cm_type_alignment must be SKIPped, NOT crash.
        align_check = next(r for r in report.results if r.name == "cm_type_alignment")
        assert align_check.status == CheckStatus.SKIP


class TestTrackingFailures:
    @responses.activate
    def test_tracking_db_in_non_creatable_path(self, tmp_path: Path) -> None:
        _stub_warmup_ok()
        _stub_type_definitions_ok()
        config = load_config(_write_yaml(tmp_path))
        # Inject a non-creatable db_path (under /dev/null which can't have subdirs).
        broken = config.model_copy(
            update={
                "tracking": config.tracking.model_copy(
                    update={"db_path": Path("/dev/null/cmcourier/tracking.db")}
                )
            }
        )
        report = run_doctor(broken, _secrets())
        track_check = next(r for r in report.results if r.name == "tracking_openable")
        assert track_check.status == CheckStatus.FAIL


class TestMappingWarn:
    @responses.activate
    def test_empty_mapping_warns(self, tmp_path: Path) -> None:
        _stub_warmup_ok()
        # Empty mapping CSV (header only).
        empty_mapping = tmp_path / "empty_mapping.csv"
        empty_mapping.write_text("ID CLASE DOCUMENTAL,ID RVI,ID Corto,CLASE DOCUMENTAL,METADATOS\n")
        # No type-definition stubs needed since alignment will see zero types.
        config = load_config(_write_yaml(tmp_path, mapping_csv=empty_mapping))
        report = run_doctor(config, _secrets())
        m_check = next(r for r in report.results if r.name == "mapping_completeness")
        assert m_check.status == CheckStatus.WARN
        assert m_check.details["mapping_count"] == "0"


class TestMetadataWarn:
    @responses.activate
    def test_empty_metadata_source_warns(self, tmp_path: Path) -> None:
        _stub_warmup_ok()
        _stub_type_definitions_ok()
        empty_clients = tmp_path / "empty_clients.csv"
        empty_clients.write_text("CIF,Nombre_Cliente,Tipo_Cliente\n")
        config = load_config(_write_yaml(tmp_path, clients_csv=empty_clients))
        report = run_doctor(config, _secrets())
        md_check = next(r for r in report.results if r.name == "metadata_sources")
        assert md_check.status == CheckStatus.WARN
        assert "clients" in md_check.details["empty_aliases"]


class TestCmTypeMissing:
    @responses.activate
    def test_missing_type_fails(self, tmp_path: Path) -> None:
        _stub_warmup_ok()
        # Register only the FIRST type; the others 404.
        responses.add(
            responses.GET,
            f"{_CMIS_BASE_URL}/{_CMIS_REPO_ID}",
            json={"id": _DISTINCT_TYPES[0]},
            status=200,
            match=[
                responses.matchers.query_param_matcher(
                    {"cmisselector": "typeDefinition", "typeId": _DISTINCT_TYPES[0]}
                )
            ],
        )
        for type_id in _DISTINCT_TYPES[1:]:
            responses.add(
                responses.GET,
                f"{_CMIS_BASE_URL}/{_CMIS_REPO_ID}",
                json={"error": "not found"},
                status=404,
                match=[
                    responses.matchers.query_param_matcher(
                        {"cmisselector": "typeDefinition", "typeId": type_id}
                    )
                ],
            )
        config = load_config(_write_yaml(tmp_path))
        report = run_doctor(config, _secrets())
        align = next(r for r in report.results if r.name == "cm_type_alignment")
        assert align.status == CheckStatus.FAIL
        # All but the first type are missing.
        for type_id in _DISTINCT_TYPES[1:]:
            assert type_id in align.details["missing_types"]


class TestSampleDryRun:
    @responses.activate
    def test_dry_run_pass(self, tmp_path: Path) -> None:
        _stub_warmup_ok()
        _stub_type_definitions_ok()
        config = load_config(_write_yaml(tmp_path))
        report = run_doctor(config, _secrets())
        dry = next(r for r in report.results if r.name == "sample_dry_run")
        assert dry.status == CheckStatus.PASS
        assert dry.details["stages"] == "S1,S2,S3,S4"

    @responses.activate
    def test_dry_run_skip_on_empty_triggers(self, tmp_path: Path) -> None:
        _stub_warmup_ok()
        _stub_type_definitions_ok()
        empty_triggers = tmp_path / "empty_triggers.csv"
        empty_triggers.write_text("ShortName,CIF,SystemID\n")
        config = load_config(_write_yaml(tmp_path, triggers_csv=empty_triggers))
        report = run_doctor(config, _secrets())
        dry = next(r for r in report.results if r.name == "sample_dry_run")
        assert dry.status == CheckStatus.SKIP
        assert dry.details["reason"] == "no_triggers"


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


class TestCli:
    @responses.activate
    def test_doctor_exit_0_happy_path(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("CMIS_USERNAME", "tester")
        monkeypatch.setenv("CMIS_PASSWORD", "secret-not-real")
        _stub_warmup_ok()
        _stub_type_definitions_ok()
        yaml_path = _write_yaml(tmp_path)
        result = cli_runner.invoke(main, ["doctor", "--config", str(yaml_path)])
        assert result.exit_code == 0, result.stderr
        assert "[PASS]" in result.stdout
        assert "0 failed" in result.stdout

    def test_doctor_missing_config_exit_2(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("CMIS_USERNAME", "tester")
        monkeypatch.setenv("CMIS_PASSWORD", "secret-not-real")
        result = cli_runner.invoke(main, ["doctor", "--config", str(tmp_path / "nope.yaml")])
        assert result.exit_code == 2

    @responses.activate
    def test_doctor_exit_1_on_failure(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("CMIS_USERNAME", "tester")
        monkeypatch.setenv("CMIS_PASSWORD", "secret-not-real")
        responses.add(
            responses.GET,
            f"{_CMIS_BASE_URL}/{_CMIS_REPO_ID}",
            json={"error": "boom"},
            status=503,
            match=[responses.matchers.query_param_matcher({"cmisselector": "repositoryInfo"})],
        )
        yaml_path = _write_yaml(tmp_path)
        result = cli_runner.invoke(main, ["doctor", "--config", str(yaml_path)])
        assert result.exit_code == 1
        assert "[FAIL]" in result.stdout
