"""Unit tests for the polymorphic Trigger hierarchy (046 Phase 1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from cmcourier.domain.models import (
    ClientTrigger,
    LocalScanTrigger,
    RvabrepRowTrigger,
    Trigger,
    TriggerRecord,
)

pytestmark = pytest.mark.unit


class TestBackwardCompat046:
    """``TriggerRecord`` must keep pointing at ``ClientTrigger`` so every
    pre-046 import (csv strategy, single-doc CLI, tracking adapter,
    integration tests) compiles unchanged."""

    def test_alias_is_identity(self) -> None:
        assert TriggerRecord is ClientTrigger

    def test_legacy_construction_still_works(self) -> None:
        # The pre-046 shape: positional or named, all three fields.
        t = TriggerRecord(shortname="ACME-001", cif="123456", system_id="PROD")
        assert isinstance(t, ClientTrigger)
        assert isinstance(t, Trigger)


class TestClientTrigger:
    def test_validation_rejects_empty_shortname(self) -> None:
        with pytest.raises(ValueError, match="shortname"):
            ClientTrigger(shortname="", cif="x", system_id="1")

    def test_validation_rejects_empty_system_id(self) -> None:
        with pytest.raises(ValueError, match="system_id"):
            ClientTrigger(shortname="A", cif="x", system_id="")

    def test_cif_may_be_none(self) -> None:
        # CIF self-healing (REBIRTH §6.5) needs cif=None as a first-class state.
        t = ClientTrigger(shortname="A", cif=None, system_id="1")
        assert t.cif is None

    def test_audit_row_returns_literal_fields(self) -> None:
        t = ClientTrigger(shortname="A", cif="42", system_id="PROD")
        assert t.audit_row() == {"shortname": "A", "cif": "42", "system_id": "PROD"}

    def test_audit_row_preserves_none_cif(self) -> None:
        t = ClientTrigger(shortname="A", cif=None, system_id="PROD")
        assert t.audit_row() == {"shortname": "A", "cif": None, "system_id": "PROD"}


class TestRvabrepRowTrigger:
    def test_audit_row_projects_from_rvabrep_columns(self) -> None:
        row = {
            "ABABCD": "ACME-001",  # shortname
            "ABACCD": "987654",  # cif
            "ABAACD": "PROD",  # system_id
            "ABAJCD": "FILE001.PDF",  # file_name (not in audit)
            "extra_col": "irrelevant",
        }
        t = RvabrepRowTrigger(row=row)
        assert t.audit_row() == {
            "shortname": "ACME-001",
            "cif": "987654",
            "system_id": "PROD",
        }

    def test_audit_row_normalizes_blank_cif_to_none(self) -> None:
        """RVABREP rows often have whitespace-only CIF for clients whose CIF
        is later self-healed by S3. The audit row should report None, not
        the raw whitespace."""
        t = RvabrepRowTrigger(row={"ABABCD": "X", "ABACCD": "   ", "ABAACD": "1"})
        assert t.audit_row()["cif"] is None

    def test_audit_row_handles_missing_columns(self) -> None:
        # A row that doesn't even have the column key (e.g. AS400 SQL projection
        # over a different table) returns None for missing slots.
        t = RvabrepRowTrigger(row={"ABABCD": "X"})
        assert t.audit_row() == {"shortname": "X", "cif": None, "system_id": None}


class TestLocalScanTrigger:
    def test_audit_row_projects_from_row(self) -> None:
        row = {"ABABCD": "PEDRO99", "ABACCD": "555111", "ABAACD": "3"}
        t = LocalScanTrigger(file_path=Path("/tmp/scan/foo.001"), row=row)
        assert t.audit_row() == {
            "shortname": "PEDRO99",
            "cif": "555111",
            "system_id": "3",
        }

    def test_file_path_preserved(self) -> None:
        p = Path("/tmp/scan/AAA.PDF")
        t = LocalScanTrigger(file_path=p, row={"ABABCD": "X", "ABAACD": "1"})
        assert t.file_path == p


class TestTriggerBaseIsAbstract:
    def test_cannot_instantiate_abstract_base(self) -> None:
        with pytest.raises(TypeError):
            Trigger()  # type: ignore[abstract]
