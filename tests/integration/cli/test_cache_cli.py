"""Tests de integración para los subcomandos ``cmcourier cache`` (037 Fase 3)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from textwrap import dedent
from types import MappingProxyType

import pytest
from click.testing import CliRunner

from cmcourier.adapters.tracking import SqliteDocumentCache, SQLiteTrackingStore
from cmcourier.cli.app import main
from cmcourier.domain.ports import CacheEntry

pytestmark = pytest.mark.integration

_TESTS_ROOT = Path(__file__).parent.parent.parent
_PIPELINE_FIXTURES = _TESTS_ROOT / "fixtures" / "pipeline"
_SERVICES_FIXTURES = _TESTS_ROOT / "fixtures" / "services"
_ASSEMBLY_FIXTURES = _TESTS_ROOT / "fixtures" / "assembly"


def _write_yaml(tmp_path: Path) -> Path:
    triggers = tmp_path / "triggers.csv"
    triggers.write_text("ShortName,CIF,SystemID\n")
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
              base_url: "http://cmis.test:9080/cmis"
              repo_id: "$x!testrepo"
            tracking:
              db_path: {tmp_path / "tracking.db"}
            """
        )
    )
    return yaml_path


@pytest.fixture
def cache_setup(tmp_path: Path) -> tuple[Path, SqliteDocumentCache]:
    """Provee una config + cache pre-bootstrapeada apuntando a la misma DB."""
    yaml_path = _write_yaml(tmp_path)
    db_path = tmp_path / "tracking.db"
    # Bootstrap del schema tocando el `tracking store`.
    store = SQLiteTrackingStore(db_path)
    store.close()
    cache = SqliteDocumentCache(db_path)
    yield yaml_path, cache
    cache.close()


def _entry(
    txn: str,
    fields_hash: str = "abc123",
    cached_at: datetime | None = None,
) -> CacheEntry:
    return CacheEntry(
        txn_num=txn,
        fields_hash=fields_hash,
        trigger_cif="123",
        properties=MappingProxyType({"BAC_CIF": "123"}),
        cached_at=cached_at or datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# Descubrimiento de ayuda
# ---------------------------------------------------------------------------


class TestCacheHelp:
    def test_root_help_lists_cache(self) -> None:
        result = CliRunner().invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "cache" in result.stdout

    def test_cache_help_lists_subcommands(self) -> None:
        result = CliRunner().invoke(main, ["cache", "--help"])
        assert result.exit_code == 0
        assert "stats" in result.stdout
        assert "clear" in result.stdout


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------


class TestCacheStats:
    def test_stats_empty(self, cache_setup: tuple[Path, SqliteDocumentCache]) -> None:
        yaml_path, _ = cache_setup
        result = CliRunner().invoke(main, ["cache", "stats", "-c", str(yaml_path)])
        assert result.exit_code == 0
        assert "rows : 0" in result.stdout

    def test_stats_json(self, cache_setup: tuple[Path, SqliteDocumentCache]) -> None:
        yaml_path, cache = cache_setup
        cache.put(_entry("T1"))
        cache.put(_entry("T2"))
        result = CliRunner().invoke(
            main, ["cache", "stats", "-c", str(yaml_path), "--format", "json"]
        )
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["total_rows"] == 2
        assert payload["oldest_cached_at"] is not None


# ---------------------------------------------------------------------------
# clear
# ---------------------------------------------------------------------------


class TestCacheClear:
    def test_clear_txn(self, cache_setup: tuple[Path, SqliteDocumentCache]) -> None:
        yaml_path, cache = cache_setup
        cache.put(_entry("T1"))
        cache.put(_entry("T2"))
        result = CliRunner().invoke(main, ["cache", "clear", "-c", str(yaml_path), "--txn", "T1"])
        assert result.exit_code == 0
        assert "deleted 1 row" in result.stdout
        assert cache.stats().total_rows == 1

    def test_clear_all(self, cache_setup: tuple[Path, SqliteDocumentCache]) -> None:
        yaml_path, cache = cache_setup
        cache.put(_entry("T1"))
        cache.put(_entry("T2"))
        cache.put(_entry("T3"))
        result = CliRunner().invoke(main, ["cache", "clear", "-c", str(yaml_path), "--all"])
        assert result.exit_code == 0
        assert "truncated 3 row" in result.stdout
        assert cache.stats().total_rows == 0

    def test_clear_older_than(self, cache_setup: tuple[Path, SqliteDocumentCache]) -> None:
        yaml_path, cache = cache_setup
        cache.put(_entry("old", cached_at=datetime.now(UTC) - timedelta(minutes=120)))
        cache.put(_entry("fresh"))
        result = CliRunner().invoke(
            main,
            ["cache", "clear", "-c", str(yaml_path), "--older-than", "60"],
        )
        assert result.exit_code == 0
        assert "older than 60" in result.stdout
        assert cache.stats().total_rows == 1

    def test_clear_requires_exactly_one_mode(
        self, cache_setup: tuple[Path, SqliteDocumentCache]
    ) -> None:
        yaml_path, _ = cache_setup
        result = CliRunner().invoke(main, ["cache", "clear", "-c", str(yaml_path)])
        assert result.exit_code == 2
        assert "exactly one" in result.stderr

    def test_clear_rejects_two_modes(self, cache_setup: tuple[Path, SqliteDocumentCache]) -> None:
        yaml_path, _ = cache_setup
        result = CliRunner().invoke(
            main,
            ["cache", "clear", "-c", str(yaml_path), "--all", "--txn", "T1"],
        )
        assert result.exit_code == 2
