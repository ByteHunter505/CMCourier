"""Metadata resolution service.

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
    ClientTrigger,
    CMMapping,
    ResolvedMetadata,
    RVABREPDocument,
    Trigger,
)
from cmcourier.domain.ports import IDataSource

_logger = logging.getLogger(__name__)

_CSV_PREFIX = "csv:"
_AS400_PREFIX = "as400:"


def _trigger_cif(trigger: Trigger) -> str | None:
    """046 — extract the CIF from whatever shape the trigger surfaces.

    ``ClientTrigger.cif`` is the canonical attribute path; row-based
    triggers (``RvabrepRowTrigger``, ``LocalScanTrigger``) carry the CIF
    inside their row under their configured ``col_cif`` column. The
    audit_row projection already knows how to extract it; we just
    consume that.
    """
    if isinstance(trigger, ClientTrigger):
        return trigger.cif
    audit = trigger.audit_row()
    cif = audit.get("cif")
    return cif if isinstance(cif, str) and cif else None


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
    """Top-level metadata resolution config."""

    field_aliases: Mapping[str, str]
    field_sources: Mapping[str, FieldSourceConfig]
    prefetch_enabled: bool = True


@dataclass(frozen=True, slots=True)
class MetadataResolution:
    """Result of resolve(): the metadata bag plus the (possibly healed) trigger.

    046: ``healed_trigger`` is polymorphic. For ``ClientTrigger`` inputs the
    resolver may produce a new ``ClientTrigger`` with the CIF field set to
    the self-healed value. For row-based subtypes the original trigger is
    returned unchanged — the row mapping is immutable, and the healed CIF
    lives in ``metadata`` (as the ``cmcourier:BAC_CIF`` property) and in
    the document_cache (037) rather than re-projected onto the trigger.
    """

    metadata: ResolvedMetadata
    healed_trigger: Trigger
    # 046: the resolved CIF, captured explicitly so the document_cache
    # can persist it without inspecting the trigger subtype.
    healed_cif: str | None = None


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
        trigger: Trigger,
        document: RVABREPDocument,
        mapping: CMMapping,
    ) -> MetadataResolution:
        """Resolve every required metadata field."""
        canonical_fields, canonical_to_friendly = self._normalize_fields_with_friendly(
            mapping.required_metadata_fields
        )
        resolved: dict[str, str] = {}

        # 046: trigger is polymorphic. ``_trigger_cif`` extracts the CIF from
        # whichever attribute the subtype carries (ClientTrigger.cif or
        # row[col_cif] for row-based subtypes).
        current_cif = _trigger_cif(trigger)

        # CIF self-healing FIRST so subsequent CSV lookups can use the
        # resolved value.
        if current_cif is None and "BAC_CIF" in canonical_fields:
            cif_value = self._resolve_one("BAC_CIF", trigger, document, cif_override=current_cif)
            current_cif = cif_value
            resolved["BAC_CIF"] = cif_value

        for f in canonical_fields:
            if f in resolved:
                continue
            resolved[f] = self._resolve_one(f, trigger, document, cif_override=current_cif)

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

        # 046: if the input was a ClientTrigger that had no CIF and we
        # resolved one, return a fresh ClientTrigger with the healed CIF
        # so downstream code that reads `trigger.cif` directly (none left
        # post-046 inside cmcourier, but tests / hooks may) sees the new
        # value. Row-based triggers stay unchanged (their row mapping is
        # immutable); the healed CIF travels in ``metadata`` + ``healed_cif``.
        healed_trigger: Trigger = trigger
        if isinstance(trigger, ClientTrigger) and trigger.cif != current_cif:
            healed_trigger = ClientTrigger(
                shortname=trigger.shortname,
                cif=current_cif,
                system_id=trigger.system_id,
            )
        return MetadataResolution(
            metadata=ResolvedMetadata.from_dict(resolved),
            healed_trigger=healed_trigger,
            healed_cif=current_cif,
        )

    # --- per-field resolution ------------------------------------------

    def _resolve_one(
        self,
        canonical_field: str,
        trigger: Trigger,
        document: RVABREPDocument,
        *,
        cif_override: str | None = None,
    ) -> str:
        if canonical_field not in self._config.field_sources:
            raise ConfigurationError(
                "no field_sources config for field",
                field=canonical_field,
            )
        fsc = self._config.field_sources[canonical_field]
        first_validation = fsc.sources[0].validation if fsc.sources else None

        for sc in fsc.sources:
            value = self._fetch_from_source(sc, trigger, document, cif_override=cif_override)
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
        trigger: Trigger,
        document: RVABREPDocument,
        *,
        cif_override: str | None = None,
    ) -> str | None:
        if sc.source_type == "trigger":
            return self._fetch_trigger(sc, trigger)
        if sc.source_type == "rvabrep":
            return self._fetch_rvabrep(sc, document)
        if sc.source_type.startswith(_CSV_PREFIX):
            alias = sc.source_type[len(_CSV_PREFIX) :]
            return self._fetch_csv(sc, alias, trigger, cif_override=cif_override)
        if sc.source_type.startswith(_AS400_PREFIX):
            raise NotImplementedError(
                "as400:<alias> source type is not yet supported. "
                "The AS400 adapter has not shipped; this source type "
                "will activate when that adapter change merges."
            )
        raise ConfigurationError("unknown source_type", source_type=sc.source_type)

    def _fetch_trigger(self, sc: SourceConfig, trigger: Trigger) -> str | None:
        """Read a field from the trigger.

        Pre-046 the trigger always had ``shortname / cif / system_id`` as
        direct attributes (``ClientTrigger`` shape). Post-046 row-based
        triggers carry the same data inside their ``row`` mapping under
        their configured RVABREP column names. We try the attribute path
        first (works for ClientTrigger and lookup_value_column names like
        ``shortname`` / ``cif``); if the trigger doesn't expose it, we
        fall back to the row + audit projection.
        """
        # ClientTrigger has shortname/cif/system_id as attributes.
        if hasattr(trigger, sc.lookup_value_column):
            value = getattr(trigger, sc.lookup_value_column)
            return None if value is None else str(value)
        # Row-based triggers map lookup_value_column → audit_row projection
        # for shortname/cif/system_id; everything else falls through to None.
        audit = trigger.audit_row()
        if sc.lookup_value_column in audit:
            v = audit[sc.lookup_value_column]
            return None if v is None else str(v)
        raise ConfigurationError(
            "trigger source has no attribute",
            attribute=sc.lookup_value_column,
            trigger_kind=type(trigger).__name__,
        )

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
        trigger: Trigger,
        *,
        cif_override: str | None = None,
    ) -> str | None:
        if alias not in self._sources_registry:
            raise ConfigurationError("unknown CSV alias at resolution time", alias=alias)
        if sc.lookup_key_column is None:
            raise ConfigurationError(
                "csv source requires lookup_key_column",
                source_type=sc.source_type,
            )
        # Convention: csv lookup keys against the trigger's CIF.
        # 046: ``cif_override`` carries the self-healed CIF from S3 when
        # the trigger started without one; falls back to the trigger's own
        # CIF projection. ClientTrigger.cif and row-based triggers'
        # audit_row()["cif"] both feed through ``_trigger_cif``.
        cif = cif_override if cif_override is not None else _trigger_cif(trigger)
        if cif is None:
            return None  # cannot lookup with no CIF
        if self._config.prefetch_enabled:
            cache_key = (alias, sc.lookup_key_column, cif, sc.lookup_value_column)
            return self._csv_cache.get(cache_key)
        # Fallback: direct query
        rows = self._sources_registry[alias].get_by_fields({sc.lookup_key_column: cif})
        if not rows:
            return None
        raw = rows[0].get(sc.lookup_value_column)
        return None if raw is None else str(raw)
