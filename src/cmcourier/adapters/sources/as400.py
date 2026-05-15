"""AS400 ODBC data source — concrete :class:`IDataSource` via pyodbc.

Lazy ``pyodbc`` import inside :meth:`_connect` so importing this module
in environments without unixODBC headers does not crash (the failure
surfaces on first real call instead).

The AS400 ODBC driver is NOT thread-safe; a future change will add
``threading.local()`` connections when the orchestrator's worker pool
lands. 014 ships ONE connection per :class:`As400DataSource` instance.

All :class:`pyodbc.Error` exceptions are wrapped in
:class:`cmcourier.domain.exceptions.IndexingError`. SQLSTATE codes are
extracted from ``exc.args[0]`` when present.

Constitution Principle VIII: SQL queries and their parameters MAY
contain customer values (CIF, names). The adapter NEVER logs the SQL
body or parameters; callers are expected to handle their own audit.
"""

from __future__ import annotations

__all__ = ["As400DataSource"]

import logging
import re
import time
from collections.abc import Iterator, Mapping
from typing import Any

from cmcourier.domain.exceptions import ConfigurationError, IndexingError
from cmcourier.domain.ports import IDataSource

_network_log = logging.getLogger("cmcourier.metrics.network")

# Lazy import: the `pyodbc` name is resolved inside `_connect()` so test
# environments without unixODBC headers can `import` this module.
pyodbc: Any = None

_log = logging.getLogger(__name__)

_IN_CHUNK_SIZE = 1000
_STREAM_BATCH_SIZE = 500
_SQLSTATE_RE = re.compile(r"^[0-9A-Z]{5}$")


class As400DataSource(IDataSource):
    """Concrete IDataSource over an AS400 ODBC connection.

    Accepts either a ``table`` (bare identifier) or a custom prefetch
    ``query`` (a full ``SELECT ...`` statement), but never both. In
    query mode the SQL is wrapped in a derived-table alias
    (``(query) AS T``) so the full IDataSource contract (``get_all``,
    ``count``, ``get_by_fields*``) keeps working transparently. The
    "raw mode" (neither set) is valid for callers that only invoke
    :meth:`query` or :meth:`query_stream` directly (e.g. trigger
    strategies that own their own SQL).
    """

    def __init__(
        self,
        *,
        host: str,
        port: int,
        database: str,
        driver: str,
        username: str,
        password: str,
        table: str = "",
        query: str | None = None,
    ) -> None:
        if table and query:
            raise ConfigurationError(
                "As400DataSource: `table` and `query` are mutually exclusive",
            )
        self._host = host
        self._port = port
        self._database = database
        self._driver = driver
        self._username = username
        self._password = password
        self._source_expr = f"({query}) AS T" if query else table
        self._conn: Any = None
        self._closed = False

    # ------------------------------------------------------------------ ports

    def query(self, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
        cursor = self._connect().cursor()
        t0 = time.monotonic()
        try:
            cursor.execute(sql, params or [])
            columns = [col[0] for col in cursor.description or []]
            rows = [dict(zip(columns, row, strict=False)) for row in cursor.fetchall()]
            _network_log.info(
                "as400_query",
                extra={
                    "kind": "as400_query",
                    "duration_ms": round((time.monotonic() - t0) * 1000.0, 3),
                    "sql_prefix": sql[:80],
                    "row_count": len(rows),
                },
            )
            return rows
        except _pyodbc_error_type() as exc:
            raise IndexingError(
                "AS400 query failed",
                sql_prefix=sql[:80],
                sqlstate=_extract_sqlstate(exc),
            ) from exc
        finally:
            cursor.close()

    def query_stream(self, sql: str, params: list[Any] | None = None) -> Iterator[dict[str, Any]]:
        cursor = self._connect().cursor()
        t0 = time.monotonic()
        yielded = 0
        try:
            cursor.execute(sql, params or [])
            columns = [col[0] for col in cursor.description or []]
            while True:
                rows = cursor.fetchmany(_STREAM_BATCH_SIZE)
                if not rows:
                    _network_log.info(
                        "as400_query",
                        extra={
                            "kind": "as400_query",
                            "duration_ms": round((time.monotonic() - t0) * 1000.0, 3),
                            "sql_prefix": sql[:80],
                            "row_count": yielded,
                        },
                    )
                    return
                for row in rows:
                    yielded += 1
                    yield dict(zip(columns, row, strict=False))
        except _pyodbc_error_type() as exc:
            raise IndexingError(
                "AS400 query_stream failed",
                sql_prefix=sql[:80],
                sqlstate=_extract_sqlstate(exc),
            ) from exc
        finally:
            cursor.close()

    def get_by_fields(self, filters: Mapping[str, Any]) -> list[dict[str, Any]]:
        if not filters:
            return self.query(f"SELECT * FROM {self._source_expr}", [])
        cols = list(filters.keys())
        where = " AND ".join(f"{c} = ?" for c in cols)
        sql = f"SELECT * FROM {self._source_expr} WHERE {where}"
        return self.query(sql, [filters[c] for c in cols])

    def get_by_fields_in(
        self,
        field: str,
        values: list[Any],
        fixed_filters: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        if not values:
            return []
        fixed_cols = list(fixed_filters.keys())
        fixed_vals = [fixed_filters[c] for c in fixed_cols]
        fixed_clause = " AND " + " AND ".join(f"{c} = ?" for c in fixed_cols) if fixed_cols else ""
        results: list[dict[str, Any]] = []
        for start in range(0, len(values), _IN_CHUNK_SIZE):
            chunk = values[start : start + _IN_CHUNK_SIZE]
            placeholders = ", ".join("?" * len(chunk))
            sql = (
                f"SELECT * FROM {self._source_expr} WHERE {field} IN ({placeholders}){fixed_clause}"
            )
            results.extend(self.query(sql, list(chunk) + fixed_vals))
        return results

    def get_all(self) -> Iterator[dict[str, Any]]:
        return self.query_stream(f"SELECT * FROM {self._source_expr}", [])

    def count(self) -> int:
        rows = self.query(f"SELECT COUNT(*) AS CNT FROM {self._source_expr}", [])
        if not rows:
            return 0
        first = rows[0]
        for value in first.values():
            if isinstance(value, int):
                return value
        return 0

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._conn is not None:
            try:
                self._conn.close()
            except _pyodbc_error_type():
                _log.exception("AS400 close failed")
            self._conn = None

    # ------------------------------------------------------------------ internals

    def _connect(self) -> Any:
        if self._conn is not None:
            return self._conn
        _import_pyodbc()
        try:
            self._conn = pyodbc.connect(self._build_connection_string())
        except _pyodbc_error_type() as exc:
            raise IndexingError(
                "AS400 connection failed",
                host=self._host,
                sqlstate=_extract_sqlstate(exc),
            ) from exc
        return self._conn

    def _build_connection_string(self) -> str:
        return (
            f"DRIVER={{{self._driver}}};"
            f"SYSTEM={self._host};"
            f"PORT={self._port};"
            f"DATABASE={self._database};"
            f"UID={self._username};"
            f"PWD={self._password};"
        )


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _import_pyodbc() -> None:
    global pyodbc
    if pyodbc is not None:
        return
    import pyodbc as _pyodbc  # noqa: PLC0415 — intentional lazy import

    pyodbc = _pyodbc


def _pyodbc_error_type() -> type[BaseException]:
    if pyodbc is None:
        return RuntimeError
    return pyodbc.Error  # type: ignore[no-any-return]


def _extract_sqlstate(exc: BaseException) -> str:
    args = getattr(exc, "args", ())
    if args and isinstance(args[0], str) and _SQLSTATE_RE.match(args[0]):
        return args[0]
    return ""
