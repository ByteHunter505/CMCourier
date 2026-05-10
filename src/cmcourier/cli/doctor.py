"""Pre-flight validation for the CMCourier pipeline (REBIRTH §10.5).

Six checks run in order, each as a private function returning a
:class:`CheckResult`. Exceptions inside a check are caught and turned
into FAIL results — :func:`run_doctor` MUST NOT raise.

Order:
  1. ``cmis_connectivity`` — CMIS warmup + repositoryInfo.
  2. ``tracking_openable`` — SQLite WAL DB opens at the configured path.
  3. ``mapping_completeness`` — Modelo Documental has ≥1 row.
  4. ``metadata_sources`` — every CSV alias source has ≥1 row.
  5. ``cm_type_alignment`` — every distinct ``cm_object_type`` in
     mapping resolves via CMIS getTypeDefinition. SKIPped if check 1
     failed (no working uploader).
  6. ``sample_dry_run`` — S1→S4 walk on the first trigger's first doc,
     no upload, staged PDF deleted. SKIPped if zero triggers or zero
     docs.

Constitution Principle VIII: NO check message or details field carries
resolved property values. Operational keys (base_url, db_path,
mapping_count, missing types) are OK.
"""

from __future__ import annotations

__all__ = [
    "CheckResult",
    "CheckStatus",
    "DoctorReport",
    "run_doctor",
]

import contextlib
import enum
import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TypeVar

from cmcourier.adapters.assembly import PdfAssembler
from cmcourier.adapters.sources import TabularDataSource
from cmcourier.adapters.tracking import SQLiteTrackingStore
from cmcourier.adapters.upload.cmis_uploader import CmisConfig, CmisUploader
from cmcourier.config.loader import Secrets
from cmcourier.config.schema import PipelineConfig
from cmcourier.config.wiring import build_pipeline
from cmcourier.domain.ports import S0Strategy
from cmcourier.services.indexing import IndexingService
from cmcourier.services.mapping import MappingService
from cmcourier.services.metadata import MetadataService

_log = logging.getLogger(__name__)

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


class CheckStatus(enum.StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    WARN = "WARN"
    SKIP = "SKIP"


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    status: CheckStatus
    message: str
    details: Mapping[str, str] = field(
        default_factory=lambda: MappingProxyType({}),
    )


@dataclass(frozen=True, slots=True)
class DoctorReport:
    results: tuple[CheckResult, ...]
    elapsed_seconds: float

    def _count(self, status: CheckStatus) -> int:
        return sum(1 for r in self.results if r.status == status)

    @property
    def passed_count(self) -> int:
        return self._count(CheckStatus.PASS)

    @property
    def failed_count(self) -> int:
        return self._count(CheckStatus.FAIL)

    @property
    def warn_count(self) -> int:
        return self._count(CheckStatus.WARN)

    @property
    def skip_count(self) -> int:
        return self._count(CheckStatus.SKIP)

    @property
    def has_failures(self) -> bool:
        return self.failed_count > 0


# ---------------------------------------------------------------------------
# run_doctor
# ---------------------------------------------------------------------------


def run_doctor(config: PipelineConfig, secrets: Secrets) -> DoctorReport:
    """Run all checks in order. Never raises."""
    start = time.monotonic()
    results: list[CheckResult] = []
    results.append(_check_cmis_connectivity(config, secrets))
    results.append(_check_tracking_openable(config))
    results.append(_check_mapping_completeness(config))
    results.append(_check_metadata_sources(config))
    if results[0].status == CheckStatus.PASS:
        results.append(_check_cm_type_alignment(config, secrets))
    else:
        results.append(_skip("cm_type_alignment", "cmis_connectivity FAILed; skipping"))
    results.append(_check_sample_dry_run(config, secrets))
    return DoctorReport(
        results=tuple(results),
        elapsed_seconds=time.monotonic() - start,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _frozen(d: Mapping[str, str]) -> Mapping[str, str]:
    return MappingProxyType(dict(d))


def _fail(name: str, exc: Exception, base: Mapping[str, str] | None = None) -> CheckResult:
    details = dict(base or {})
    details["exc_type"] = type(exc).__name__
    details["error"] = str(exc)[:200]
    return CheckResult(
        name=name,
        status=CheckStatus.FAIL,
        message=f"{type(exc).__name__}: {exc}",
        details=_frozen(details),
    )


def _skip(name: str, reason: str) -> CheckResult:
    return CheckResult(
        name=name,
        status=CheckStatus.SKIP,
        message=reason,
        details=_frozen({"reason": reason}),
    )


def _build_uploader(config: PipelineConfig, secrets: Secrets) -> CmisUploader:
    return CmisUploader(
        CmisConfig(
            base_url=config.cmis.base_url,
            repo_id=config.cmis.repo_id,
            username=secrets.cmis_username,
            password=secrets.cmis_password,
            timeout_seconds=config.cmis.timeout_seconds,
            verify_ssl=config.cmis.verify_ssl,
            max_bandwidth_mbps=config.cmis.max_bandwidth_mbps,
            retry_max_attempts=config.cmis.retry_max_attempts,
            retry_base_delay_s=config.cmis.retry_base_delay_s,
        )
    )


def _try(stage: str, fn: Callable[[], T]) -> T | CheckResult:
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 — doctor catches every check exception
        return _fail("sample_dry_run", exc, {"stage": stage})


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def _check_cmis_connectivity(config: PipelineConfig, secrets: Secrets) -> CheckResult:
    try:
        uploader = _build_uploader(config, secrets)
        info = uploader.test_connection()
    except Exception as exc:  # noqa: BLE001
        return _fail(
            "cmis_connectivity",
            exc,
            {"base_url": config.cmis.base_url},
        )
    repo_id = info.get("repository_id", "")
    if not repo_id:
        return CheckResult(
            name="cmis_connectivity",
            status=CheckStatus.FAIL,
            message="CMIS returned empty repository_id",
            details=_frozen({"base_url": config.cmis.base_url}),
        )
    return CheckResult(
        name="cmis_connectivity",
        status=CheckStatus.PASS,
        message=f"CMIS reachable at {config.cmis.base_url}",
        details=_frozen({"repository_id": repo_id}),
    )


def _check_tracking_openable(config: PipelineConfig) -> CheckResult:
    db_path = config.tracking.db_path
    try:
        store = SQLiteTrackingStore(db_path)
        store.close()
    except Exception as exc:  # noqa: BLE001
        return _fail("tracking_openable", exc, {"db_path": str(db_path)})
    return CheckResult(
        name="tracking_openable",
        status=CheckStatus.PASS,
        message=f"SQLite tracking store openable at {db_path}",
        details=_frozen({"db_path": str(db_path)}),
    )


def _check_mapping_completeness(config: PipelineConfig) -> CheckResult:
    try:
        source = TabularDataSource(config.mapping.csv_path)
        try:
            mapping = MappingService(source)
            count = mapping.count()
        finally:
            source.close()
    except Exception as exc:  # noqa: BLE001
        return _fail(
            "mapping_completeness",
            exc,
            {"csv_path": str(config.mapping.csv_path)},
        )
    if count == 0:
        return CheckResult(
            name="mapping_completeness",
            status=CheckStatus.WARN,
            message="Modelo Documental has zero rows",
            details=_frozen({"mapping_count": "0"}),
        )
    return CheckResult(
        name="mapping_completeness",
        status=CheckStatus.PASS,
        message=f"Modelo Documental has {count} mappings",
        details=_frozen({"mapping_count": str(count)}),
    )


def _check_metadata_sources(config: PipelineConfig) -> CheckResult:
    empty_aliases: list[str] = []
    counts: dict[str, str] = {}
    for source_cfg in config.metadata.sources:
        try:
            src = TabularDataSource(source_cfg.csv_path)
            try:
                count = src.count()
            finally:
                src.close()
        except Exception as exc:  # noqa: BLE001
            return _fail(
                "metadata_sources",
                exc,
                {"alias": source_cfg.alias, "csv_path": str(source_cfg.csv_path)},
            )
        counts[source_cfg.alias] = str(count)
        if count == 0:
            empty_aliases.append(source_cfg.alias)
    if empty_aliases:
        return CheckResult(
            name="metadata_sources",
            status=CheckStatus.WARN,
            message=f"empty sources: {','.join(empty_aliases)}",
            details=_frozen({**counts, "empty_aliases": ",".join(empty_aliases)}),
        )
    return CheckResult(
        name="metadata_sources",
        status=CheckStatus.PASS,
        message=f"{len(config.metadata.sources)} metadata sources, all non-empty",
        details=_frozen(counts),
    )


def _check_cm_type_alignment(config: PipelineConfig, secrets: Secrets) -> CheckResult:
    try:
        mapping_src = TabularDataSource(config.mapping.csv_path)
        try:
            mapping = MappingService(mapping_src)
            unique_types = sorted({m.cm_object_type for m in mapping.get_all()})
        finally:
            mapping_src.close()
        uploader = _build_uploader(config, secrets)
    except Exception as exc:  # noqa: BLE001
        return _fail("cm_type_alignment", exc)
    missing: list[str] = []
    for type_id in unique_types:
        try:
            uploader.get_type_definition(type_id)
        except Exception:  # noqa: BLE001 — surface every missing in one pass
            missing.append(type_id)
    if missing:
        return CheckResult(
            name="cm_type_alignment",
            status=CheckStatus.FAIL,
            message=f"{len(missing)} cm_object_type(s) missing on CM",
            details=_frozen(
                {
                    "missing_types": ",".join(missing),
                    "checked_count": str(len(unique_types)),
                }
            ),
        )
    return CheckResult(
        name="cm_type_alignment",
        status=CheckStatus.PASS,
        message=f"all {len(unique_types)} cm_object_type(s) resolve on CM",
        details=_frozen({"checked_count": str(len(unique_types))}),
    )


def _check_sample_dry_run(config: PipelineConfig, secrets: Secrets) -> CheckResult:
    try:
        pipeline = build_pipeline(config, secrets)
    except Exception as exc:  # noqa: BLE001
        return _fail("sample_dry_run", exc, {"stage": "construction"})
    # Re-extract the collaborators we need (the orchestrator hides them).
    # Doctor manually walks S1..S4 to avoid touching the tracking store.
    services = _DryRunServices(
        trigger_strategy=pipeline._trigger_strategy,
        indexing=pipeline._indexing_service,
        mapping=pipeline._mapping_service,
        metadata=pipeline._metadata_service,
        assembler=pipeline._assembler,
    )
    return _dry_run_first_doc(services, source_descriptor=str(config.trigger.csv_path))


# ---------------------------------------------------------------------------
# Dry-run plumbing
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _DryRunServices:
    trigger_strategy: S0Strategy
    indexing: IndexingService
    mapping: MappingService
    metadata: MetadataService
    assembler: PdfAssembler


def _dry_run_first_doc(services: _DryRunServices, *, source_descriptor: str) -> CheckResult:
    triggers_iter = _try("S0", lambda: list(services.trigger_strategy.acquire(source_descriptor)))
    if isinstance(triggers_iter, CheckResult):
        return triggers_iter
    if not triggers_iter:
        return _skip("sample_dry_run", "no_triggers")
    trigger = triggers_iter[0]
    docs = _try("S1", lambda: services.indexing.find_documents(trigger))
    if isinstance(docs, CheckResult):
        return docs
    if not docs:
        return CheckResult(
            name="sample_dry_run",
            status=CheckStatus.SKIP,
            message="first trigger resolved to no documents",
            details=_frozen({"reason": "no_docs", "shortname": trigger.shortname}),
        )
    doc = docs[0]
    mapping = _try("S2", lambda: services.mapping.get_mapping(doc.index7))
    if isinstance(mapping, CheckResult):
        return mapping
    resolution = _try("S3", lambda: services.metadata.resolve(trigger, doc, mapping))
    if isinstance(resolution, CheckResult):
        return resolution
    staged = _try("S4", lambda: services.assembler.assemble(doc))
    if isinstance(staged, CheckResult):
        return staged
    # Best-effort cleanup so the doctor leaves no artifacts.
    with contextlib.suppress(OSError):
        staged.path.unlink(missing_ok=True)
    return CheckResult(
        name="sample_dry_run",
        status=CheckStatus.PASS,
        message=f"S1..S4 dry-run OK for {doc.txn_num}",
        details=_frozen({"txn_num": doc.txn_num, "stages": "S1,S2,S3,S4"}),
    )
