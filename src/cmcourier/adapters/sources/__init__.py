"""Data source adapters: CSV/XLSX (pandas) and AS400 (pyodbc, thread-local connections).

Concrete implementations of :class:`cmcourier.domain.ports.IDataSource`. The
tabular adapter (CSV/XLSX) is the canonical dev/test substitute for AS400 per
Constitution Principle VI; the AS400 adapter lands in a later change.
"""

from __future__ import annotations

__all__ = ["TabularDataSource"]

from cmcourier.adapters.sources.tabular import TabularDataSource
