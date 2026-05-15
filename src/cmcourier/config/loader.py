"""Loader de configuración YAML + lector de secretos desde env-vars.

Ambas funciones lanzan :class:`ConfigurationError` (de
``cmcourier.domain.exceptions``) ante fallos, con contexto estructurado
para que la CLI pueda exponer detalle diagnóstico al operador.

Principio V de la Constitución: la configuración es la única fuente de
verdad. Principio VIII: las credenciales viven en variables de entorno,
NUNCA en el archivo YAML.
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
    """Credenciales leídas desde variables de entorno al arrancar."""

    cmis_username: str
    cmis_password: str
    as400_username: str = ""
    as400_password: str = ""


def load_config(path: Path) -> PipelineConfig:
    """Lee *path* como YAML y devuelve un :class:`PipelineConfig` validado."""
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
    _reject_removed_kinds(data)
    try:
        return PipelineConfig.model_validate(data)
    except ValidationError as exc:
        raise ConfigurationError(
            "config validation failed",
            errors=exc.errors(),
        ) from exc


def _reject_removed_kinds(data: dict[str, object]) -> None:
    """048: ``trigger.kind: as400`` fue removido.

    "AS400" ahora es una elección de *source*, no un `kind` de trigger —
    el pipeline RVABREP es el mismo pipeline independientemente de dónde
    viva su tabla RVABREP. El error de unión discriminada de Pydantic
    ante un ``kind`` desconocido es críptico; exponemos uno directivo
    que apunta a la nueva forma.
    """
    trigger = data.get("trigger")
    if isinstance(trigger, dict) and trigger.get("kind") == "as400":
        raise ConfigurationError(
            "trigger.kind 'as400' was removed in 0.51.0 — AS400 is now a "
            "source choice, not a trigger kind. Use trigger.kind: rvabrep "
            "and set indexing.source.kind: as400 with connection + query.",
            removed_kind="as400",
            migrate_to="trigger.kind: rvabrep + indexing.source.kind: as400",
        )


def _inject_default_kinds(data: dict[str, object]) -> None:
    """Retrocompatibilidad: el discriminador ``kind`` por defecto es ``"csv"``.

    Las uniones discriminadas de Pydantic v2 requieren el campo
    discriminador. Las configuraciones existentes del change 012 omiten
    ``kind`` por completo — los schemas originales tenían formas únicas
    (``TriggerCsvConfig``, ``MetadataSourceConfig`` solo `csv`). Inyectamos
    ``kind: "csv"`` antes de validar para que esos YAMLs sigan cargando.

    Cubre dos superficies de discriminador:
      * ``trigger.kind`` (del change 014).
      * ``metadata.sources[i].kind`` (del change 015).
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
    """Lee CMIS_USERNAME / CMIS_PASSWORD (requeridos) + AS400_* (opcionales)."""
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
