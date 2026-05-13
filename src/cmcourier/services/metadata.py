"""Metadata resolution service - REBIRTH §6.

Per-field source fallback chain with validation regexes, default-value
fallback, CIF self-healing, field alias normalization, and eager
pre-fetching of csv:<alias> sources at construction. Stage S3 of every
pipeline depends on this service.

Constitution Principle I: imports only ``cmcourier.domain.*`` and stdlib.
Principle VIII: never log resolved field VALUES (PII); log field NAMES only.
"""

from __future__ import annotations

__all__ = [
    "FieldSourceConfig",
    "MetadataConfig",
    "MetadataResolution",
    "MetadataService",
    "SourceConfig",
    "ValidationConfig",
]

import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass

from cmcourier.domain.exceptions import (
    ConfigurationError,
    DefaultValidationFailedError,
    SourceFailedError,
)
from cmcourier.domain.models import (
    CMMapping,
    ResolvedMetadata,
    RVABREPDocument,
    TriggerRecord,
)
from cmcourier.domain.ports import IDataSource

_logger = logging.getLogger(__name__)

_CSV_PREFIX = "csv:"
_AS400_PREFIX = "as400:"

# Used to indicate "all sources tried" in SourceFailedError context.
_ALL_SOURCES_SENTINEL = "<all>"


# ---------------------------------------------------------------------------
# Public configuration / result dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ValidationConfig:
    """Optional validation for a single source's resolved value."""

    allowed_pattern: str | None = None


@dataclass(frozen=True, slots=True)
class SourceConfig:
    """One step of a field's fallback chain."""

    source_type: str
    lookup_value_column: str
    lookup_key_column: str | None = None
    validation: ValidationConfig | None = None


@dataclass(frozen=True, slots=True)
class FieldSourceConfig:
    """The full fallback chain plus default for one canonical (BAC_*) field."""

    sources: tuple[SourceConfig, ...]
    default_value: str | None = None


@dataclass(frozen=True, slots=True)
class MetadataConfig:
    """Top-level metadata resolution config (REBIRTH §6.2 + §6.3 + §6.6)."""

    field_aliases: Mapping[str, str]
    field_sources: Mapping[str, FieldSourceConfig]
    prefetch_enabled: bool = True


@dataclass(frozen=True, slots=True)
class MetadataResolution:
    """Result of resolve(): the metadata bag plus the (possibly healed) trigger."""

    metadata: ResolvedMetadata
    healed_trigger: TriggerRecord


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validates(value: str, validation: ValidationConfig | None) -> bool:
    """Return True if value passes the validation (None validation = always True)."""
    if validation is None or validation.allowed_pattern is None:
        return True
    return re.fullmatch(validation.allowed_pattern, value) is not None


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class MetadataService:
    """Per-field metadata resolution with fallback + CIF self-healing.

    See ``specs/005-metadata-service/{spec,plan}.md`` for full context.
    """

    def __init__(
        self,
        config: MetadataConfig,
        sources_registry: Mapping[str, IDataSource],
    ) -> None:
        self._config = config
        self._sources_registry = sources_registry
        # Cache key shape: (alias, key_column, key_value, value_column) -> value.
        self._csv_cache: dict[tuple[str, str, str, str], str] = {}
        if config.prefetch_enabled:
            self._prefetch_csv_sources()

    # --- construction --------------------------------------------------

    def _prefetch_csv_sources(self) -> None:
        seen_pairs: set[tuple[str, str, str]] = set()
        for fsc in self._config.field_sources.values():
            for sc in fsc.sources:
                if not sc.source_type.startswith(_CSV_PREFIX):
                    continue
                alias = sc.source_type[len(_CSV_PREFIX) :]
                if alias not in self._sources_registry:
                    raise ConfigurationError(
                        "unknown CSV alias referenced in metadata config",
                        alias=alias,
                    )
                if sc.lookup_key_column is None:
                    raise ConfigurationError(
                        "csv source requires lookup_key_column",
                        source_type=sc.source_type,
                    )
                triple = (alias, sc.lookup_key_column, sc.lookup_value_column)
                if triple in seen_pairs:
                    continue
                seen_pairs.add(triple)
                self._populate_cache_for(alias, sc.lookup_key_column, sc.lookup_value_column)

    def _populate_cache_for(self, alias: str, key_col: str, val_col: str) -> None:
        for row in self._sources_registry[alias].get_all():
            key = row.get(key_col)
            val = row.get(val_col)
            if key is None or val is None:
                continue
            cache_key = (alias, key_col, str(key), val_col)
            self._csv_cache.setdefault(cache_key, str(val))  # first wins on dupes

    # --- public entry point --------------------------------------------

    def resolve(
        self,
        trigger: TriggerRecord,
        document: RVABREPDocument,
        mapping: CMMapping,
    ) -> MetadataResolution:
        """Resolve every required metadata field per REBIRTH §6 rules."""
        canonical_fields, canonical_to_friendly = self._normalize_fields_with_friendly(
            mapping.required_metadata_fields
        )
        resolved: dict[str, str] = {}

        # CIF self-healing FIRST so subsequent CSV lookups can use trigger.cif.
        if trigger.cif is None and "BAC_CIF" in canonical_fields:
            cif_value = self._resolve_one("BAC_CIF", trigger, document)
            trigger = TriggerRecord(
                shortname=trigger.shortname,
                cif=cif_value,
                system_id=trigger.system_id,
            )
            resolved["BAC_CIF"] = cif_value

        for f in canonical_fields:
            if f in resolved:
                continue
            resolved[f] = self._resolve_one(f, trigger, document)

        # 038: translate property keys to CMIS property IDs when the
        # mapping carries a catalog (``MetadatosCM.CMISPropertyId``).
        # Keys not in the catalog (or all keys when the catalog is
        # absent / None) pass through unchanged — backward-compat.
        if mapping.cmis_property_ids:
            translated: dict[str, str] = {}
            for canonical, value in resolved.items():
                friendly = canonical_to_friendly.get(canonical, canonical)
                cmis_id = mapping.cmis_property_ids.get(friendly)
                translated[cmis_id if cmis_id else canonical] = value
            resolved = translated

        return MetadataResolution(
            metadata=ResolvedMetadata.from_dict(resolved),
            healed_trigger=trigger,
        )

    # --- per-field resolution ------------------------------------------

    def _resolve_one(
        self,
        canonical_field: str,
        trigger: TriggerRecord,
        document: RVABREPDocument,
    ) -> str:
        if canonical_field not in self._config.field_sources:
            raise ConfigurationError(
                "no field_sources config for field",
                field=canonical_field,
            )
        fsc = self._config.field_sources[canonical_field]
        first_validation = fsc.sources[0].validation if fsc.sources else None

        for sc in fsc.sources:
            value = self._fetch_from_source(sc, trigger, document)
            if value is None or value == "":
                continue
            if not _validates(value, sc.validation):
                _logger.debug(
                    "validation failed for field=%s source=%s",
                    canonical_field,
                    sc.source_type,
                )
                continue
            return value

        # All sources failed. Try the default if present.
        if fsc.default_value is None:
            _logger.warning(
                "all sources failed for field=%s (no default configured)",
                canonical_field,
            )
            raise SourceFailedError(field_name=canonical_field, source=_ALL_SOURCES_SENTINEL)
        if not _validates(fsc.default_value, first_validation):
            raise DefaultValidationFailedError(
                field_name=canonical_field,
                default_value=fsc.default_value,
            )
        return fsc.default_value

    # --- field name normalization --------------------------------------

    def _normalize_fields(self, raw_fields: tuple[str, ...]) -> list[str]:
        canonical, _ = self._normalize_fields_with_friendly(raw_fields)
        return canonical

    def _normalize_fields_with_friendly(
        self, raw_fields: tuple[str, ...]
    ) -> tuple[list[str], dict[str, str]]:
        """Like :meth:`_normalize_fields` but also returns the inverse
        ``canonical -> raw_friendly`` map (038).

        The friendly name is the operator-facing name as written in
        ``MetadatosCM.Metadato`` (preserved verbatim, not stripped). The
        map lets :meth:`resolve` look up ``cmis_property_ids`` — which
        is keyed by friendly name — after resolution has produced
        canonical-keyed values.
        """
        aliases_lower = {k.lower(): v for k, v in self._config.field_aliases.items()}
        canonical: list[str] = []
        canonical_to_friendly: dict[str, str] = {}
        for raw in raw_fields:
            if raw in self._config.field_sources:
                canonical.append(raw)  # already canonical
                canonical_to_friendly[raw] = raw
                continue
            canonical_match = aliases_lower.get(raw.lower())
            if canonical_match is not None:
                canonical.append(canonical_match)
                canonical_to_friendly[canonical_match] = raw
                continue
            raise ConfigurationError(
                "unknown field (no alias and no field_sources entry)",
                field=raw,
            )
        return canonical, canonical_to_friendly

    # --- source dispatch ------------------------------------------------

    def _fetch_from_source(
        self,
        sc: SourceConfig,
        trigger: TriggerRecord,
        document: RVABREPDocument,
    ) -> str | None:
        if sc.source_type == "trigger":
            return self._fetch_trigger(sc, trigger)
        if sc.source_type == "rvabrep":
            return self._fetch_rvabrep(sc, document)
        if sc.source_type.startswith(_CSV_PREFIX):
            alias = sc.source_type[len(_CSV_PREFIX) :]
            return self._fetch_csv(sc, alias, trigger)
        if sc.source_type.startswith(_AS400_PREFIX):
            raise NotImplementedError(
                "as400:<alias> source type is not yet supported. "
                "The AS400 adapter has not shipped; this source type "
                "will activate when that adapter change merges."
            )
        raise ConfigurationError("unknown source_type", source_type=sc.source_type)

    def _fetch_trigger(self, sc: SourceConfig, trigger: TriggerRecord) -> str | None:
        if not hasattr(trigger, sc.lookup_value_column):
            raise ConfigurationError(
                "TriggerRecord has no attribute",
                attribute=sc.lookup_value_column,
            )
        value = getattr(trigger, sc.lookup_value_column)
        return None if value is None else str(value)

    def _fetch_rvabrep(self, sc: SourceConfig, document: RVABREPDocument) -> str | None:
        if not hasattr(document, sc.lookup_value_column):
            raise ConfigurationError(
                "RVABREPDocument has no attribute",
                attribute=sc.lookup_value_column,
            )
        value = getattr(document, sc.lookup_value_column)
        return None if value is None else str(value)

    def _fetch_csv(
        self,
        sc: SourceConfig,
        alias: str,
        trigger: TriggerRecord,
    ) -> str | None:
        if alias not in self._sources_registry:
            raise ConfigurationError("unknown CSV alias at resolution time", alias=alias)
        if sc.lookup_key_column is None:
            raise ConfigurationError(
                "csv source requires lookup_key_column",
                source_type=sc.source_type,
            )
        # Convention: csv lookup keys against trigger.cif (REBIRTH §6 examples).
        if trigger.cif is None:
            return None  # cannot lookup with no CIF
        if self._config.prefetch_enabled:
            cache_key = (alias, sc.lookup_key_column, trigger.cif, sc.lookup_value_column)
            return self._csv_cache.get(cache_key)
        # Fallback: direct query
        rows = self._sources_registry[alias].get_by_fields({sc.lookup_key_column: trigger.cif})
        if not rows:
            return None
        raw = rows[0].get(sc.lookup_value_column)
        return None if raw is None else str(raw)
