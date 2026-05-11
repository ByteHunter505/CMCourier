"""Integration tests for ``cmcourier as400-query "<SQL>"`` (021)."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from textwrap import dedent
from typing import Any

import pytest
from click.testing import CliRunner

import cmcourier.adapters.sources.as400 as as400_module
from cmcourier.cli.app import main

pytestmark = [pytest.mark.integration, pytest.mark.slow]


# ---------------------------------------------------------------------------
# pyodbc fakes (mirrored from test_pipeline_kinds.py)
# ---------------------------------------------------------------------------


class _FakeCursor:
    def __init__(
        self,
        rows: Sequence[Sequence[Any]],
        columns: Sequence[str],
        *,
        raise_on_execute: BaseException | None = None,
    ) -> None:
        self._rows = [list(r) for r in rows]
        self._columns = list(columns)
        self._raise = raise_on_execute
        self.executions: list[tuple[str, list[Any]]] = []

    @property
    def description(self) -> list[tuple[str, ...]]:
        return [(c,) for c in self._columns]

    def execute(self, sql: str, params: list[Any] | None = None) -> _FakeCursor:
        self.executions.append((sql, list(params or [])))
        if self._raise is not None:
            raise self._raise
        return self

    def fetchall(self) -> list[list[Any]]:
        out = self._rows
        self._rows = []
        return out

    def fetchmany(self, size: int) -> list[list[Any]]:
        chunk, self._rows = self._rows[:size], self._rows[size:]
        return chunk

    def fetchone(self) -> list[Any] | None:
        return self._rows.pop(0) if self._rows else None

    def close(self) -> None:
        pass


class _FakeConn:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self) -> _FakeCursor:
        return self._cursor

    def close(self) -> None:
        pass


class _FakePyodbcModule:
    class Error(Exception):
        pass

    def __init__(self, connect_fn: Any) -> None:
        self._connect_fn = connect_fn

    def connect(self, cs: str) -> Any:
        return self._connect_fn(cs)


def _patch_pyodbc(monkeypatch: pytest.MonkeyPatch, cursor: _FakeCursor) -> None:
    def _connect(_cs: str) -> _FakeConn:
        return _FakeConn(cursor)

    monkeypatch.setattr(as400_module, "pyodbc", _FakePyodbcModule(_connect))


# ---------------------------------------------------------------------------
# YAML builder — uses kind=as400 trigger so trigger.as400_connection exists
# ---------------------------------------------------------------------------


_TESTS_ROOT = Path(__file__).parent.parent.parent
_PIPELINE_FIXTURES = _TESTS_ROOT / "fixtures" / "pipeline"
_SERVICES_FIXTURES = _TESTS_ROOT / "fixtures" / "services"
_ASSEMBLY_FIXTURES = _TESTS_ROOT / "fixtures" / "assembly"


def _write_yaml(tmp_path: Path) -> Path:
    yaml_path = tmp_path / "config.yaml"
    yaml_path.write_text(
        dedent(
            f"""\
            trigger:
              kind: "as400"
              query: "SELECT SHORTNAME, CIF, SYSTEMID FROM RVILIB.TRIGGERS"
              as400_connection:
                host: "10.0.0.1"
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
              field_sources:
                BAC_CIF:
                  sources:
                    - source_type: trigger
                      lookup_value_column: cif
            assembly:
              source_root: {_ASSEMBLY_FIXTURES}
              temp_dir: {tmp_path / "stg"}
            cmis:
              base_url: http://cmis.test:9080/cmis
              repo_id: "$x!t"
            tracking:
              db_path: {tmp_path / "tracking.db"}
            observability:
              log_dir: {tmp_path / "logs"}
            """
        )
    )
    return yaml_path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAs400Query:
    def test_help(self) -> None:
        result = CliRunner().invoke(main, ["as400-query", "--help"])
        assert result.exit_code == 0
        assert "SQL" in result.stdout

    def test_missing_credentials_exit_2(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CMIS_USERNAME", "u")
        monkeypatch.setenv("CMIS_PASSWORD", "p")
        monkeypatch.delenv("AS400_USERNAME", raising=False)
        monkeypatch.delenv("AS400_PASSWORD", raising=False)
        yaml_path = _write_yaml(tmp_path)
        result = CliRunner().invoke(main, ["as400-query", "-c", str(yaml_path), "SELECT 1"])
        assert result.exit_code == 2
        assert "AS400_USERNAME" in result.stderr

    def test_happy_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CMIS_USERNAME", "u")
        monkeypatch.setenv("CMIS_PASSWORD", "p")
        monkeypatch.setenv("AS400_USERNAME", "as400user")
        monkeypatch.setenv("AS400_PASSWORD", "as400pass")
        cursor = _FakeCursor(
            rows=[("TXN1", "CC03"), ("TXN2", "FF17")],
            columns=("TXN", "ID_RVI"),
        )
        _patch_pyodbc(monkeypatch, cursor)
        yaml_path = _write_yaml(tmp_path)
        result = CliRunner().invoke(
            main,
            [
                "as400-query",
                "-c",
                str(yaml_path),
                "SELECT TXN, ID_RVI FROM RVILIB.RVABREP",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "TXN" in result.stdout
        assert "ID_RVI" in result.stdout
        assert "TXN1" in result.stdout
        assert "CC03" in result.stdout
        assert "(2 rows)" in result.stdout

    def test_no_as400_connection_in_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # csv-trigger config has no as400 anywhere.
        from textwrap import dedent as _d

        monkeypatch.setenv("CMIS_USERNAME", "u")
        monkeypatch.setenv("CMIS_PASSWORD", "p")
        monkeypatch.setenv("AS400_USERNAME", "u")
        monkeypatch.setenv("AS400_PASSWORD", "p")
        triggers = tmp_path / "t.csv"
        triggers.write_text("ShortName,CIF,SystemID\n")
        yaml_path = tmp_path / "config.yaml"
        yaml_path.write_text(
            _d(
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
        )
        result = CliRunner().invoke(main, ["as400-query", "-c", str(yaml_path), "SELECT 1"])
        assert result.exit_code == 2
        assert "no AS400 connection" in result.stderr
