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
from cmcourier.adapters.sources import As400DataSource, TabularDataSource
from cmcourier.adapters.tracking import SQLiteTrackingStore
from cmcourier.adapters.upload.cmis_uploader import CmisConfig, CmisUploader
from cmcourier.config.loader import Secrets
from cmcourier.config.schema import (
    As400MetadataSourceConfig,
    As400TriggerConfig,
    CsvMetadataSourceConfig,
    CsvTriggerConfig,
    MetadataSourceConfig,
    PipelineConfig,
    SingleDocTriggerConfig,
)
from cmcourier.config.wiring import build_mapping_service, build_pipeline
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


# REBIRTH §11 group → check names. ``all`` is the sentinel.
_CHECK_GROUPS: dict[str, frozenset[str]] = {
    "connections": frozenset(
        {
            "log_dir_writable",
            "cmis_connectivity",
            "as400_connectivity",
            "tracking_openable",
        }
    ),
    "mapping": frozenset({"mapping_completeness"}),
    "metadata": frozenset({"metadata_sources", "sample_dry_run"}),
    "cm-types": frozenset({"cm_type_alignment"}),
    "all": frozenset(),
}


def _selected(name: str, selected: str) -> bool:
    """True when ``name`` belongs to the active filter group."""
    if selected == "all":
        return True
    return name in _CHECK_GROUPS.get(selected, frozenset())


def run_doctor(
    config: PipelineConfig,
    secrets: Secrets,
    *,
    selected: str = "all",
) -> DoctorReport:
    """Run pre-flight checks. ``selected`` filters by REBIRTH §11 group."""
    start = time.monotonic()
    results: list[CheckResult] = []
    if _selected("log_dir_writable", selected):
        results.append(_check_log_dir_writable(config))
    if _selected("cmis_connectivity", selected):
        results.append(_check_cmis_connectivity(config, secrets))
    if _selected("as400_connectivity", selected):
        results.append(_check_as400_connectivity(config, secrets))
    if _selected("tracking_openable", selected):
        results.append(_check_tracking_openable(config))
    if _selected("as400_sync", selected):
        results.append(_check_as400_sync(config, secrets))
    if _selected("mapping_completeness", selected):
        results.append(_check_mapping_completeness(config))
    if _selected("metadata_sources", selected):
        results.append(_check_metadata_sources(config, secrets))
    if _selected("cm_type_alignment", selected):
        cmis_check = next((r for r in results if r.name == "cmis_connectivity"), None)
        if cmis_check is not None and cmis_check.status != CheckStatus.PASS:
            results.append(_skip("cm_type_alignment", "cmis_connectivity FAILed; skipping"))
        else:
            results.append(_check_cm_type_alignment(config, secrets))
    if _selected("sample_dry_run", selected):
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


def _mapping_path_repr(config: PipelineConfig) -> str:
    """Display the Modelo Documental path(s) regardless of mode (035)."""
    mc = config.mapping
    if mc.csv_path is not None:
        return str(mc.csv_path)
    return f"{mc.rvi_cm_csv_path} + {mc.metadatos_csv_path}"


def _skip(name: str, reason: str) -> CheckResult:
    return CheckResult(
        name=name,
        status=CheckStatus.SKIP,
        message=reason,
        details=_frozen({"reason": reason}),
    )


def _open_metadata_source(
    source_cfg: MetadataSourceConfig,
    secrets: Secrets,
) -> TabularDataSource | As400DataSource:
    if isinstance(source_cfg, CsvMetadataSourceConfig):
        return TabularDataSource(source_cfg.csv_path)
    if isinstance(source_cfg, As400MetadataSourceConfig):
        return As400DataSource(
            host=source_cfg.as400_connection.host,
            port=source_cfg.as400_connection.port,
            database=source_cfg.as400_connection.database,
            driver=source_cfg.as400_connection.driver,
            username=secrets.as400_username,
            password=secrets.as400_password,
            table=source_cfg.table or "",
            query=source_cfg.query,
        )
    raise RuntimeError(f"unknown metadata source kind: {source_cfg!r}")


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


def _check_log_dir_writable(config: PipelineConfig) -> CheckResult:
    log_dir = config.observability.log_dir
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        probe = log_dir / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except OSError as exc:
        return _fail(
            "log_dir_writable",
            exc,
            {"log_dir": str(log_dir)},
        )
    return CheckResult(
        name="log_dir_writable",
        status=CheckStatus.PASS,
        message=f"log_dir is writable at {log_dir}",
        details=_frozen({"log_dir": str(log_dir)}),
    )


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


def _check_as400_connectivity(config: PipelineConfig, secrets: Secrets) -> CheckResult:
    trigger = config.trigger
    if not isinstance(trigger, As400TriggerConfig):
        return _skip("as400_connectivity", "trigger_kind_not_as400")
    if not secrets.as400_username or not secrets.as400_password:
        return CheckResult(
            name="as400_connectivity",
            status=CheckStatus.FAIL,
            message="AS400 credentials missing in environment",
            details=_frozen({"host": trigger.as400_connection.host}),
        )
    try:
        src = As400DataSource(
            host=trigger.as400_connection.host,
            port=trigger.as400_connection.port,
            database=trigger.as400_connection.database,
            driver=trigger.as400_connection.driver,
            username=secrets.as400_username,
            password=secrets.as400_password,
            table=trigger.as400_connection.table or "",
        )
        try:
            src.query("SELECT 1", [])
        finally:
            src.close()
    except Exception as exc:  # noqa: BLE001
        return _fail(
            "as400_connectivity",
            exc,
            {"host": trigger.as400_connection.host},
        )
    return CheckResult(
        name="as400_connectivity",
        status=CheckStatus.PASS,
        message=f"AS400 reachable at {trigger.as400_connection.host}",
        details=_frozen({"host": trigger.as400_connection.host}),
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


def _check_as400_sync(config: PipelineConfig, secrets: Secrets) -> CheckResult:
    """034: validate AS400 NIARVILOG connection + table when sync is enabled.

    SKIPs when ``tracking.as400_sync.enabled`` is False. When True,
    connects to the configured AS400 and runs a probe query against
    the NIARVILOG table.
    """
    sync_cfg = config.tracking.as400_sync
    if not sync_cfg.enabled:
        return _skip("as400_sync", "disabled (tracking.as400_sync.enabled=false)")
    if sync_cfg.connection is None:  # pragma: no cover — schema guards this
        return CheckResult(
            name="as400_sync",
            status=CheckStatus.FAIL,
            message="as400_sync.enabled=true but connection is missing",
            details=_frozen({"reason": "missing_connection"}),
        )
    if not secrets.as400_username or not secrets.as400_password:
        return CheckResult(
            name="as400_sync",
            status=CheckStatus.FAIL,
            message="AS400 credentials missing in environment",
            details=_frozen({"host": sync_cfg.connection.host}),
        )
    full_table = f"{sync_cfg.library}.{sync_cfg.table}"
    try:
        src = As400DataSource(
            host=sync_cfg.connection.host,
            port=sync_cfg.connection.port,
            database=sync_cfg.connection.database,
            driver=sync_cfg.connection.driver,
            username=secrets.as400_username,
            password=secrets.as400_password,
            table=full_table,
        )
        try:
            # 1=0 keeps the probe cheap (zero rows returned, only schema check).
            src.query(f"SELECT 1 FROM {full_table} WHERE 1=0", [])
        finally:
            src.close()
    except Exception as exc:  # noqa: BLE001
        return _fail(
            "as400_sync",
            exc,
            {"host": sync_cfg.connection.host, "table": full_table},
        )
    return CheckResult(
        name="as400_sync",
        status=CheckStatus.PASS,
        message=f"AS400 NIARVILOG reachable at {sync_cfg.connection.host}/{full_table}",
        details=_frozen({"host": sync_cfg.connection.host, "table": full_table}),
    )


def _check_mapping_completeness(config: PipelineConfig) -> CheckResult:
    try:
        mapping = build_mapping_service(config.mapping)
        count = mapping.count()
    except Exception as exc:  # noqa: BLE001
        return _fail(
            "mapping_completeness",
            exc,
            {"csv_path": _mapping_path_repr(config)},
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


def _check_metadata_sources(config: PipelineConfig, secrets: Secrets) -> CheckResult:
    empty_aliases: list[str] = []
    counts: dict[str, str] = {}
    for source_cfg in config.metadata.sources:
        try:
            src = _open_metadata_source(source_cfg, secrets)
            try:
                count = src.count()
            finally:
                src.close()
        except Exception as exc:  # noqa: BLE001
            return _fail(
                "metadata_sources",
                exc,
                {"alias": source_cfg.alias, "kind": source_cfg.kind},
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
        mapping = build_mapping_service(config.mapping)
        unique_types = sorted({m.cm_object_type for m in mapping.get_all()})
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
    if isinstance(config.trigger, SingleDocTriggerConfig):
        return _skip("sample_dry_run", "trigger_kind_single_doc_requires_cli_args")
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
    descriptor = (
        str(config.trigger.csv_path) if isinstance(config.trigger, CsvTriggerConfig) else ""
    )
    return _dry_run_first_doc(services, source_descriptor=descriptor)


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
