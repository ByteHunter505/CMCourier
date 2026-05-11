"""Integration tests for ``cmcourier.config.wiring.build_pipeline``."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest
import responses

from cmcourier.config.loader import Secrets, load_config
from cmcourier.config.wiring import build_pipeline
from cmcourier.domain.exceptions import ConfigurationError
from cmcourier.orchestrators.staged import StagedPipeline

pytestmark = pytest.mark.integration

_TESTS_ROOT = Path(__file__).parent.parent.parent
_PIPELINE_FIXTURES = _TESTS_ROOT / "fixtures" / "pipeline"
_SERVICES_FIXTURES = _TESTS_ROOT / "fixtures" / "services"
_ASSEMBLY_FIXTURES = _TESTS_ROOT / "fixtures" / "assembly"

_CMIS_BASE_URL = "http://cmis.example.test:9080/opencmcmis/browser"
_CMIS_REPO_ID = "$x!testrepo"


def _write_yaml(tmp_path: Path, *, triggers_path: Path | None = None) -> Path:
    triggers = triggers_path or (tmp_path / "triggers.csv")
    if not triggers.exists():
        triggers.write_text("ShortName,CIF,SystemID\nTESTCLIENT01,123456,1\n")
    yaml_path = tmp_path / "config.yaml"
    yaml_path.write_text(
        dedent(
            f"""\
            trigger:
              csv_path: {triggers}
              shortname_column: ShortName
              cif_column: CIF
              system_id_column: SystemID
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
            """
        )
    )
    return yaml_path


def _secrets() -> Secrets:
    return Secrets(cmis_username="tester", cmis_password="secret-not-real")


def _register_cmis_for_doc(txn: str) -> None:
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
    responses.add(
        responses.POST,
        f"{_CMIS_BASE_URL}/{_CMIS_REPO_ID}/root/$type/BAC_04_01_01_01_01",
        json={"succinctProperties": {"cmis:objectId": f"cm-{txn}"}},
        status=201,
    )


class TestBuildPipeline:
    @responses.activate
    def test_returns_pipeline_runs_end_to_end(self, tmp_path: Path) -> None:
        yaml_path = _write_yaml(tmp_path)
        config = load_config(yaml_path)
        pipeline = build_pipeline(config, _secrets())
        assert isinstance(pipeline, StagedPipeline)
        _register_cmis_for_doc("TXN_PIPE_001")
        triggers = config.trigger.csv_path
        report = pipeline.run(source_descriptor=str(triggers))
        assert report.s5_done == 1
        assert report.s5_failed == 0

    def test_repeated_calls_produce_independent_pipelines(self, tmp_path: Path) -> None:
        yaml_path = _write_yaml(tmp_path)
        config = load_config(yaml_path)
        p1 = build_pipeline(config, _secrets())
        p2 = build_pipeline(config, _secrets())
        assert p1 is not p2
        assert isinstance(p1, StagedPipeline)
        assert isinstance(p2, StagedPipeline)

    def test_as400_metadata_source_builds(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Build a YAML with an additional as400 metadata source. pyodbc is
        # mocked so the As400DataSource constructor doesn't try to connect
        # (it doesn't — connection is lazy in _connect()).
        yaml_path = _write_yaml(tmp_path)
        text = yaml_path.read_text()
        text = text.replace(
            "  sources:\n    - alias: clients",
            "  sources:\n"
            "    - kind: as400\n"
            "      alias: customers\n"
            "      as400_connection:\n"
            '        host: "10.0.0.1"\n'
            "      table: CUSTOMERS\n"
            "    - alias: clients",
            1,
        )
        yaml_path.write_text(text)
        config = load_config(yaml_path)
        secrets = Secrets(
            cmis_username="tester",
            cmis_password="secret-not-real",
            as400_username="as400tester",
            as400_password="as400secret",
        )
        pipeline = build_pipeline(config, secrets)
        # Inspect MetadataService's registered sources.
        registry = pipeline._metadata_service._sources_registry  # type: ignore[attr-defined]
        assert "customers" in registry
        assert "clients" in registry

    def test_as400_metadata_source_missing_secret_raises(self, tmp_path: Path) -> None:
        yaml_path = _write_yaml(tmp_path)
        text = yaml_path.read_text()
        text = text.replace(
            "  sources:\n    - alias: clients",
            "  sources:\n"
            "    - kind: as400\n"
            "      alias: customers\n"
            "      as400_connection:\n"
            '        host: "10.0.0.1"\n'
            "      table: CUSTOMERS\n"
            "    - alias: clients",
            1,
        )
        yaml_path.write_text(text)
        config = load_config(yaml_path)
        # _secrets() returns AS400 creds empty.
        with pytest.raises(ConfigurationError) as ei:
            build_pipeline(config, _secrets())
        assert ei.value.context["alias"] == "customers"
        assert "AS400_USERNAME" in ei.value.context["missing_vars"]
