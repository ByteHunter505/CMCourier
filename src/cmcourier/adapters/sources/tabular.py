"""TabularDataSource - concrete IDataSource over CSV and XLSX files.

First adapter implementation in CMCourier. Reads the entire file eagerly via
pandas, stores it as a private DataFrame, and exposes the IDataSource
contract. ``query()`` and ``query_stream()`` raise ``NotImplementedError``
because tabular sources have no SQL surface; callers use ``get_by_fields``,
``get_by_fields_in``, or ``get_all`` instead.

The adapter normalizes ``NaN`` (pandas missing-value sentinel) to ``None``
before yielding any row dict, so callers never see pandas-specific
internals through the port boundary.

See ``specs/003-tabular-data-source-adapter/{spec,plan}.md`` for full
context and rationale.
"""

from __future__ import annotations

__all__ = ["TabularDataSource"]

from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import pandas as pd

from cmcourier.domain.exceptions import ConfigurationError
from cmcourier.domain.ports import IDataSource

_SUPPORTED_CSV: tuple[str, ...] = (".csv",)
_SUPPORTED_XLSX: tuple[str, ...] = (".xlsx", ".xls")


def _normalize_row(row: dict[Any, Any]) -> dict[str, Any]:
    """Replace pandas ``NaN`` sentinels with ``None`` and stringify keys.

    pandas's ``DataFrame.to_dict(orient="records")`` returns
    ``dict[Hashable, Any]`` because column labels can be anything hashable.
    At runtime our DataFrames always have string headers (CSV / XLSX), but
    we coerce ``str(k)`` defensively to keep the contract clean.
    """
    return {str(k): (None if pd.isna(v) else v) for k, v in row.items()}


class TabularDataSource(IDataSource):
    """In-memory IDataSource backed by a single CSV or XLSX file.

    Construction reads the file once into a pandas DataFrame and stores it
    for the lifetime of the instance. Callers must ``close()`` the source
    when done; subsequent operations on a closed instance raise
    ``RuntimeError``.
    """

    def __init__(
        self,
        path: Path,
        encoding: str = "utf-8",
        sheet_name: str | int = 0,
    ) -> None:
        if not path.exists():
            raise FileNotFoundError(path)
        suffix = path.suffix.lower()
        if suffix in _SUPPORTED_CSV:
            self._df = self._load_csv(path, encoding)
        elif suffix in _SUPPORTED_XLSX:
            self._df = self._load_xlsx(path, sheet_name)
        else:
            raise ConfigurationError(
                f"Unsupported file extension {suffix!r}; expected one of "
                f"{_SUPPORTED_CSV + _SUPPORTED_XLSX}"
            )
        self._closed = False
        self._path = path

    @staticmethod
    def _load_csv(path: Path, encoding: str) -> pd.DataFrame:
        try:
            return pd.read_csv(path, encoding=encoding, dtype=str, keep_default_na=True)
        except (UnicodeDecodeError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
            raise ConfigurationError(f"Failed to load CSV {path}: {exc}") from exc

    @staticmethod
    def _load_xlsx(path: Path, sheet_name: str | int) -> pd.DataFrame:
        try:
            return pd.read_excel(
                path,
                sheet_name=sheet_name,
                dtype=str,
                engine="openpyxl",
            )
        except Exception as exc:  # pandas / openpyxl raise heterogeneous types
            raise ConfigurationError(f"Failed to load XLSX {path}: {exc}") from exc

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("operation on closed TabularDataSource")

    def query(self, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
        raise NotImplementedError(
            "TabularDataSource does not support raw SQL. "
            "Use get_by_fields(filters), get_by_fields_in(...), or get_all()."
        )

    def query_stream(self, sql: str, params: list[Any] | None = None) -> Iterator[dict[str, Any]]:
        raise NotImplementedError(
            "TabularDataSource does not support raw SQL. "
            "Use get_by_fields(filters), get_by_fields_in(...), or get_all()."
        )
        yield  # pragma: no cover - unreachable, keeps the function a generator

    def get_by_fields(self, filters: Mapping[str, Any]) -> list[dict[str, Any]]:
        self._ensure_open()
        df = self._df
        for key, value in filters.items():
            if key not in df.columns:
                raise KeyError(key)
            df = df[df[key] == value]
        return [_normalize_row(row) for row in df.to_dict(orient="records")]

    def get_by_fields_in(
        self,
        field: str,
        values: list[Any],
        fixed_filters: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        self._ensure_open()
        if field not in self._df.columns:
            raise KeyError(field)
        df = self._df[self._df[field].isin(values)]
        for key, value in fixed_filters.items():
            if key not in df.columns:
                raise KeyError(key)
            df = df[df[key] == value]
        return [_normalize_row(row) for row in df.to_dict(orient="records")]

    def get_all(self) -> Iterator[dict[str, Any]]:
        self._ensure_open()
        # 050: iterate row by row via ``itertuples`` (lazy) instead of
        # ``to_dict(orient="records")`` which builds the full list of
        # every row's dict before the generator yields anything.
        columns = list(self._df.columns)
        for values in self._df.itertuples(index=False, name=None):
            yield _normalize_row(dict(zip(columns, values, strict=True)))

    def count(self) -> int:
        self._ensure_open()
        return len(self._df)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        del self._df
