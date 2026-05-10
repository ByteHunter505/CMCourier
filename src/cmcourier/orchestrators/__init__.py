"""Orchestrators layer - thin coordinators for pipeline composition.

Each orchestrator wires a sequence of stages (``S0`` ... ``S7``) into a runnable
pipeline. No business logic, no direct I/O. Constitution Principle I.
"""

from __future__ import annotations

from cmcourier.orchestrators.csv_trigger import CsvTriggerPipeline, RunReport

__all__ = ["CsvTriggerPipeline", "RunReport"]
