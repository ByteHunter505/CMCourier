"""Data source adapters: CSV/XLSX (pandas) and AS400 (pyodbc).

Concrete implementations of :class:`cmcourier.domain.ports.IDataSource`.
The tabular adapter (CSV/XLSX) is the canonical dev/test substitute for
AS400 per Constitution Principle VI. The AS400 adapter holds ONE
pyodbc connection — thread-local connections land in a future change
when the orchestrator's worker pool ships.
"""

from __future__ import annotations

__all__ = ["As400DataSource", "TabularDataSource"]

from cmcourier.adapters.sources.as400 import As400DataSource
from cmcourier.adapters.sources.tabular import TabularDataSource
