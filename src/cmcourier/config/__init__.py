"""Configuration layer - Pydantic schema + YAML loader + env-var secrets.

Sole reader of process environment variables: ``AS400_USERNAME``,
``AS400_PASSWORD``, ``CMIS_USERNAME``, ``CMIS_PASSWORD``.
Constitution Principle V.
"""

from __future__ import annotations

from cmcourier.config.loader import Secrets, load_config, load_secrets
from cmcourier.config.schema import PipelineConfig
from cmcourier.config.wiring import build_pipeline

__all__ = [
    "PipelineConfig",
    "Secrets",
    "build_pipeline",
    "load_config",
    "load_secrets",
]
