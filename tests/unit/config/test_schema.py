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
    As400MetadataSourceConfig,
    As400TriggerConfig,
    AssemblyConfig,
    CmisConfigModel,
    CsvMetadataSourceConfig,
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
            "sources": [{"kind": "csv", "alias": "clients", "csv_path": str(clients_csv)}],
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

    def test_local_scan_kind_loads(self, fixture_paths: dict[str, Path], tmp_path: Path) -> None:
        from cmcourier.config.schema import LocalScanTriggerConfig

        data = _build_full_data(
            fixture_paths["trigger"],
            fixture_paths["rvabrep"],
            fixture_paths["modelo"],
            fixture_paths["clients"],
            fixture_paths["assembly_root"],
            tmp_path,
        )
        scan_dir = tmp_path / "scan"
        scan_dir.mkdir()
        data["trigger"] = {"kind": "local_scan", "scan_path": str(scan_dir)}
        config = PipelineConfig.model_validate(data)
        assert isinstance(config.trigger, LocalScanTriggerConfig)
        assert config.trigger.scan_path == scan_dir

    def test_local_scan_requires_existing_path(
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
        data["trigger"] = {
            "kind": "local_scan",
            "scan_path": str(tmp_path / "does_not_exist"),
        }
        with pytest.raises(ValidationError):
            PipelineConfig.model_validate(data)

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

    def test_single_doc_kind_loads(self, fixture_paths: dict[str, Path], tmp_path: Path) -> None:
        from cmcourier.config.schema import SingleDocTriggerConfig

        data = _build_full_data(
            fixture_paths["trigger"],
            fixture_paths["rvabrep"],
            fixture_paths["modelo"],
            fixture_paths["clients"],
            fixture_paths["assembly_root"],
            tmp_path,
        )
        data["trigger"] = {"kind": "single_doc"}
        config = PipelineConfig.model_validate(data)
        assert isinstance(config.trigger, SingleDocTriggerConfig)
        assert config.trigger.kind == "single_doc"

    def test_single_doc_rejects_extra_fields(
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
        data["trigger"] = {"kind": "single_doc", "shortname": "X"}
        with pytest.raises(ValidationError):
            PipelineConfig.model_validate(data)


# ---------------------------------------------------------------------------
# Metadata source discriminated union (015)
# ---------------------------------------------------------------------------


class TestMetadataSourceDiscriminatedUnion:
    def test_csv_kind_loads(self, fixture_paths: dict[str, Path], tmp_path: Path) -> None:
        data = _build_full_data(
            fixture_paths["trigger"],
            fixture_paths["rvabrep"],
            fixture_paths["modelo"],
            fixture_paths["clients"],
            fixture_paths["assembly_root"],
            tmp_path,
        )
        # Already kind=csv by helper. Verify the discriminated union picks it.
        config = PipelineConfig.model_validate(data)
        source = config.metadata.sources[0]
        assert isinstance(source, CsvMetadataSourceConfig)
        assert source.kind == "csv"

    def test_as400_kind_loads(self, fixture_paths: dict[str, Path], tmp_path: Path) -> None:
        data = _build_full_data(
            fixture_paths["trigger"],
            fixture_paths["rvabrep"],
            fixture_paths["modelo"],
            fixture_paths["clients"],
            fixture_paths["assembly_root"],
            tmp_path,
        )
        data["metadata"]["sources"] = [
            {
                "kind": "as400",
                "alias": "customers",
                "as400_connection": {"host": "10.0.0.1"},
                "table": "CUSTOMERS",
            }
        ]
        config = PipelineConfig.model_validate(data)
        source = config.metadata.sources[0]
        assert isinstance(source, As400MetadataSourceConfig)
        assert source.alias == "customers"
        assert source.table == "CUSTOMERS"
        assert source.as400_connection.host == "10.0.0.1"

    def test_as400_table_required_non_empty(self) -> None:
        with pytest.raises(ValidationError):
            As400MetadataSourceConfig(
                kind="as400",
                alias="x",
                as400_connection=As400ConnectionConfig(host="h"),
                table="",
            )

    def test_as400_with_query_loads(self, fixture_paths: dict[str, Path], tmp_path: Path) -> None:
        data = _build_full_data(
            fixture_paths["trigger"],
            fixture_paths["rvabrep"],
            fixture_paths["modelo"],
            fixture_paths["clients"],
            fixture_paths["assembly_root"],
            tmp_path,
        )
        data["metadata"]["sources"] = [
            {
                "kind": "as400",
                "alias": "customers",
                "as400_connection": {"host": "10.0.0.1"},
                "query": "SELECT CIF, NAME FROM CUSTOMERS WHERE ACTIVE = 'Y'",
            }
        ]
        config = PipelineConfig.model_validate(data)
        source = config.metadata.sources[0]
        assert isinstance(source, As400MetadataSourceConfig)
        assert source.table is None
        assert source.query == "SELECT CIF, NAME FROM CUSTOMERS WHERE ACTIVE = 'Y'"

    def test_as400_both_table_and_query_rejected(self) -> None:
        with pytest.raises(ValidationError) as ei:
            As400MetadataSourceConfig(
                kind="as400",
                alias="x",
                as400_connection=As400ConnectionConfig(host="h"),
                table="CUSTOMERS",
                query="SELECT * FROM CUSTOMERS",
            )
        assert "exactly one" in str(ei.value)

    def test_as400_neither_table_nor_query_rejected(self) -> None:
        with pytest.raises(ValidationError) as ei:
            As400MetadataSourceConfig(
                kind="as400",
                alias="x",
                as400_connection=As400ConnectionConfig(host="h"),
            )
        assert "exactly one" in str(ei.value)


# ---------------------------------------------------------------------------
# 020 — Observability config
# ---------------------------------------------------------------------------


class TestObservabilityConfig:
    def test_defaults(self) -> None:
        from cmcourier.config.schema import ObservabilityConfig

        cfg = ObservabilityConfig()
        assert cfg.enabled is True
        assert cfg.pipeline_metrics is True
        assert cfg.network_metrics is True
        assert cfg.system_metrics is False
        assert cfg.log_dir == Path("./logs")
        assert cfg.log_format == "json"
        assert cfg.rotation_mb == 100
        assert cfg.retention_days == 30
        assert cfg.slow_op_threshold_ms == 5000
        assert cfg.slow_op_top_n == 20

    def test_system_metrics_true_rejected(self) -> None:
        from cmcourier.config.schema import ObservabilityConfig

        with pytest.raises(ValidationError) as ei:
            ObservabilityConfig(system_metrics=True)
        assert "post-MVP" in str(ei.value)

    def test_log_format_invalid_rejected(self) -> None:
        from cmcourier.config.schema import ObservabilityConfig

        with pytest.raises(ValidationError):
            ObservabilityConfig(log_format="xml")  # type: ignore[arg-type]

    def test_rotation_mb_must_be_ge_one(self) -> None:
        from cmcourier.config.schema import ObservabilityConfig

        with pytest.raises(ValidationError):
            ObservabilityConfig(rotation_mb=0)

    def test_pipeline_config_observability_defaults_when_absent(
        self, fixture_paths: dict[str, Path], tmp_path: Path
    ) -> None:
        # Regression: existing YAMLs without observability block still validate.
        from cmcourier.config.schema import ObservabilityConfig

        data = _build_full_data(
            fixture_paths["trigger"],
            fixture_paths["rvabrep"],
            fixture_paths["modelo"],
            fixture_paths["clients"],
            fixture_paths["assembly_root"],
            tmp_path,
        )
        config = PipelineConfig.model_validate(data)
        assert isinstance(config.observability, ObservabilityConfig)
        assert config.observability.enabled is True


# ---------------------------------------------------------------------------
# 025 — AutoTuneConfig + cmis.workers/auto_tune
# ---------------------------------------------------------------------------


class TestAutoTuneConfig:
    def test_defaults(self) -> None:
        from cmcourier.config.schema import AutoTuneConfig

        cfg = AutoTuneConfig()
        assert cfg.enabled is False
        assert cfg.min_threads == 2
        assert cfg.max_threads == 50
        assert cfg.target_p95_ms == 5000.0
        assert cfg.adjustment_interval_s == 30
        assert cfg.warmup_seconds == 60
        assert cfg.timeout_auto_adjust is True
        assert cfg.min_timeout_s == 30
        assert cfg.max_timeout_s == 600

    def test_min_greater_than_max_threads_rejected(self) -> None:
        from cmcourier.config.schema import AutoTuneConfig

        with pytest.raises(ValidationError) as ei:
            AutoTuneConfig(min_threads=50, max_threads=10)
        assert "min_threads" in str(ei.value)

    def test_min_greater_than_max_timeout_rejected(self) -> None:
        from cmcourier.config.schema import AutoTuneConfig

        with pytest.raises(ValidationError) as ei:
            AutoTuneConfig(min_timeout_s=600, max_timeout_s=30)
        assert "min_timeout_s" in str(ei.value)

    def test_target_p95_must_be_positive(self) -> None:
        from cmcourier.config.schema import AutoTuneConfig

        with pytest.raises(ValidationError):
            AutoTuneConfig(target_p95_ms=0)

    def test_warmup_zero_allowed(self) -> None:
        from cmcourier.config.schema import AutoTuneConfig

        cfg = AutoTuneConfig(warmup_seconds=0)
        assert cfg.warmup_seconds == 0


class TestCmisWorkersAndAutoTune:
    def test_cmis_defaults_include_workers(self) -> None:
        from cmcourier.config.schema import AutoTuneConfig, CmisConfigModel

        cfg = CmisConfigModel(base_url="http://x:9080/cmis", repo_id="$x!t")
        assert cfg.workers == 4
        assert isinstance(cfg.auto_tune, AutoTuneConfig)
        assert cfg.auto_tune.enabled is False

    def test_cmis_workers_must_be_ge_one(self) -> None:
        from cmcourier.config.schema import CmisConfigModel

        with pytest.raises(ValidationError):
            CmisConfigModel(base_url="x", repo_id="y", workers=0)

    def test_pipeline_config_loads_workers_and_auto_tune(
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
        data["cmis"]["workers"] = 8
        data["cmis"]["auto_tune"] = {
            "enabled": True,
            "target_p95_ms": 2000.0,
        }
        config = PipelineConfig.model_validate(data)
        assert config.cmis.workers == 8
        assert config.cmis.auto_tune.enabled is True
        assert config.cmis.auto_tune.target_p95_ms == 2000.0

    def test_cmis_block_without_workers_uses_defaults(
        self, fixture_paths: dict[str, Path], tmp_path: Path
    ) -> None:
        # Regression: existing YAMLs without cmis.workers / auto_tune still validate.
        data = _build_full_data(
            fixture_paths["trigger"],
            fixture_paths["rvabrep"],
            fixture_paths["modelo"],
            fixture_paths["clients"],
            fixture_paths["assembly_root"],
            tmp_path,
        )
        config = PipelineConfig.model_validate(data)
        assert config.cmis.workers == 4
        assert config.cmis.auto_tune.enabled is False

    def test_unknown_kind_rejected(self, fixture_paths: dict[str, Path], tmp_path: Path) -> None:
        data = _build_full_data(
            fixture_paths["trigger"],
            fixture_paths["rvabrep"],
            fixture_paths["modelo"],
            fixture_paths["clients"],
            fixture_paths["assembly_root"],
            tmp_path,
        )
        data["metadata"]["sources"] = [{"kind": "ldap", "alias": "directory", "url": "ldap://..."}]
        with pytest.raises(ValidationError):
            PipelineConfig.model_validate(data)

    def test_mixed_kinds_load(self, fixture_paths: dict[str, Path], tmp_path: Path) -> None:
        data = _build_full_data(
            fixture_paths["trigger"],
            fixture_paths["rvabrep"],
            fixture_paths["modelo"],
            fixture_paths["clients"],
            fixture_paths["assembly_root"],
            tmp_path,
        )
        data["metadata"]["sources"] = [
            {"kind": "csv", "alias": "clients", "csv_path": str(fixture_paths["clients"])},
            {
                "kind": "as400",
                "alias": "customers",
                "as400_connection": {"host": "10.0.0.1"},
                "table": "CUSTOMERS",
            },
        ]
        config = PipelineConfig.model_validate(data)
        assert len(config.metadata.sources) == 2
        assert isinstance(config.metadata.sources[0], CsvMetadataSourceConfig)
        assert isinstance(config.metadata.sources[1], As400MetadataSourceConfig)
