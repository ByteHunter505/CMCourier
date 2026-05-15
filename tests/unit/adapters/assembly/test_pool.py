"""Tests unitarios para :mod:`cmcourier.adapters.assembly.pool` (066)."""

from __future__ import annotations

import importlib
import pickle
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


class TestPoolHelpers:
    def test_module_imports_cleanly(self) -> None:
        # 066: el proceso `worker` importa este módulo por nombre; verifica
        # que el path de import sea estable y libre de side-effects.
        mod = importlib.import_module("cmcourier.adapters.assembly.pool")
        assert hasattr(mod, "_pool_init")
        assert hasattr(mod, "_pool_assemble")
        assert hasattr(mod, "build_s4_process_pool")

    def test_helpers_are_picklable_by_reference(self) -> None:
        # 066: `ProcessPoolExecutor` picklea la función `worker` por nombre
        # cualificado al hacer submit. Si los helpers estuvieran anidados
        # dentro de una función (la forma buggy), pickle fallaría con
        # `PicklingError`. Este test fija el contrato.
        from cmcourier.adapters.assembly.pool import _pool_assemble, _pool_init

        pickled_init = pickle.dumps(_pool_init)
        pickled_work = pickle.dumps(_pool_assemble)
        assert pickle.loads(pickled_init) is _pool_init
        assert pickle.loads(pickled_work) is _pool_assemble

    def test_init_and_assemble_in_main_process_round_trips(self, tmp_path: Path) -> None:
        # 066: prueba end-to-end de los helpers en el proceso *actual* —
        # construye un assembler `worker`, ejecuta assemble. Confirma el
        # contrato de estado global (init debe correr antes de assemble).
        from cmcourier.adapters.assembly import pool as pool_mod
        from cmcourier.adapters.assembly.pdf_assembler import AssemblerConfig

        # Construye un escenario simple de documento paginado: 1 PDF nativo.
        source_root = tmp_path / "source"
        (source_root / "PROD").mkdir(parents=True)
        from cmcourier.adapters.assembly.pdf_assembler import PdfAssembler

        pdf_path = source_root / "PROD" / "TESTFILE.001"
        # Cuerpo PDF mínimo válido para que el camino img2pdf / shutil.copy2
        # funcione.
        pdf_path.write_bytes(b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n")

        cfg = AssemblerConfig(source_root=source_root, temp_dir=tmp_path / "tmp")
        pool_mod._pool_init(cfg)
        assert pool_mod._worker_assembler is not None
        assert isinstance(pool_mod._worker_assembler, PdfAssembler)
        # Limpieza para que otros tests no vean estado residual.
        pool_mod._worker_assembler = None

    def test_assemble_without_init_raises_runtime_error(self) -> None:
        from cmcourier.adapters.assembly import pool as pool_mod
        from cmcourier.domain.models import RVABREPDocument

        # Asegura estado limpio.
        pool_mod._worker_assembler = None
        from datetime import datetime as _dt

        doc = RVABREPDocument(
            system_code="1",
            txn_num="TXN",
            index1="1",
            index2="1",
            index3="",
            index4="",
            index5="",
            index6="",
            index7="CC03",
            image_type="B",
            image_path="x",
            file_name="DAAAH9X4.001",
            creation_date=_dt(2025, 11, 17),
            last_view_date=None,
            total_pages=1,
            delete_code="",
        )
        with pytest.raises(RuntimeError, match="_pool_init"):
            pool_mod._pool_assemble(doc)
