"""Configuration layer - Pydantic schema + YAML loader + env-var secrets.

Sole reader of process environment variables: ``AS400_USERNAME``,
``AS400_PASSWORD``, ``CMIS_USERNAME``, ``CMIS_PASSWORD``.
Constitution Principle V.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cmcourier.config.loader import Secrets, load_config, load_secrets
from cmcourier.config.schema import PipelineConfig

if TYPE_CHECKING:
    from cmcourier.config.wiring import build_pipeline


def __getattr__(name: str):  # type: ignore[no-untyped-def]
    """Lazy-import :func:`build_pipeline` to break a circular dependency.

    ``config.wiring`` pulls in ``orchestrators.staged`` which transitively
    imports ``observability.setup`` which imports ``config.schema``.
    Eager top-level import would cycle. Re-exporting via ``__getattr__``
    keeps the public API (``from cmcourier.config import build_pipeline``)
    working without the cycle.
    """
    if name == "build_pipeline":
        from cmcourier.config.wiring import build_pipeline as _bp  # noqa: PLC0415

        return _bp
    raise AttributeError(f"module 'cmcourier.config' has no attribute {name!r}")


__all__ = [
    "PipelineConfig",
    "Secrets",
    "build_pipeline",
    "load_config",
    "load_secrets",
]
