"""Unit tests for :class:`cmcourier.services.indexing.IndexingService`.

Exercises the service end-to-end against a real :class:`TabularDataSource`
over a CSV fixture (Constitution Principle VI: no IDataSource mocks). A
small :class:`_CallCountingSource` wraps the adapter to assert call counts
for the batched-lookup performance requirements (NFR-002).
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from cmcourier.adapters.sources import TabularDataSource
from cmcourier.domain.exceptions import (
    IndexingError,
    RVABREPDeletedError,
    RVABREPNotFoundError,
)
from cmcourier.domain.models import TriggerRecord
from cmcourier.domain.ports import IDataSource
from cmcourier.services.indexing import IndexingColumnsConfig, IndexingService

pytestmark = pytest.mark.unit

_FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "services"
_SAMPLE_CSV = _FIXTURES / "rvabrep_index_sample.csv"


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


class _CallCountingSource(IDataSource):
    """Wraps a real IDataSource and counts adapter invocations."""

    def __init__(self, inner: IDataSource) -> None:
        self.inner = inner
        self.get_by_fields_calls = 0
        self.get_by_fields_in_calls = 0

    def get_all(self) -> Iterator[dict[str, Any]]:
        yield from self.inner.get_all()

    def get_by_fields(self, filters: Mapping[str, Any]) -> list[dict[str, Any]]:
        self.get_by_fields_calls += 1
        return self.inner.get_by_fields(filters)

    def query(self, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
        return self.inner.query(sql, params)

    def query_stream(self, sql: str, params: list[Any] | None = None) -> Iterator[dict[str, Any]]:
        return self.inner.query_stream(sql, params)

    def get_by_fields_in(
        self,
        field: str,
        values: list[Any],
        fixed_filters: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        self.get_by_fields_in_calls += 1
        return self.inner.get_by_fields_in(field, values, fixed_filters)

    def count(self) -> int:
        return self.inner.count()

    def close(self) -> None:
        self.inner.close()


def _friendly_config() -> IndexingColumnsConfig:
    """Column map matching the friendly names in rvabrep_index_sample.csv."""
    return IndexingColumnsConfig(
        shortname_column="shortname",
        system_id_column="system_id",
        delete_code_column="delete_code",
        txn_num_column="txn_num",
        index2_column="index2",
        index3_column="index3",
        index4_column="index4",
        index5_column="index5",
        index6_column="index6",
        index7_column="index7",
        image_type_column="image_type",
        image_path_column="image_path",
        file_name_column="file_name",
        creation_date_column="creation_date",
        last_view_date_column="last_view_date",
        total_pages_column="total_pages",
    )


def _trigger(shortname: str, system_id: str = "1", cif: str | None = None) -> TriggerRecord:
    return TriggerRecord(shortname=shortname, cif=cif, system_id=system_id)


@pytest.fixture
def source() -> Iterator[TabularDataSource]:
    src = TabularDataSource(_SAMPLE_CSV)
    yield src
    src.close()


@pytest.fixture
def service(source: TabularDataSource) -> IndexingService:
    return IndexingService(source, _friendly_config())


# ---------------------------------------------------------------------------
# Group 1 — Construction & defaults
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_construction_does_not_query(self, source: TabularDataSource) -> None:
        counting = _CallCountingSource(source)
        IndexingService(counting, _friendly_config())
        assert counting.get_by_fields_calls == 0
        assert counting.get_by_fields_in_calls == 0

    def test_default_column_config_matches_rebirth_section_3_2(self) -> None:
        cfg = IndexingColumnsConfig()
        # Filter / lookup columns (REBIRTH §3.2).
        assert cfg.shortname_column == "ABABCD"
        assert cfg.system_id_column == "ABAACD"
        assert cfg.txn_num_column == "ABAANB"
        assert cfg.delete_code_column == "ABACST"
        # Type-join column.
        assert cfg.index7_column == "ABAHCD"
        # File columns.
        assert cfg.image_type_column == "ABABST"
        assert cfg.file_name_column == "ABAJCD"
        # Date / numeric columns.
        assert cfg.creation_date_column == "ABAADT"
        assert cfg.last_view_date_column == "ABABDT"
        assert cfg.total_pages_column == "ABABUN"

    def test_config_is_frozen(self) -> None:
        import dataclasses

        cfg = IndexingColumnsConfig()
        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.shortname_column = "OTHER"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Group 2 — Single-trigger lookup
# ---------------------------------------------------------------------------


class TestSingleTriggerLookup:
    def test_vanilla_multi_match(self, service: IndexingService) -> None:
        # JUANPEREZ01 system 1 has 3 active rows.
        docs = service.find_documents(_trigger("JUANPEREZ01"))
        assert len(docs) == 3
        assert {d.txn_num for d in docs} == {"TXN0000001", "TXN0000002", "TXN0000003"}

    def test_not_found_raises(self, service: IndexingService) -> None:
        with pytest.raises(RVABREPNotFoundError) as ei:
            service.find_documents(_trigger("DOES_NOT_EXIST"))
        assert ei.value.context["shortname"] == "DOES_NOT_EXIST"
        assert ei.value.context["system_id"] == "1"

    def test_all_deleted_raises(self, service: IndexingService) -> None:
        # MARIAGOMEZ02 system 1 has 2 rows, both deleted.
        with pytest.raises(RVABREPDeletedError) as ei:
            service.find_documents(_trigger("MARIAGOMEZ02"))
        assert ei.value.context["deleted_count"] == 2

    def test_mixed_deleted_returns_active_only(self, service: IndexingService) -> None:
        # PEPELOPEZ03 system 1 has 1 active + 2 deleted.
        docs = service.find_documents(_trigger("PEPELOPEZ03"))
        assert len(docs) == 1
        assert docs[0].txn_num == "TXN0000006"
        assert not docs[0].is_deleted

    def test_cif_does_not_filter(self, service: IndexingService) -> None:
        # JUANPEREZ01 with cif=None returns 3 docs.
        none_cif_docs = service.find_documents(_trigger("JUANPEREZ01", cif=None))
        # JUANPEREZ01 with cif="123456" returns the SAME 3 docs (CIF ignored).
        cif_docs = service.find_documents(_trigger("JUANPEREZ01", cif="123456"))
        # Even with a CIF that does not appear on any row.
        wrong_cif_docs = service.find_documents(_trigger("JUANPEREZ01", cif="999999"))
        assert len(none_cif_docs) == 3
        assert len(cif_docs) == 3
        assert len(wrong_cif_docs) == 3


# ---------------------------------------------------------------------------
# Group 3 — Duplicate txn_num handling
# ---------------------------------------------------------------------------


class TestDuplicateHandling:
    def test_duplicate_txn_num_warns_and_drops(
        self,
        service: IndexingService,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        # DUPECLIENT has 2 rows both with txn_num='TXN0000009'.
        with caplog.at_level(logging.WARNING, logger="cmcourier.services.indexing"):
            docs = service.find_documents(_trigger("DUPECLIENT"))
        assert len(docs) == 1
        assert docs[0].txn_num == "TXN0000009"
        # WARNING emitted, names shortname and duplicate count.
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any(
            "DUPECLIENT" in r.getMessage() or r.__dict__.get("shortname") == "DUPECLIENT"
            for r in warnings
        )

    def test_duplicate_does_not_raise(self, service: IndexingService) -> None:
        # Pure functional assertion — must not raise.
        docs = service.find_documents(_trigger("DUPECLIENT"))
        assert isinstance(docs, list)


# ---------------------------------------------------------------------------
# Group 4 — Batched lookup
# ---------------------------------------------------------------------------


class TestBatchedLookup:
    def test_batch_size_drives_call_count(self, source: TabularDataSource) -> None:
        counting = _CallCountingSource(source)
        service = IndexingService(counting, _friendly_config(), batch_size=2)
        triggers = [
            _trigger("JUANPEREZ01"),
            _trigger("PEPELOPEZ03"),
            _trigger("MULTISYS01", system_id="5"),
            _trigger("ALONECLIENT"),
            _trigger("EDGEDATES"),
        ]
        results = list(service.find_documents_batch(triggers))
        # 5 triggers / batch_size=2 → ceil(5/2) = 3 calls.
        assert counting.get_by_fields_in_calls == 3
        assert len(results) == 5

    def test_missing_trigger_yields_empty_list(self, service: IndexingService) -> None:
        triggers = [
            _trigger("JUANPEREZ01"),
            _trigger("NO_SUCH_CLIENT"),
            _trigger("ALONECLIENT"),
        ]
        results = list(service.find_documents_batch(triggers))
        assert len(results) == 3
        assert results[0][0].shortname == "JUANPEREZ01"
        assert len(results[0][1]) == 3
        assert results[1][0].shortname == "NO_SUCH_CLIENT"
        assert results[1][1] == []
        assert results[2][0].shortname == "ALONECLIENT"
        assert len(results[2][1]) == 1

    def test_same_shortname_different_system_id_isolated(self, service: IndexingService) -> None:
        # MULTISYS01 has 1 row under system 1 and 1 row under system 5.
        triggers = [
            _trigger("MULTISYS01", system_id="1"),
            _trigger("MULTISYS01", system_id="5"),
        ]
        results = list(service.find_documents_batch(triggers))
        assert len(results) == 2
        _, docs_sys1 = results[0]
        _, docs_sys5 = results[1]
        assert len(docs_sys1) == 1
        assert docs_sys1[0].txn_num == "TXN0000010"
        assert len(docs_sys5) == 1
        assert docs_sys5[0].txn_num == "TXN0000011"

    def test_input_order_preserved(self, service: IndexingService) -> None:
        triggers = [
            _trigger("ALONECLIENT"),
            _trigger("JUANPEREZ01"),
            _trigger("PEPELOPEZ03"),
        ]
        order = [t.shortname for t, _ in service.find_documents_batch(triggers)]
        assert order == ["ALONECLIENT", "JUANPEREZ01", "PEPELOPEZ03"]

    def test_repeated_trigger_yielded_twice(self, service: IndexingService) -> None:
        triggers = [
            _trigger("ALONECLIENT"),
            _trigger("ALONECLIENT"),
        ]
        results = list(service.find_documents_batch(triggers))
        assert len(results) == 2
        assert len(results[0][1]) == 1
        assert len(results[1][1]) == 1


# ---------------------------------------------------------------------------
# Group 5 — Row coercion
# ---------------------------------------------------------------------------


class TestRowCoercion:
    def test_cymmdd_round_trip(self, service: IndexingService) -> None:
        # JUANPEREZ01's first row has creation_date='1251117' and last_view='1251018'.
        docs = service.find_documents(_trigger("JUANPEREZ01"))
        first = next(d for d in docs if d.txn_num == "TXN0000001")
        assert first.creation_date == datetime(2025, 11, 17)
        assert first.last_view_date == datetime(2025, 10, 18)

    def test_last_view_date_zero_becomes_none(self, service: IndexingService) -> None:
        # JUANPEREZ01's PDF row has last_view_date='0'.
        docs = service.find_documents(_trigger("JUANPEREZ01"))
        pdf = next(d for d in docs if d.txn_num == "TXN0000002")
        assert pdf.last_view_date is None

    def test_last_view_date_empty_becomes_none(self, service: IndexingService) -> None:
        # EDGEDATES has last_view_date='' (empty cell).
        docs = service.find_documents(_trigger("EDGEDATES"))
        assert docs[0].last_view_date is None

    def test_total_pages_is_int(self, service: IndexingService) -> None:
        # JUANPEREZ01's first row has total_pages='540'.
        docs = service.find_documents(_trigger("JUANPEREZ01"))
        first = next(d for d in docs if d.txn_num == "TXN0000001")
        assert isinstance(first.total_pages, int)
        assert first.total_pages == 540


# ---------------------------------------------------------------------------
# Group 6 — Error wrapping
# ---------------------------------------------------------------------------


class _BrokenSource(IDataSource):
    """An IDataSource whose methods raise a synthetic RuntimeError."""

    def get_all(self) -> Iterator[dict[str, Any]]:
        raise RuntimeError("synthetic adapter failure")
        yield  # pragma: no cover  # unreachable, makes the type checker happy

    def get_by_fields(self, filters: Mapping[str, Any]) -> list[dict[str, Any]]:
        raise RuntimeError("synthetic adapter failure")

    def query(self, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
        raise RuntimeError("synthetic adapter failure")

    def query_stream(self, sql: str, params: list[Any] | None = None) -> Iterator[dict[str, Any]]:
        raise RuntimeError("synthetic adapter failure")
        yield  # pragma: no cover

    def get_by_fields_in(
        self,
        field: str,
        values: list[Any],
        fixed_filters: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        raise RuntimeError("synthetic adapter failure")

    def count(self) -> int:
        return 0

    def close(self) -> None:
        return None


class TestErrorWrapping:
    def test_adapter_exception_becomes_indexing_error(self) -> None:
        service = IndexingService(_BrokenSource(), _friendly_config())
        with pytest.raises(IndexingError) as ei:
            service.find_documents(_trigger("JUANPEREZ01"))
        assert isinstance(ei.value.__cause__, RuntimeError)
        assert ei.value.context["shortname"] == "JUANPEREZ01"
        assert ei.value.context["system_id"] == "1"

    def test_batched_adapter_exception_becomes_indexing_error(self) -> None:
        service = IndexingService(_BrokenSource(), _friendly_config())
        with pytest.raises(IndexingError):
            list(service.find_documents_batch([_trigger("JUANPEREZ01")]))


# ---------------------------------------------------------------------------
# Group 7 — Logging discipline (Constitution VIII)
# ---------------------------------------------------------------------------


class TestLoggingDiscipline:
    def test_duplicate_warning_does_not_log_index_values(
        self,
        service: IndexingService,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        with caplog.at_level(logging.WARNING, logger="cmcourier.services.indexing"):
            service.find_documents(_trigger("DUPECLIENT"))
        # CIF value of DUPECLIENT in the fixture is '456789'. It must NOT
        # appear in any log message.
        for record in caplog.records:
            assert "456789" not in record.getMessage()
            assert "456789" not in str(record.__dict__.get("extra", ""))
