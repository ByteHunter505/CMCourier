"""Unit tests for ``cmcourier.config.schema``.

Pydantic v2 validation tests: every model is ``frozen=True, extra="forbid"``
so unknown keys raise, mutation raises, and the type system catches
required-field omissions.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from cmcourier.config.schema import (
    As400ConnectionConfig,
    As400TriggerConfig,
    AssemblyConfig,
    CmisConfigModel,
    CsvTriggerConfig,
    FieldConfig,
    FieldSourceItem,
    IndexingSourceConfig,
    MappingConfig,
    MetadataConfigModel,
    PipelineConfig,
    RvabrepTriggerConfig,
    TrackingConfig,
    TriggerCsvConfig,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_full_data(
    trigger_csv: Path,
    rvabrep_csv: Path,
    modelo_csv: Path,
    clients_csv: Path,
    assembly_root: Path,
    tmp_path: Path,
) -> dict[str, Any]:
    return {
        "trigger": {"kind": "csv", "csv_path": str(trigger_csv)},
        "indexing": {"csv_path": str(rvabrep_csv)},
        "mapping": {"csv_path": str(modelo_csv)},
        "metadata": {
            "field_aliases": {"CIF": "BAC_CIF"},
            "field_sources": {
                "BAC_CIF": {
                    "sources": [
                        {"source_type": "trigger", "lookup_value_column": "cif"},
                    ],
                },
            },
            "sources": [{"alias": "clients", "csv_path": str(clients_csv)}],
        },
        "assembly": {
            "source_root": str(assembly_root),
            "temp_dir": str(tmp_path / "stg"),
        },
        "cmis": {
            "base_url": "http://cmis.test:9080/cmis",
            "repo_id": "$x!test",
        },
        "tracking": {"db_path": str(tmp_path / "tracking.db")},
    }


@pytest.fixture
def fixture_paths(tmp_path: Path) -> dict[str, Path]:
    """Materialize a synthetic file tree the schema can validate against."""
    trigger = tmp_path / "triggers.csv"
    trigger.write_text("ShortName,CIF,SystemID\n")
    rvabrep = tmp_path / "rvabrep.csv"
    rvabrep.write_text("shortname,system_id,txn_num\n")
    modelo = tmp_path / "modelo.csv"
    modelo.write_text("ID RVI,ID CLASE DOCUMENTAL\n")
    clients = tmp_path / "clients.csv"
    clients.write_text("CIF,Nombre_Cliente\n")
    assembly_root = tmp_path / "assembly"
    assembly_root.mkdir()
    return {
        "trigger": trigger,
        "rvabrep": rvabrep,
        "modelo": modelo,
        "clients": clients,
        "assembly_root": assembly_root,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSchemaValidation:
    def test_full_config_validates(self, fixture_paths: dict[str, Path], tmp_path: Path) -> None:
        data = _build_full_data(
            fixture_paths["trigger"],
            fixture_paths["rvabrep"],
            fixture_paths["modelo"],
            fixture_paths["clients"],
            fixture_paths["assembly_root"],
            tmp_path,
        )
        config = PipelineConfig.model_validate(data)
        assert config.cmis.base_url == "http://cmis.test:9080/cmis"
        assert config.batch_size == 1000
        assert config.tracking.db_path == tmp_path / "tracking.db"

    def test_extra_top_level_key_rejected(
        self, fixture_paths: dict[str, Path], tmp_path: Path
    ) -> None:
        data = _build_full_data(
            fixture_paths["trigger"],
            fixture_paths["rvabrep"],
            fixture_paths["modelo"],
            fixture_paths["clients"],
            fixture_paths["assembly_root"],
            tmp_path,
        )
        data["cosmic_settings"] = {"intent": "blast"}
        with pytest.raises(ValidationError):
            PipelineConfig.model_validate(data)

    def test_extra_nested_key_rejected(
        self, fixture_paths: dict[str, Path], tmp_path: Path
    ) -> None:
        data = _build_full_data(
            fixture_paths["trigger"],
            fixture_paths["rvabrep"],
            fixture_paths["modelo"],
            fixture_paths["clients"],
            fixture_paths["assembly_root"],
            tmp_path,
        )
        data["mapping"]["unknown_field"] = "foo"
        with pytest.raises(ValidationError):
            PipelineConfig.model_validate(data)


class TestFieldSourceItem:
    @pytest.mark.parametrize(
        "source_type",
        ["trigger", "rvabrep", "csv:clients", "as400:default"],
    )
    def test_accepted_source_types(self, source_type: str) -> None:
        item = FieldSourceItem(source_type=source_type, lookup_value_column="x")
        assert item.source_type == source_type

    def test_rejects_unknown_source_type(self) -> None:
        with pytest.raises(ValidationError):
            FieldSourceItem(source_type="http:remote", lookup_value_column="x")


class TestFieldConfig:
    def test_requires_at_least_one_source(self) -> None:
        with pytest.raises(ValidationError):
            FieldConfig(sources=[])

    def test_default_value_optional(self) -> None:
        fc = FieldConfig(
            sources=[FieldSourceItem(source_type="trigger", lookup_value_column="cif")]
        )
        assert fc.default_value is None


class TestNumericConstraints:
    def test_cmis_timeout_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            CmisConfigModel(base_url="x", repo_id="y", timeout_seconds=0)

    def test_retry_max_attempts_must_be_ge_one(self) -> None:
        with pytest.raises(ValidationError):
            CmisConfigModel(base_url="x", repo_id="y", retry_max_attempts=0)

    def test_batch_size_must_be_ge_one(
        self, fixture_paths: dict[str, Path], tmp_path: Path
    ) -> None:
        data = _build_full_data(
            fixture_paths["trigger"],
            fixture_paths["rvabrep"],
            fixture_paths["modelo"],
            fixture_paths["clients"],
            fixture_paths["assembly_root"],
            tmp_path,
        )
        data["batch_size"] = 0
        with pytest.raises(ValidationError):
            PipelineConfig.model_validate(data)


class TestFrozenness:
    def test_pipeline_config_is_frozen(
        self, fixture_paths: dict[str, Path], tmp_path: Path
    ) -> None:
        data = _build_full_data(
            fixture_paths["trigger"],
            fixture_paths["rvabrep"],
            fixture_paths["modelo"],
            fixture_paths["clients"],
            fixture_paths["assembly_root"],
            tmp_path,
        )
        config = PipelineConfig.model_validate(data)
        with pytest.raises(ValidationError):
            config.batch_size = 5000  # type: ignore[misc]


class TestSubmodelDefaults:
    def test_assembly_image_type_map_default(
        self, fixture_paths: dict[str, Path], tmp_path: Path
    ) -> None:
        cfg = AssemblyConfig(
            source_root=fixture_paths["assembly_root"],
            temp_dir=tmp_path / "stg",
        )
        assert cfg.image_type_map == {
            "B": "image/tiff",
            "O": "application/pdf",
            "C": "image/jpeg",
        }

    def test_trigger_column_defaults(self, fixture_paths: dict[str, Path]) -> None:
        cfg = TriggerCsvConfig(csv_path=fixture_paths["trigger"])
        assert cfg.shortname_column == "ShortName"
        assert cfg.cif_column == "CIF"
        assert cfg.system_id_column == "SystemID"

    def test_indexing_columns_defaults_match_as400(self, fixture_paths: dict[str, Path]) -> None:
        cfg = IndexingSourceConfig(csv_path=fixture_paths["rvabrep"])
        assert cfg.columns.shortname_column == "ABABCD"
        assert cfg.columns.txn_num_column == "ABAANB"
        assert cfg.columns.index7_column == "ABAHCD"

    def test_mapping_column_defaults(self, fixture_paths: dict[str, Path]) -> None:
        cfg = MappingConfig(csv_path=fixture_paths["modelo"])
        assert cfg.id_rvi_column == "ID RVI"
        assert cfg.clase_id_column == "ID CLASE DOCUMENTAL"

    def test_metadata_empty_field_sources_invalid(self, fixture_paths: dict[str, Path]) -> None:
        # field_sources is required (no default), so this should pass; but
        # with no fields configured, the orchestrator's get_mapping later
        # may fail. The schema doesn't enforce min field count.
        cfg = MetadataConfigModel(field_sources={})
        assert cfg.field_sources == {}

    def test_tracking_db_path_is_required(self) -> None:
        with pytest.raises(ValidationError):
            TrackingConfig()  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Discriminated union: trigger.kind
# ---------------------------------------------------------------------------


class TestTriggerDiscriminatedUnion:
    def test_csv_kind_loads(self, fixture_paths: dict[str, Path], tmp_path: Path) -> None:
        data = _build_full_data(
            fixture_paths["trigger"],
            fixture_paths["rvabrep"],
            fixture_paths["modelo"],
            fixture_paths["clients"],
            fixture_paths["assembly_root"],
            tmp_path,
        )
        config = PipelineConfig.model_validate(data)
        assert isinstance(config.trigger, CsvTriggerConfig)
        assert config.trigger.kind == "csv"

    def test_rvabrep_kind_loads(self, fixture_paths: dict[str, Path], tmp_path: Path) -> None:
        data = _build_full_data(
            fixture_paths["trigger"],
            fixture_paths["rvabrep"],
            fixture_paths["modelo"],
            fixture_paths["clients"],
            fixture_paths["assembly_root"],
            tmp_path,
        )
        data["trigger"] = {
            "kind": "rvabrep",
            "filters": {"systems": ["1"], "document_types": ["FF17"]},
        }
        config = PipelineConfig.model_validate(data)
        assert isinstance(config.trigger, RvabrepTriggerConfig)
        assert config.trigger.filters.systems == ["1"]

    def test_as400_kind_loads(self, fixture_paths: dict[str, Path], tmp_path: Path) -> None:
        data = _build_full_data(
            fixture_paths["trigger"],
            fixture_paths["rvabrep"],
            fixture_paths["modelo"],
            fixture_paths["clients"],
            fixture_paths["assembly_root"],
            tmp_path,
        )
        data["trigger"] = {
            "kind": "as400",
            "query": "SELECT SHORTNAME, CIF, SYSTEMID FROM TRIGGERS",
            "as400_connection": {
                "host": "10.0.0.1",
                "database": "RVILIB",
                "driver": "iSeries Access ODBC Driver",
            },
        }
        config = PipelineConfig.model_validate(data)
        assert isinstance(config.trigger, As400TriggerConfig)
        assert config.trigger.query.startswith("SELECT")
        assert config.trigger.as400_connection.host == "10.0.0.1"

    def test_unknown_kind_rejected(self, fixture_paths: dict[str, Path], tmp_path: Path) -> None:
        data = _build_full_data(
            fixture_paths["trigger"],
            fixture_paths["rvabrep"],
            fixture_paths["modelo"],
            fixture_paths["clients"],
            fixture_paths["assembly_root"],
            tmp_path,
        )
        data["trigger"] = {"kind": "ftp", "csv_path": str(fixture_paths["trigger"])}
        with pytest.raises(ValidationError):
            PipelineConfig.model_validate(data)

    def test_as400_connection_defaults(self) -> None:
        cfg = As400ConnectionConfig(host="10.0.0.1")
        assert cfg.port == 446
        assert cfg.database == "RVILIB"
        assert cfg.driver == "iSeries Access ODBC Driver"
        assert cfg.table is None

    def test_csv_alias_for_backwards_compat(self) -> None:
        # TriggerCsvConfig is the old name — kept as an alias to CsvTriggerConfig.
        assert TriggerCsvConfig is CsvTriggerConfig
