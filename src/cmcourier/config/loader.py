"""YAML config loader + env-var secrets reader.

Both functions raise :class:`ConfigurationError` (from
``cmcourier.domain.exceptions``) on failure with structured context so
the CLI can surface diagnostic detail to operators.

Constitution Principle V: configuration is the single source of truth.
Principle VIII: credentials live in environment variables, NEVER in
the YAML file.
"""

from __future__ import annotations

__all__ = ["Secrets", "load_config", "load_secrets"]

import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import ValidationError

from cmcourier.config.schema import PipelineConfig
from cmcourier.domain.exceptions import ConfigurationError


@dataclass(frozen=True, slots=True)
class Secrets:
    """Credentials read from environment variables at startup."""

    cmis_username: str
    cmis_password: str
    as400_username: str = ""
    as400_password: str = ""


def load_config(path: Path) -> PipelineConfig:
    """Read *path* as YAML and return a validated :class:`PipelineConfig`."""
    if not path.is_file():
        raise ConfigurationError("config file not found", config_path=str(path))
    try:
        text = path.read_text(encoding="utf-8")
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigurationError("invalid YAML", reason=str(exc)) from exc
    if not isinstance(data, dict):
        raise ConfigurationError(
            "config root must be a mapping",
            actual_type=type(data).__name__,
        )
    _inject_default_kinds(data)
    try:
        return PipelineConfig.model_validate(data)
    except ValidationError as exc:
        raise ConfigurationError(
            "config validation failed",
            errors=exc.errors(),
        ) from exc


def _inject_default_kinds(data: dict[str, object]) -> None:
    """Backwards-compat: discriminator ``kind`` defaults to ``"csv"``.

    Pydantic v2 discriminated unions require the discriminator field. Existing
    configs from change 012 omit ``kind`` entirely — the original schemas had
    single shapes (``TriggerCsvConfig``, ``MetadataSourceConfig`` as csv-only).
    Inject ``kind: "csv"`` before validation so those YAMLs still load.

    Covers two discriminator surfaces:
      * ``trigger.kind`` (from change 014).
      * ``metadata.sources[i].kind`` (from change 015).
    """
    trigger = data.get("trigger")
    if isinstance(trigger, dict) and "kind" not in trigger:
        trigger["kind"] = "csv"
    metadata = data.get("metadata")
    if isinstance(metadata, dict):
        sources = metadata.get("sources")
        if isinstance(sources, list):
            for source in sources:
                if isinstance(source, dict) and "kind" not in source:
                    source["kind"] = "csv"


def load_secrets() -> Secrets:
    """Read CMIS_USERNAME / CMIS_PASSWORD (required) + AS400_* (optional)."""
    cmis_username = os.environ.get("CMIS_USERNAME", "").strip()
    cmis_password = os.environ.get("CMIS_PASSWORD", "").strip()
    missing: list[str] = []
    if not cmis_username:
        missing.append("CMIS_USERNAME")
    if not cmis_password:
        missing.append("CMIS_PASSWORD")
    if missing:
        raise ConfigurationError(
            "required environment variables missing or empty",
            missing_vars=missing,
        )
    return Secrets(
        cmis_username=cmis_username,
        cmis_password=cmis_password,
        as400_username=os.environ.get("AS400_USERNAME", "").strip(),
        as400_password=os.environ.get("AS400_PASSWORD", "").strip(),
    )
