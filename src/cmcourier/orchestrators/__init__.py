"""Capa de orchestrators — coordinadores delgados para la composición del `pipeline`.

Cada orchestrator conecta una secuencia de `stage`s (``S0`` ... ``S7``) en un
`pipeline` ejecutable. Sin lógica de negocio, sin I/O directo. Principio I de
la Constitución.
"""

from __future__ import annotations

from cmcourier.orchestrators.multi_batch import MultiBatchOrchestrator, MultiBatchRunReport
from cmcourier.orchestrators.staged import RunReport, StagedPipeline
from cmcourier.orchestrators.streaming import StreamingOrchestrator, StreamingSnapshot

__all__ = [
    "MultiBatchOrchestrator",
    "MultiBatchRunReport",
    "RunReport",
    "StagedPipeline",
    "StreamingOrchestrator",
    "StreamingSnapshot",
]
