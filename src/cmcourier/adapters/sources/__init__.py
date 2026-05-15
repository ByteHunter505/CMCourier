"""Adaptadores de fuentes de datos: CSV/XLSX (pandas) y AS400 (pyodbc).

Implementaciones concretas de :class:`cmcourier.domain.ports.IDataSource`.
El adaptador tabular (CSV/XLSX) es el sustituto canónico de AS400 para dev/test
según el Principio VI de la Constitución. El adaptador AS400 mantiene UNA sola
conexión pyodbc — las conexiones thread-local llegarán en un cambio futuro,
cuando se libere el `worker pool` del orquestador.
"""

from __future__ import annotations

__all__ = ["As400DataSource", "TabularDataSource"]

from cmcourier.adapters.sources.as400 import As400DataSource
from cmcourier.adapters.sources.tabular import TabularDataSource
