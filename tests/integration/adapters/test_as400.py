"""Integration tests for :class:`As400DataSource`.

pyodbc is mocked at the module-attribute boundary
(``cmcourier.adapters.sources.as400.pyodbc.connect``) so the real
unixODBC driver is not required to run these tests.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest

from cmcourier.adapters.sources.as400 import As400DataSource
from cmcourier.domain.exceptions import IndexingError

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Fakes for the pyodbc cursor / connection protocol
# ---------------------------------------------------------------------------


class _FakeAs400Cursor:
    """Scriptable pyodbc-style cursor for tests."""

    def __init__(
        self,
        *,
        rows: Sequence[Sequence[Any]] = (),
        columns: Sequence[str] = (),
        raise_on_execute: BaseException | None = None,
    ) -> None:
        self._rows: list[list[Any]] = [list(r) for r in rows]
        self._columns = list(columns)
        self._raise_on_execute = raise_on_execute
        self.executions: list[tuple[str, list[Any]]] = []
        self.fetchmany_calls = 0
        self.closed = False

    @property
    def description(self) -> list[tuple[str, ...]] | None:
        return [(c,) for c in self._columns] if self._columns else None

    def execute(self, sql: str, params: list[Any] | None = None) -> _FakeAs400Cursor:
        self.executions.append((sql, list(params or [])))
        if self._raise_on_execute is not None:
            raise self._raise_on_execute
        return self

    def fetchall(self) -> list[list[Any]]:
        out = self._rows
        self._rows = []
        return out

    def fetchmany(self, size: int) -> list[list[Any]]:
        self.fetchmany_calls += 1
        chunk = self._rows[:size]
        self._rows = self._rows[size:]
        return chunk

    def fetchone(self) -> list[Any] | None:
        if not self._rows:
            return None
        return self._rows.pop(0)

    def close(self) -> None:
        self.closed = True


class _FakeAs400Connection:
    """Scriptable pyodbc-style connection for tests."""

    def __init__(self, cursor: _FakeAs400Cursor) -> None:
        self._cursor = cursor
        self.closed = False

    def cursor(self) -> _FakeAs400Cursor:
        return self._cursor

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def fake_cursor() -> _FakeAs400Cursor:
    return _FakeAs400Cursor()


@pytest.fixture
def fake_connection(fake_cursor: _FakeAs400Cursor) -> _FakeAs400Connection:
    return _FakeAs400Connection(fake_cursor)


def _patch_pyodbc_connect(
    monkeypatch: pytest.MonkeyPatch,
    connection: _FakeAs400Connection,
) -> list[str]:
    captured: list[str] = []

    def _fake_connect(connection_string: str) -> _FakeAs400Connection:
        captured.append(connection_string)
        return connection

    # Lazy import path: pyodbc is imported inside _connect(). We patch the
    # module's pyodbc attribute after import.
    import cmcourier.adapters.sources.as400 as as400_module

    monkeypatch.setattr(as400_module, "pyodbc", _FakePyodbcModule(_fake_connect))
    return captured


class _FakePyodbcModule:
    """Minimal stand-in for the pyodbc module."""

    class Error(Exception):
        """Mirrors pyodbc.Error for isinstance checks."""

    def __init__(self, connect_fn: Any) -> None:
        self._connect_fn = connect_fn

    def connect(self, connection_string: str) -> Any:
        return self._connect_fn(connection_string)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_source(table: str = "TRIGGERS") -> As400DataSource:
    return As400DataSource(
        host="10.0.0.1",
        port=446,
        database="RVILIB",
        driver="iSeries Access ODBC Driver",
        username="tester",
        password="secret-not-real",
        table=table,
    )


# ---------------------------------------------------------------------------
# Construction + connection
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_construction_does_not_connect(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured = _patch_pyodbc_connect(monkeypatch, _FakeAs400Connection(_FakeAs400Cursor()))
        _make_source()
        assert captured == []  # no connect() call yet

    def test_first_method_call_connects(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_connection: _FakeAs400Connection,
    ) -> None:
        captured = _patch_pyodbc_connect(monkeypatch, fake_connection)
        src = _make_source()
        src.count()  # any method triggers the connect
        assert len(captured) == 1
        # Connection string format matches REQ-002.
        cs = captured[0]
        assert "DRIVER={iSeries Access ODBC Driver}" in cs
        assert "SYSTEM=10.0.0.1" in cs
        assert "PORT=446" in cs
        assert "DATABASE=RVILIB" in cs
        assert "UID=tester" in cs
        assert "PWD=secret-not-real" in cs

    def test_subsequent_calls_reuse_connection(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_connection: _FakeAs400Connection,
    ) -> None:
        captured = _patch_pyodbc_connect(monkeypatch, fake_connection)
        src = _make_source()
        src.count()
        src.count()
        assert len(captured) == 1  # connected only once


# ---------------------------------------------------------------------------
# query / query_stream
# ---------------------------------------------------------------------------


class TestQuery:
    def test_query_materializes_rows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        cursor = _FakeAs400Cursor(
            rows=[("JUANPEREZ01", "123456"), ("MARIAGOMEZ02", "234567")],
            columns=("SHORTNAME", "CIF"),
        )
        conn = _FakeAs400Connection(cursor)
        _patch_pyodbc_connect(monkeypatch, conn)
        src = _make_source()
        result = src.query("SELECT SHORTNAME, CIF FROM T", [])
        assert result == [
            {"SHORTNAME": "JUANPEREZ01", "CIF": "123456"},
            {"SHORTNAME": "MARIAGOMEZ02", "CIF": "234567"},
        ]
        assert cursor.executions == [("SELECT SHORTNAME, CIF FROM T", [])]

    def test_query_with_params(self, monkeypatch: pytest.MonkeyPatch) -> None:
        cursor = _FakeAs400Cursor(rows=[("X",)], columns=("V",))
        _patch_pyodbc_connect(monkeypatch, _FakeAs400Connection(cursor))
        src = _make_source()
        src.query("SELECT V FROM T WHERE CIF = ?", ["123456"])
        assert cursor.executions[0][1] == ["123456"]

    def test_query_stream_uses_fetchmany(self, monkeypatch: pytest.MonkeyPatch) -> None:
        rows = [(str(i),) for i in range(750)]
        cursor = _FakeAs400Cursor(rows=rows, columns=("V",))
        _patch_pyodbc_connect(monkeypatch, _FakeAs400Connection(cursor))
        src = _make_source()
        materialized = list(src.query_stream("SELECT V FROM T", []))
        assert len(materialized) == 750
        # 750 rows / 500-batch = 2 full batches; the stream loop calls
        # fetchmany until it returns < batch_size.
        assert cursor.fetchmany_calls >= 2


# ---------------------------------------------------------------------------
# get_by_fields and get_by_fields_in
# ---------------------------------------------------------------------------


class TestGetByFields:
    def test_get_by_fields_builds_where(self, monkeypatch: pytest.MonkeyPatch) -> None:
        cursor = _FakeAs400Cursor(rows=[("X", "1")], columns=("SHORTNAME", "SYS"))
        _patch_pyodbc_connect(monkeypatch, _FakeAs400Connection(cursor))
        src = _make_source(table="RVABREP")
        src.get_by_fields({"SHORTNAME": "JUANPEREZ01", "SYS": "1"})
        sql, params = cursor.executions[0]
        assert "FROM RVABREP" in sql
        assert "SHORTNAME = ?" in sql
        assert "SYS = ?" in sql
        assert params == ["JUANPEREZ01", "1"]

    def test_get_by_fields_in_empty_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        cursor = _FakeAs400Cursor()
        _patch_pyodbc_connect(monkeypatch, _FakeAs400Connection(cursor))
        src = _make_source()
        result = src.get_by_fields_in("CIF", values=[], fixed_filters={})
        assert result == []
        assert cursor.executions == []  # never executed

    def test_get_by_fields_in_chunks_at_1000(self, monkeypatch: pytest.MonkeyPatch) -> None:
        cursor = _FakeAs400Cursor(columns=("CIF",))
        _patch_pyodbc_connect(monkeypatch, _FakeAs400Connection(cursor))
        src = _make_source()
        values = [str(i) for i in range(1500)]
        src.get_by_fields_in("CIF", values, fixed_filters={"SYS": "1"})
        # Two chunks: 1000 + 500.
        assert len(cursor.executions) == 2
        first_sql, first_params = cursor.executions[0]
        second_sql, second_params = cursor.executions[1]
        # Each chunk has its IN-list params + the fixed filter value.
        assert len(first_params) == 1001
        assert first_params[-1] == "1"  # fixed filter
        assert len(second_params) == 501


# ---------------------------------------------------------------------------
# get_all + count
# ---------------------------------------------------------------------------


class TestGetAllCount:
    def test_get_all_yields_rows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        rows = [(str(i),) for i in range(3)]
        cursor = _FakeAs400Cursor(rows=rows, columns=("V",))
        _patch_pyodbc_connect(monkeypatch, _FakeAs400Connection(cursor))
        src = _make_source(table="RVABREP")
        result = list(src.get_all())
        assert len(result) == 3
        assert cursor.executions[0][0] == "SELECT * FROM RVABREP"

    def test_count(self, monkeypatch: pytest.MonkeyPatch) -> None:
        cursor = _FakeAs400Cursor(rows=[(42,)], columns=("CNT",))
        _patch_pyodbc_connect(monkeypatch, _FakeAs400Connection(cursor))
        src = _make_source(table="RVABREP")
        assert src.count() == 42
        executed_sql = cursor.executions[0][0]
        assert "SELECT COUNT(*)" in executed_sql
        assert "FROM RVABREP" in executed_sql


# ---------------------------------------------------------------------------
# Error wrapping
# ---------------------------------------------------------------------------


class TestErrorWrapping:
    def test_pyodbc_error_wrapped_in_indexing_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Build a fake pyodbc.Error that mimics the (sqlstate, message) shape.
        import cmcourier.adapters.sources.as400 as as400_module

        captured: list[str] = []

        def _fake_connect(cs: str) -> _FakeAs400Connection:
            captured.append(cs)
            cursor = _FakeAs400Cursor(
                raise_on_execute=as400_module.pyodbc.Error("42S02", "Table not found"),
            )
            return _FakeAs400Connection(cursor)

        monkeypatch.setattr(
            as400_module,
            "pyodbc",
            _FakePyodbcModule(_fake_connect),
        )
        src = _make_source()
        with pytest.raises(IndexingError) as ei:
            src.query("SELECT * FROM NOPE", [])
        assert isinstance(ei.value.__cause__, as400_module.pyodbc.Error)

    def test_pyodbc_connect_error_wrapped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import cmcourier.adapters.sources.as400 as as400_module

        def _raise(cs: str) -> _FakeAs400Connection:
            raise as400_module.pyodbc.Error("08001", "Connection refused")

        monkeypatch.setattr(as400_module, "pyodbc", _FakePyodbcModule(_raise))
        src = _make_source()
        with pytest.raises(IndexingError):
            src.count()


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


class TestLifecycle:
    def test_close_idempotent(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_connection: _FakeAs400Connection,
    ) -> None:
        _patch_pyodbc_connect(monkeypatch, fake_connection)
        src = _make_source()
        src.count()
        src.close()
        src.close()  # no-op
        assert fake_connection.closed
