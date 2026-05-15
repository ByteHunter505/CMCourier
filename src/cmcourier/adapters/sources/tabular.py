"""TabularDataSource — IDataSource concreto sobre archivos CSV y XLSX.

Primera implementación de adaptador en CMCourier. Lee el archivo completo de
forma eager con pandas, lo guarda como un DataFrame privado, y expone el
contrato IDataSource. ``query()`` y ``query_stream()`` levantan
``NotImplementedError`` porque las fuentes tabulares no tienen superficie SQL;
los callers usan ``get_by_fields``, ``get_by_fields_in`` o ``get_all`` en su
lugar.

El adaptador normaliza el centinela ``NaN`` de pandas a ``None`` antes de
emitir cualquier dict de fila, de modo que los callers nunca ven internals
específicos de pandas a través del borde del puerto.

Ver ``specs/003-tabular-data-source-adapter/{spec,plan}.md`` para el contexto
y la justificación completa.
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
    """Reemplaza los centinelas ``NaN`` de pandas por ``None`` y convierte las claves a string.

    ``DataFrame.to_dict(orient="records")`` de pandas devuelve
    ``dict[Hashable, Any]`` porque las etiquetas de columna pueden ser cualquier
    hashable. En runtime nuestros DataFrames siempre tienen headers de tipo
    string (CSV / XLSX), pero forzamos ``str(k)`` de manera defensiva para
    mantener el contrato limpio.
    """
    return {str(k): (None if pd.isna(v) else v) for k, v in row.items()}


class TabularDataSource(IDataSource):
    """IDataSource en memoria respaldado por un único archivo CSV o XLSX.

    La construcción lee el archivo una vez en un DataFrame de pandas y lo
    guarda por el resto del ciclo de vida de la instancia. Los callers deben
    invocar ``close()`` cuando terminen; operaciones posteriores sobre una
    instancia cerrada levantan ``RuntimeError``.
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
        except Exception as exc:  # pandas / openpyxl levantan tipos heterogéneos
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
        yield  # pragma: no cover - inalcanzable; mantiene la función como generator

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
        # 050: iteramos fila por fila vía ``itertuples`` (lazy) en lugar de
        # ``to_dict(orient="records")``, que construye la lista completa de
        # dicts de todas las filas antes de que el generator emita nada.
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
