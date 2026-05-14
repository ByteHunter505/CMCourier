"""Integration tests for ``cmcourier sync`` subcommands (034 phase 4).

The CLI is wired against fake AS400 (pyodbc cursor at the driver
boundary) + a real SQLite store. Test focus: argument parsing +
exit codes + the resolver's effect on SQLite.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from textwrap import dedent
from typing import Any

import pytest
from click.testing import CliRunner

from cmcourier.adapters.tracking import as400_niarvilog as niarvilog_module
from cmcourier.cli.app import main

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Reuse the pyodbc fake from test_as400_niarvilog.py
# ---------------------------------------------------------------------------


class _FakeCursor:
    def __init__(self) -> None:
        self.executions: list[tuple[str, list[Any]]] = []
        self.fetch_queue: list[tuple[list[tuple[Any, ...]], tuple[str, ...]]] = []
        self.rowcount_queue: list[int] = []
        self._current_rows: list[list[Any]] = []
        self._current_columns: list[str] = []
        self.rowcount = -1

    @property
    def description(self) -> list[tuple[str, ...]]:
        return [(c,) for c in self._current_columns]

    def execute(self, sql: str, params: list[Any] | None = None) -> _FakeCursor:
        self.executions.append((sql, list(params or [])))
        if self.fetch_queue:
            rows, columns = self.fetch_queue.pop(0)
            self._current_rows = [list(r) for r in rows]
            self._current_columns = list(columns)
        else:
            self._current_rows = []
            self._current_columns = []
        self.rowcount = self.rowcount_queue.pop(0) if self.rowcount_queue else -1
        return self

    def fetchall(self) -> list[list[Any]]:
        out = self._current_rows
        self._current_rows = []
        return out

    def fetchone(self) -> list[Any] | None:
        return self._current_rows.pop(0) if self._current_rows else None

    def close(self) -> None:
        pass


class _FakeConn:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self) -> _FakeCursor:
        return self._cursor

    def commit(self) -> None:
        pass

    def close(self) -> None:
        pass


class _FakePyodbcModule:
    class Error(Exception):
        pass

    class IntegrityError(Error):
        pass

    def __init__(self, conn: _FakeConn) -> None:
        self._conn = conn

    def connect(self, cs: str) -> _FakeConn:  # noqa: ARG002
        return self._conn


def _patch_pyodbc(monkeypatch: pytest.MonkeyPatch, cursor: _FakeCursor) -> _FakeConn:
    conn = _FakeConn(cursor)
    monkeypatch.setattr(niarvilog_module, "pyodbc", _FakePyodbcModule(conn))
    return conn


_COLUMNS = (
    "SISCOD",
    "TRNNUM",
    "DOCFRM",
    "IMGARC",
    "IMGTIP",
    "CTECIF",
    "CTENUM",
    "STSCOD",
    "IDNBAC",
    "TIPIDN",
    "OBJIDN",
    "NUMREI",
    "PMRREI",
    "FINREI",
    "EERRMSG",
)


def _niarvilog_tuple(
    *,
    trnnum: str = "0000001",
    stscod: str = "O",
    objidn: str = "cmis-abc",
) -> tuple[Any, ...]:
    now = datetime(2025, 11, 17, 10, 0, 0)
    return (
        "1",  # SISCOD
        trnnum,
        "CC03",
        "DAAAH9X4.001",
        "B",
        "TESTCLIENT01",
        123456,
        stscod,
        "CN01",
        "MyType",
        objidn,
        0,
        now,
        now,
        "",
    )


# ---------------------------------------------------------------------------
# YAML helper (minimal, AS400 sync enabled)
# ---------------------------------------------------------------------------


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
              as400_sync:
                enabled: true
                connection:
                  host: 10.0.0.1
                library: RVILIB
                table: NIARVILOG
                stale_in_progress_minutes: 30
                retry_attempts: 3
                retry_base_delay_s: 0.001
            """
        )
    )
    return yaml_path


def _set_as400_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AS400_USERNAME", "tester")
    monkeypatch.setenv("AS400_PASSWORD", "secret-not-real")
    monkeypatch.setenv("CMIS_USERNAME", "tester")
    monkeypatch.setenv("CMIS_PASSWORD", "secret-not-real")


# ---------------------------------------------------------------------------
# Help discovery
# ---------------------------------------------------------------------------


class TestSyncHelp:
    def test_root_help_lists_sync(self) -> None:
        result = CliRunner().invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "sync" in result.stdout

    def test_sync_help_lists_subcommands(self) -> None:
        result = CliRunner().invoke(main, ["sync", "--help"])
        assert result.exit_code == 0
        assert "resolve" in result.stdout
        assert "status" in result.stdout


# ---------------------------------------------------------------------------
# sync status
# ---------------------------------------------------------------------------


class TestSyncStatus:
    def test_reports_no_conflicts(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _set_as400_env(monkeypatch)
        cur = _FakeCursor()
        # cleanup_stale returns 0 rows
        cur.rowcount_queue = [0]
        _patch_pyodbc(monkeypatch, cur)
        yaml_path = _write_yaml(tmp_path)

        result = CliRunner().invoke(main, ["sync", "status", "--config", str(yaml_path)])
        assert result.exit_code == 0, result.stderr
        assert "stale_cleaned=0" in result.stdout


# ---------------------------------------------------------------------------
# sync resolve --prefer-as400
# ---------------------------------------------------------------------------


class TestSyncResolvePreferAs400:
    def test_pulls_as400_state_into_sqlite(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _set_as400_env(monkeypatch)
        cur = _FakeCursor()
        # First call: read_state_by_txn returns a 'O' row.
        cur.fetch_queue = [
            ([_niarvilog_tuple(stscod="O", objidn="cmis-abc")], _COLUMNS),
        ]
        _patch_pyodbc(monkeypatch, cur)
        yaml_path = _write_yaml(tmp_path)

        result = CliRunner().invoke(
            main,
            [
                "sync",
                "resolve",
                "0000001",
                "--prefer-as400",
                "--config",
                str(yaml_path),
            ],
        )
        assert result.exit_code == 0, result.stderr
        assert "0000001" in result.stdout
        assert "resolved" in result.stdout.lower() or "imported" in result.stdout.lower()

    def test_errors_when_txn_not_in_as400(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _set_as400_env(monkeypatch)
        cur = _FakeCursor()
        cur.fetch_queue = [([], _COLUMNS)]  # row absent
        _patch_pyodbc(monkeypatch, cur)
        yaml_path = _write_yaml(tmp_path)

        result = CliRunner().invoke(
            main,
            [
                "sync",
                "resolve",
                "0000001",
                "--prefer-as400",
                "--config",
                str(yaml_path),
            ],
        )
        # Exit 1 — operator asked to import but there's nothing to import.
        assert result.exit_code == 1
        assert "not found in AS400" in result.stderr or "not found" in result.stdout


# ---------------------------------------------------------------------------
# sync resolve --prefer-local
# ---------------------------------------------------------------------------


class TestSyncResolvePreferLocal:
    def test_pushes_supplied_objidn_to_as400(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _set_as400_env(monkeypatch)
        cur = _FakeCursor()
        # First exec (read_state_by_txn → SELECT) returns the existing row;
        # second exec (mark_uploaded_by_txn → UPDATE) returns rowcount=1.
        cur.fetch_queue = [
            ([_niarvilog_tuple(stscod="N", objidn="")], _COLUMNS),
        ]
        cur.rowcount_queue = [0, 1]  # SELECT no rowcount, UPDATE=1
        _patch_pyodbc(monkeypatch, cur)
        yaml_path = _write_yaml(tmp_path)

        result = CliRunner().invoke(
            main,
            [
                "sync",
                "resolve",
                "0000001",
                "--prefer-local",
                "--cm-object-id",
                "cmis-local-id",
                "--config",
                str(yaml_path),
            ],
        )
        assert result.exit_code == 0, result.stderr
        # The UPDATE was executed with the supplied cm_object_id.
        update_call = next((e for e in cur.executions if "UPDATE" in e[0].upper()), None)
        assert update_call is not None
        assert "cmis-local-id" in update_call[1]

    def test_prefer_local_without_cm_object_id_exits_2(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _set_as400_env(monkeypatch)
        _patch_pyodbc(monkeypatch, _FakeCursor())
        yaml_path = _write_yaml(tmp_path)
        result = CliRunner().invoke(
            main,
            [
                "sync",
                "resolve",
                "0000001",
                "--prefer-local",
                "--config",
                str(yaml_path),
            ],
        )
        assert result.exit_code == 2
        assert "--cm-object-id" in result.stderr
