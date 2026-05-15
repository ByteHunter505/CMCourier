"""Mapping service - in-memory cache + lookup over the Modelo Documental.

Loads every row from any :class:`IDataSource` at construction
and builds an ``id_rvi -> CMMapping`` dict for O(1) lookup. Subsequent
``get_mapping`` calls hit the cache. The service does no I/O after
construction.

Stage S2 (Document Class Mapping) of every pipeline depends on this
service, as does the ``doctor`` command's mapping-completeness check.

Constitution Principle I: imports only ``cmcourier.domain.*`` and the
Python standard library. No third-party imports, no adapter imports.
"""

from __future__ import annotations

__all__ = ["MappingColumnsConfig", "MappingService"]

import logging
from collections.abc import Iterator
from dataclasses import dataclass
from types import MappingProxyType

from cmcourier.domain.exceptions import ConfigurationError, IDRViNotMappedError
from cmcourier.domain.models import CMMapping
from cmcourier.domain.ports import IDataSource

_logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MappingColumnsConfig:
    """Column-name overrides for both consolidated and split-mode sources.

    Consolidated mode (``col_*`` family without ``rvi_cm`` / ``metadatos``
    prefix) matches the legacy test fixture layout. Split mode (035,
    ``col_rvi_cm_*`` and ``col_metadatos_*`` families) matches the
    bank's production CSV pair.
    """

    col_clase_id: str = "ID CLASE DOCUMENTAL"
    col_id_rvi: str = "ID RVI"
    col_id_corto: str = "ID Corto"
    col_clase_name: str = "CLASE DOCUMENTAL"
    col_metadata_list: str = "METADATOS"
    col_cmis_type: str = "CMISType"
    col_rvi_cm_id_rvi: str = "IDRVI"
    col_rvi_cm_id_cm: str = "IDCM"
    col_rvi_cm_clase_id: str = "IDClaseDocumental"
    col_rvi_cm_cmis_type: str = "CMISType"
    col_rvi_cm_cmis_folder: str = "CMISFolder"
    col_metadatos_id_corto: str = "IDCorto"
    col_metadatos_metadata: str = "Metadato"
    col_metadatos_required: str = "Requerido"
    col_metadatos_cmis_property_id: str = "CMISPropertyId"
    required_marker: str = "Yes"

    def required_columns(self) -> tuple[str, ...]:
        """Columns the consolidated-mode loader must find in the source.

        ``col_cmis_type`` is intentionally NOT required — it's read
        when present and defaults to "" when absent (the legacy
        fixture has no CMISType column).
        """
        return (
            self.col_clase_id,
            self.col_id_rvi,
            self.col_id_corto,
            self.col_clase_name,
            self.col_metadata_list,
        )

    def required_columns_rvi_cm(self) -> tuple[str, ...]:
        """Columns the split-mode loader must find in MapeoRVI_CM."""
        return (
            self.col_rvi_cm_id_rvi,
            self.col_rvi_cm_id_cm,
            self.col_rvi_cm_clase_id,
        )

    def required_columns_metadatos(self) -> tuple[str, ...]:
        """Columns the split-mode loader must find in MetadatosCM."""
        return (
            self.col_metadatos_id_corto,
            self.col_metadatos_metadata,
            self.col_metadatos_required,
        )


def _is_blank(value: object) -> bool:
    """Return True if *value* is None, empty, or whitespace-only."""
    return value is None or (isinstance(value, str) and not value.strip())


def _parse_metadata_list(raw: object) -> tuple[str, ...]:
    """Parse the ``METADATOS`` cell into a tuple of trimmed, non-empty fields."""
    if _is_blank(raw) or not isinstance(raw, str):
        return ()
    parts = (p.strip() for p in raw.split(","))
    return tuple(p for p in parts if p)


_TRUTHY_REQUIRED_SYNONYMS = frozenset({"yes", "sí", "si", "true", "1", "y", "s"})


def _is_required(value: object, custom_marker: str) -> bool:
    """Decide whether a ``MetadatosCM.Requerido`` cell counts as required.

    Anything matching ``custom_marker`` (case-insensitive, whitespace-
    stripped, accent-tolerant on the default "Yes" path) or one of the
    common truthy synonyms — "yes", "sí", "true", "1" — counts. Empty
    cells and "no" / "false" / "0" drop the field.
    """
    if value is None:
        return False
    text = str(value).strip().lower()
    if not text:
        return False
    if text == custom_marker.strip().lower():
        return True
    return text in _TRUTHY_REQUIRED_SYNONYMS


class MappingService:
    """In-memory cache + lookup over the Modelo Documental.

    Construction iterates the entire source once, validates required columns,
    and builds a dict keyed by ``id_rvi``. First occurrence of a duplicate
    ``id_rvi`` wins; subsequent occurrences are dropped with a
    ``WARNING`` log entry. Rows whose ``id_rvi`` is blank are silently
    skipped, with an ``INFO`` log entry summarizing the count.

    The service does not own the source's lifecycle; callers ``close()`` it.
    """

    def __init__(
        self,
        source: IDataSource,
        columns: MappingColumnsConfig | None = None,
        metadata_source: IDataSource | None = None,
    ) -> None:
        self._columns = columns or MappingColumnsConfig()
        self._cache: dict[str, CMMapping] = {}
        if metadata_source is None:
            self._load(source)
        else:
            self._load_split(source, metadata_source)

    def _load_split(self, rvi_cm: IDataSource, metadatos: IDataSource) -> None:
        """Split-mode loader (035): join MapeoRVI_CM with MetadatosCM by IDCM↔IDCorto."""
        required_index, cmis_property_id_index = self._build_metadatos_index(metadatos)
        skipped = 0
        validated = False
        for row in rvi_cm.get_all():
            if not validated:
                self._validate_rvi_cm_columns(row)
                validated = True

            id_rvi_raw = row.get(self._columns.col_rvi_cm_id_rvi)
            if _is_blank(id_rvi_raw):
                skipped += 1
                continue
            id_rvi = str(id_rvi_raw).strip()

            if id_rvi in self._cache:
                _logger.warning(
                    "duplicate ID RVI %r dropped from mapping (first occurrence wins)",
                    id_rvi,
                )
                continue

            self._cache[id_rvi] = self._row_to_mapping_split(
                row, id_rvi, required_index, cmis_property_id_index
            )

        if skipped:
            _logger.info(
                "skipped %d row(s) from MapeoRVI_CM with empty IDRVI",
                skipped,
            )

    def _build_metadatos_index(
        self, metadatos: IDataSource
    ) -> tuple[dict[str, tuple[str, ...]], dict[str, dict[str, str]]]:
        """Return ``(required_fields_by_id_corto, cmis_property_ids_by_id_corto)``.

        Required fields: rows whose ``Requerido`` parses truthy. Field
        names are whitespace-stripped, order preserved.

        CMIS property ids (038): ``{id_corto: {field: cmis_property_id}}``
        for rows whose ``CMISPropertyId`` column is non-blank. Friendly
        field name is the key. When the column is absent from the source
        or every cell is blank, the per-id_corto dict is omitted, which
        signals "no catalog" to the metadata service.
        """
        fields_index: dict[str, list[str]] = {}
        cmis_ids_index: dict[str, dict[str, str]] = {}
        validated = False
        for row in metadatos.get_all():
            if not validated:
                self._validate_metadatos_columns(row)
                validated = True
            id_corto_raw = row.get(self._columns.col_metadatos_id_corto)
            if _is_blank(id_corto_raw):
                continue
            id_corto = str(id_corto_raw).strip()
            if not _is_required(
                row.get(self._columns.col_metadatos_required),
                self._columns.required_marker,
            ):
                continue
            field_raw = row.get(self._columns.col_metadatos_metadata)
            if _is_blank(field_raw):
                continue
            field = str(field_raw).strip()
            fields_index.setdefault(id_corto, []).append(field)
            cmis_prop_raw = row.get(self._columns.col_metadatos_cmis_property_id)
            if not _is_blank(cmis_prop_raw):
                cmis_ids_index.setdefault(id_corto, {})[field] = str(cmis_prop_raw).strip()
        return (
            {k: tuple(v) for k, v in fields_index.items()},
            cmis_ids_index,
        )

    def _validate_rvi_cm_columns(self, row: dict[str, object]) -> None:
        for col in self._columns.required_columns_rvi_cm():
            if col not in row:
                raise ConfigurationError(
                    "MapeoRVI_CM missing required column",
                    missing_column=col,
                )

    def _validate_metadatos_columns(self, row: dict[str, object]) -> None:
        for col in self._columns.required_columns_metadatos():
            if col not in row:
                raise ConfigurationError(
                    "MetadatosCM missing required column",
                    missing_column=col,
                )

    def _row_to_mapping_split(
        self,
        row: dict[str, object],
        id_rvi: str,
        required_index: dict[str, tuple[str, ...]],
        cmis_property_id_index: dict[str, dict[str, str]],
    ) -> CMMapping:
        clase_id = str(row[self._columns.col_rvi_cm_clase_id]).strip()
        id_corto = str(row[self._columns.col_rvi_cm_id_cm]).strip()
        cmis_type_raw = row.get(self._columns.col_rvi_cm_cmis_type)
        cmis_type = "" if cmis_type_raw is None else str(cmis_type_raw).strip()
        cmis_folder_raw = row.get(self._columns.col_rvi_cm_cmis_folder)
        cmis_folder: str | None = (
            None if _is_blank(cmis_folder_raw) else str(cmis_folder_raw).strip()
        )
        cmis_property_ids_dict = cmis_property_id_index.get(id_corto)
        cmis_property_ids: MappingProxyType[str, str] | None = (
            MappingProxyType(cmis_property_ids_dict) if cmis_property_ids_dict else None
        )
        return CMMapping(
            clase_id=clase_id,
            id_rvi=id_rvi,
            id_corto=id_corto,
            clase_name=clase_id,
            required_metadata_fields=required_index.get(id_corto, ()),
            cmis_type=cmis_type,
            cmis_folder=cmis_folder,
            cmis_property_ids=cmis_property_ids,
        )

    def _load(self, source: IDataSource) -> None:
        skipped = 0
        validated = False
        for row in source.get_all():
            if not validated:
                self._validate_columns(row)
                validated = True

            id_rvi_raw = row.get(self._columns.col_id_rvi)
            if _is_blank(id_rvi_raw):
                skipped += 1
                continue
            id_rvi = str(id_rvi_raw).strip()

            if id_rvi in self._cache:
                _logger.warning(
                    "duplicate ID RVI %r dropped from mapping (first occurrence wins)",
                    id_rvi,
                )
                continue

            self._cache[id_rvi] = self._row_to_mapping(row, id_rvi)

        if skipped:
            _logger.info(
                "skipped %d row(s) from Modelo Documental with empty ID RVI",
                skipped,
            )

    def _validate_columns(self, row: dict[str, object]) -> None:
        for col in self._columns.required_columns():
            if col not in row:
                raise ConfigurationError(
                    "Modelo Documental missing required column",
                    missing_column=col,
                )

    def _row_to_mapping(self, row: dict[str, object], id_rvi: str) -> CMMapping:
        cmis_type_raw = row.get(self._columns.col_cmis_type)
        cmis_type = "" if cmis_type_raw is None else str(cmis_type_raw).strip()
        return CMMapping(
            clase_id=str(row[self._columns.col_clase_id]).strip(),
            id_rvi=id_rvi,
            id_corto=str(row[self._columns.col_id_corto]).strip(),
            clase_name=str(row[self._columns.col_clase_name]).strip(),
            required_metadata_fields=_parse_metadata_list(row.get(self._columns.col_metadata_list)),
            cmis_type=cmis_type,
        )

    def get_mapping(self, id_rvi: str) -> CMMapping:
        """Return the :class:`CMMapping` for *id_rvi*; raise on miss."""
        try:
            return self._cache[id_rvi]
        except KeyError:
            raise IDRViNotMappedError(id_rvi=id_rvi) from None

    def get_all(self) -> Iterator[CMMapping]:
        """Yield every cached mapping in the order rows arrived from the source."""
        return iter(self._cache.values())

    def count(self) -> int:
        """Return the number of mappings cached."""
        return len(self._cache)

    def __contains__(self, id_rvi: object) -> bool:
        return isinstance(id_rvi, str) and id_rvi in self._cache
