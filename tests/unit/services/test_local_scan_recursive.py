"""088: ``LocalScanTriggerStrategy`` con ``recursive=True`` desciende
por todos los subdirectorios del ``scan_path``.

Pre-088 ``iterdir()`` listaba solo el primer nivel — los archivos
bajo cualquier subdirectorio se ignoraban silenciosamente.
Post-088 ``rglob('*')`` cubre todo el árbol cuando el operador opta
en. El default (``False``) preserva el comportamiento pre-088.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cmcourier.adapters.sources import TabularDataSource
from cmcourier.domain.models import LocalScanTrigger
from cmcourier.services.triggers.direct_rvabrep import RvabrepColumnsConfig
from cmcourier.services.triggers.local_scan import LocalScanTriggerStrategy

pytestmark = pytest.mark.unit


def _friendly_columns() -> RvabrepColumnsConfig:
    return RvabrepColumnsConfig(
        col_shortname="shortname",
        col_cif="index2",
        col_system_id="system_id",
        col_id_rvi="index7",
        file_name_column="file_name",
    )


def _rvabrep(tmp_path: Path, files: list[tuple[str, str]]) -> Path:
    """Construye un CSV RVABREP con ``(shortname, file_name)`` por fila."""
    csv = tmp_path / "rvabrep.csv"
    header = "shortname,system_id,index2,index7,file_name\n"
    rows = "".join(f"{short},1,123456,FF17,{name}\n" for short, name in files)
    csv.write_text(header + rows)
    return csv


class TestRecursiveDefault:
    def test_default_is_non_recursive(self, tmp_path: Path) -> None:
        """088: el default (``recursive=False``) preserva el contrato
        pre-088 — solo lista el primer nivel del directorio."""
        scan = tmp_path / "scan"
        scan.mkdir()
        (scan / "TOP.PDF").touch()
        (scan / "subdir").mkdir()
        (scan / "subdir" / "DEEP.PDF").touch()

        csv = _rvabrep(tmp_path, [("CLIENT_TOP", "TOP.PDF"), ("CLIENT_DEEP", "DEEP.PDF")])
        src = TabularDataSource(csv)
        try:
            triggers = list(
                LocalScanTriggerStrategy(scan, src, columns=_friendly_columns()).acquire()
            )
        finally:
            src.close()

        files = {t.file_path.name for t in triggers if isinstance(t, LocalScanTrigger)}
        assert files == {"TOP.PDF"}, (
            f"088 default must be non-recursive — DEEP.PDF leaked: got {files}"
        )


class TestRecursiveOptIn:
    def test_recursive_true_finds_files_in_subdirectories(self, tmp_path: Path) -> None:
        """088: con ``recursive=True``, archivos en subdirectorios profundos
        se incluyen en la iteración."""
        scan = tmp_path / "scan"
        scan.mkdir()
        (scan / "TOP.PDF").touch()
        (scan / "042").mkdir()
        (scan / "042" / "MIDDLE.PDF").touch()
        (scan / "042" / "0526").mkdir()
        (scan / "042" / "0526" / "DEEP.001").touch()

        csv = _rvabrep(
            tmp_path,
            [
                ("CLIENT_TOP", "TOP.PDF"),
                ("CLIENT_MID", "MIDDLE.PDF"),
                ("CLIENT_DEEP", "DEEP.001"),
            ],
        )
        src = TabularDataSource(csv)
        try:
            triggers = list(
                LocalScanTriggerStrategy(
                    scan, src, columns=_friendly_columns(), recursive=True
                ).acquire()
            )
        finally:
            src.close()

        files = {t.file_path.name for t in triggers if isinstance(t, LocalScanTrigger)}
        assert files == {"TOP.PDF", "MIDDLE.PDF", "DEEP.001"}, (
            f"088: recursive must catch all depths — got {files}"
        )

    def test_recursive_preserves_filename_filter(self, tmp_path: Path) -> None:
        """088: ``recursive=True`` no relaja los filtros — solo ``*.PDF``
        y ``*.001`` cuentan, los demás (`.tmp`, `.002`, `.txt`) siguen
        ignorándose aunque estén en subdirectorios."""
        scan = tmp_path / "scan"
        scan.mkdir()
        (scan / "deep").mkdir()
        for name in ("VALID.PDF", "VALID2.001", "skip.tmp", "skip.002", "skip.txt"):
            (scan / "deep" / name).touch()

        csv = _rvabrep(tmp_path, [("CLIENT_A", "VALID.PDF"), ("CLIENT_B", "VALID2.001")])
        src = TabularDataSource(csv)
        try:
            triggers = list(
                LocalScanTriggerStrategy(
                    scan, src, columns=_friendly_columns(), recursive=True
                ).acquire()
            )
        finally:
            src.close()

        files = {t.file_path.name for t in triggers if isinstance(t, LocalScanTrigger)}
        assert files == {"VALID.PDF", "VALID2.001"}, (
            f"088: filename filter must persist in recursive mode — got {files}"
        )

    def test_recursive_false_explicit_ignores_subdirs(self, tmp_path: Path) -> None:
        """088: pasar ``recursive=False`` explícito se comporta como
        el default (no recursivo). Verificación redundante pero
        contractual."""
        scan = tmp_path / "scan"
        scan.mkdir()
        (scan / "TOP.PDF").touch()
        (scan / "nested").mkdir()
        (scan / "nested" / "DEEP.PDF").touch()

        csv = _rvabrep(tmp_path, [("CT", "TOP.PDF"), ("CD", "DEEP.PDF")])
        src = TabularDataSource(csv)
        try:
            triggers = list(
                LocalScanTriggerStrategy(
                    scan, src, columns=_friendly_columns(), recursive=False
                ).acquire()
            )
        finally:
            src.close()

        files = {t.file_path.name for t in triggers if isinstance(t, LocalScanTrigger)}
        assert files == {"TOP.PDF"}


class TestSchemaDefault:
    def test_local_scan_config_default_is_non_recursive(self, tmp_path: Path) -> None:
        from cmcourier.config.schema import LocalScanTriggerConfig

        scan = tmp_path / "scan"
        scan.mkdir()
        cfg = LocalScanTriggerConfig(kind="local_scan", scan_path=scan)
        assert cfg.recursive is False

    def test_local_scan_config_recursive_opt_in(self, tmp_path: Path) -> None:
        from cmcourier.config.schema import LocalScanTriggerConfig

        scan = tmp_path / "scan"
        scan.mkdir()
        cfg = LocalScanTriggerConfig(kind="local_scan", scan_path=scan, recursive=True)
        assert cfg.recursive is True
