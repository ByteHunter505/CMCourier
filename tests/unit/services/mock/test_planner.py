"""Tests unitarios para ``cmcourier.services.mock.planner`` (031, REQ-006..REQ-016)."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from cmcourier.config.schema import IndexingColumnsModel
from cmcourier.domain.exceptions import ConfigurationError
from cmcourier.services.mock.planner import (
    PlannerFilters,
    SizeBounds,
    normalize_image_path,
    plan_files,
)

# Los defaults coinciden con `IndexingColumnsModel()` — ver `config/schema.py:149`.
_COLS = IndexingColumnsModel()

_BOUNDS = SizeBounds(
    pdf_min=10 * 1024,
    pdf_max=80 * 1024,
    img_min=2 * 1024,
    img_max=30 * 1024,
)


def _row(
    *,
    shortname: str = "S1",
    system: str = "SYS",
    delete: str = "",
    txn: str = "TXN001",
    id_rvi: str = "TYPE1",
    image_type: str = "B",
    image_path: str = "docs/2024",
    file_name: str = "DOC0001.001",
    total_pages: str = "1",
) -> dict[str, object]:
    return {
        _COLS.shortname_column: shortname,
        _COLS.system_id_column: system,
        _COLS.delete_code_column: delete,
        _COLS.txn_num_column: txn,
        _COLS.index7_column: id_rvi,
        _COLS.image_type_column: image_type,
        _COLS.image_path_column: image_path,
        _COLS.file_name_column: file_name,
        _COLS.total_pages_column: total_pages,
    }


class TestNormalizeImagePath:
    def test_strips_leading_forward_slash(self) -> None:
        assert normalize_image_path("/docs/2024") == Path("docs/2024")

    def test_strips_leading_backslashes_and_normalizes(self) -> None:
        assert normalize_image_path(r"\\server\share\docs\2024") == Path("server/share/docs/2024")

    def test_mixed_separators(self) -> None:
        assert normalize_image_path(r"docs\sub/dir\file") == Path("docs/sub/dir/file")

    def test_already_clean(self) -> None:
        assert normalize_image_path("docs/2024") == Path("docs/2024")


class TestDispatch:
    def test_pdf_row_yields_one_pdf_plan(self) -> None:
        row = _row(file_name="DOC.PDF", total_pages="3", image_type="O")
        plans = list(plan_files([row], _COLS, PlannerFilters(), _BOUNDS))
        assert len(plans) == 1
        assert plans[0].kind == "pdf"
        assert plans[0].pages == 3
        assert plans[0].extensions == (".PDF",)
        assert plans[0].file_code == "DOC"
        assert plans[0].size_min == _BOUNDS.pdf_min
        assert plans[0].size_max == _BOUNDS.pdf_max

    def test_tiff_row_yields_paged_plan(self) -> None:
        row = _row(image_type="B", total_pages="3", file_name="IMG.001")
        plans = list(plan_files([row], _COLS, PlannerFilters(), _BOUNDS))
        assert len(plans) == 1
        plan = plans[0]
        assert plan.kind == "tiff"
        assert plan.pages == 3
        assert plan.extensions == (".001", ".002", ".003")
        assert plan.size_min == _BOUNDS.img_min
        assert plan.size_max == _BOUNDS.img_max

    def test_jpeg_single_page_extension_is_001(self) -> None:
        row = _row(image_type="C", total_pages="1", file_name="JPG.001")
        plans = list(plan_files([row], _COLS, PlannerFilters(), _BOUNDS))
        assert plans[0].kind == "jpeg"
        assert plans[0].extensions == (".001",)

    def test_unknown_image_type_raises(self) -> None:
        row = _row(image_type="Z", file_name="X.001")
        with pytest.raises(ConfigurationError, match="image_type"):
            list(plan_files([row], _COLS, PlannerFilters(), _BOUNDS))

    def test_pdf_with_lowercase_extension_dispatches_as_pdf(self) -> None:
        # `is_pdf_filename` es case-insensitive; `ABABST` puede decir
        # cualquier cosa para PDFs.
        row = _row(file_name="DOC.pdf", total_pages="2", image_type="O")
        plans = list(plan_files([row], _COLS, PlannerFilters(), _BOUNDS))
        assert plans[0].kind == "pdf"
        assert plans[0].pages == 2

    def test_total_pages_missing_defaults_to_one(self) -> None:
        row = _row(image_type="B", total_pages="", file_name="X.001")
        plans = list(plan_files([row], _COLS, PlannerFilters(), _BOUNDS))
        assert plans[0].pages == 1
        assert plans[0].extensions == (".001",)

    def test_total_pages_zero_defaults_to_one(self) -> None:
        row = _row(image_type="C", total_pages="0", file_name="X.001")
        plans = list(plan_files([row], _COLS, PlannerFilters(), _BOUNDS))
        assert plans[0].pages == 1

    def test_empty_image_path_raises(self) -> None:
        row = _row(image_path="")
        with pytest.raises(ConfigurationError, match="image_path"):
            list(plan_files([row], _COLS, PlannerFilters(), _BOUNDS))


class TestFilters:
    def test_deleted_row_skipped_by_default(self) -> None:
        row = _row(delete="X", file_name="A.001")
        plans = list(plan_files([row], _COLS, PlannerFilters(), _BOUNDS))
        assert plans == []

    def test_include_deleted_yields_deleted_rows(self) -> None:
        row = _row(delete="X", file_name="A.001")
        plans = list(plan_files([row], _COLS, PlannerFilters(), _BOUNDS, include_deleted=True))
        assert len(plans) == 1

    def test_system_filter(self) -> None:
        rows = [
            _row(system="A", file_name="A.001", image_path="p/A"),
            _row(system="B", file_name="B.001", image_path="p/B"),
            _row(system="C", file_name="C.001", image_path="p/C"),
        ]
        plans = list(
            plan_files(rows, _COLS, PlannerFilters(systems=("A", "C")), _BOUNDS),
        )
        assert sorted(p.file_code for p in plans) == ["A", "C"]

    def test_document_type_filter(self) -> None:
        rows = [
            _row(id_rvi="T1", file_name="A.001", image_path="p/A"),
            _row(id_rvi="T2", file_name="B.001", image_path="p/B"),
        ]
        plans = list(
            plan_files(rows, _COLS, PlannerFilters(document_types=("T2",)), _BOUNDS),
        )
        assert len(plans) == 1
        assert plans[0].file_code == "B"

    def test_combined_filters_and_limit(self) -> None:
        rows = [
            _row(system="A", id_rvi="T1", file_name=f"F{i}.001", image_path=f"p/{i}")
            for i in range(10)
        ]
        plans = list(
            plan_files(
                rows,
                _COLS,
                PlannerFilters(systems=("A",), document_types=("T1",), limit=3),
                _BOUNDS,
            ),
        )
        assert len(plans) == 3


class TestDedup:
    def test_dedup_first_wins(self) -> None:
        rows = [
            _row(txn="T1", file_name="DOC.001", image_path="p/x", total_pages="2"),
            _row(txn="T2", file_name="DOC.001", image_path="p/x", total_pages="2"),
        ]
        plans = list(plan_files(rows, _COLS, PlannerFilters(), _BOUNDS))
        assert len(plans) == 1
        assert plans[0].pages == 2

    def test_dedup_page_conflict_warns_and_keeps_first(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        rows = [
            _row(txn="T1", file_name="DOC.001", image_path="p/x", total_pages="2"),
            _row(txn="T2", file_name="DOC.001", image_path="p/x", total_pages="5"),
        ]
        with caplog.at_level(logging.WARNING, logger="cmcourier.services.mock.planner"):
            plans = list(plan_files(rows, _COLS, PlannerFilters(), _BOUNDS))
        assert len(plans) == 1
        assert plans[0].pages == 2  # gana el primero
        assert any("conflict" in rec.message.lower() for rec in caplog.records)

    def test_dedup_after_path_normalization(self) -> None:
        # Dos filas cuyo `image_path` solo difiere en el estilo de
        # separador igual deben deduplicarse contra el `path` normalizado.
        rows = [
            _row(txn="T1", file_name="DOC.001", image_path="p/x"),
            _row(txn="T2", file_name="DOC.001", image_path=r"\p\x"),
        ]
        plans = list(plan_files(rows, _COLS, PlannerFilters(), _BOUNDS))
        assert len(plans) == 1
