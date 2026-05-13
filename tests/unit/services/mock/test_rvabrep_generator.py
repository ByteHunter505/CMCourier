"""Unit tests for ``cmcourier.services.mock.rvabrep_generator`` (039).

Each test runs against the streaming generator with a small ``rows``
count so the suite stays fast. Determinism is exercised by re-running
with the same seed and asserting byte-identical output.
"""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

import pytest

from cmcourier.domain.exceptions import ConfigurationError
from cmcourier.domain.models import parse_cymmdd
from cmcourier.services.mock.rvabrep_generator import (
    ImageMix,
    RvabrepGenSpec,
    generate_rvabrep,
)

pytestmark = pytest.mark.unit


_DEFAULT_POOL: tuple[str, ...] = ("FB01", "FF17", "CN01", "CJ02", "PT01")


def _spec(
    *,
    rows: int = 200,
    seed: int = 200,
    pool: tuple[str, ...] = _DEFAULT_POOL,
    image_mix: ImageMix | None = None,
    date_from: date = date(2024, 1, 1),
    date_to: date = date(2025, 12, 31),
    clients: int = 50,
    delete_rate: float = 0.05,
    cif_rate: float = 0.95,
) -> RvabrepGenSpec:
    if image_mix is None:
        image_mix = ImageMix()
    return RvabrepGenSpec(
        rows=rows,
        seed=seed,
        idrvi_pool=pool,
        image_mix=image_mix,
        date_from=date_from,
        date_to=date_to,
        clients=clients,
        delete_rate=delete_rate,
        cif_rate=cif_rate,
    )


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


class TestDeterminism:
    def test_same_seed_same_bytes(self, tmp_path: Path) -> None:
        a = tmp_path / "a.csv"
        b = tmp_path / "b.csv"
        generate_rvabrep(_spec(seed=42), a)
        generate_rvabrep(_spec(seed=42), b)
        assert a.read_bytes() == b.read_bytes()

    def test_different_seed_different_bytes(self, tmp_path: Path) -> None:
        a = tmp_path / "a.csv"
        b = tmp_path / "b.csv"
        generate_rvabrep(_spec(seed=42), a)
        generate_rvabrep(_spec(seed=43), b)
        assert a.read_bytes() != b.read_bytes()


class TestRowCount:
    def test_row_count_matches_spec(self, tmp_path: Path) -> None:
        out = tmp_path / "r.csv"
        written = generate_rvabrep(_spec(rows=137, seed=137), out)
        assert written == 137
        assert len(_read_rows(out)) == 137


class TestTxnUniqueness:
    def test_txn_num_unique(self, tmp_path: Path) -> None:
        out = tmp_path / "r.csv"
        generate_rvabrep(_spec(rows=5000, seed=5000), out)
        rows = _read_rows(out)
        txns = [r["ABAANB"] for r in rows]
        assert len(set(txns)) == len(txns) == 5000


class TestImageMix:
    def test_mix_within_tolerance(self, tmp_path: Path) -> None:
        out = tmp_path / "r.csv"
        generate_rvabrep(
            _spec(rows=5000, seed=5000, image_mix=ImageMix(tiff=60, pdf=20, jpeg=20)),
            out,
        )
        rows = _read_rows(out)
        n = len(rows)
        observed = {
            "B": sum(1 for r in rows if r["ABABST"] == "B") / n,
            "O": sum(1 for r in rows if r["ABABST"] == "O") / n,
            "C": sum(1 for r in rows if r["ABABST"] == "C") / n,
        }
        # ±3% tolerance at N=5000.
        assert abs(observed["B"] - 0.60) < 0.03
        assert abs(observed["O"] - 0.20) < 0.03
        assert abs(observed["C"] - 0.20) < 0.03


class TestIdrviPool:
    def test_every_idrvi_in_pool(self, tmp_path: Path) -> None:
        out = tmp_path / "r.csv"
        generate_rvabrep(_spec(rows=2000, seed=2000), out)
        rows = _read_rows(out)
        seen = {r["ABAHCD"] for r in rows}
        assert seen <= set(_DEFAULT_POOL)


class TestImageInvariants:
    def test_pdf_rows_have_pdf_extension_and_one_page(self, tmp_path: Path) -> None:
        out = tmp_path / "r.csv"
        generate_rvabrep(_spec(rows=1000, seed=1000), out)
        rows = _read_rows(out)
        for row in rows:
            if row["ABABST"] == "O":
                assert row["ABAJCD"].endswith(".PDF")
                assert row["ABABUN"] == "1"

    def test_paged_rows_have_numeric_extension(self, tmp_path: Path) -> None:
        out = tmp_path / "r.csv"
        generate_rvabrep(_spec(rows=1000, seed=1000), out)
        rows = _read_rows(out)
        for row in rows:
            if row["ABABST"] in ("B", "C"):
                assert row["ABAJCD"].endswith(".001")
                assert int(row["ABABUN"]) >= 1


class TestDateRange:
    def test_creation_date_in_range(self, tmp_path: Path) -> None:
        out = tmp_path / "r.csv"
        df = date(2025, 6, 1)
        dt = date(2025, 6, 30)
        generate_rvabrep(_spec(rows=300, seed=300, date_from=df, date_to=dt), out)
        rows = _read_rows(out)
        for row in rows:
            parsed = parse_cymmdd(row["ABAADT"]).date()
            assert df <= parsed <= dt

    def test_last_view_zero_or_after_creation(self, tmp_path: Path) -> None:
        out = tmp_path / "r.csv"
        generate_rvabrep(_spec(rows=500, seed=500), out)
        rows = _read_rows(out)
        for row in rows:
            if row["ABABDT"] == "0":
                continue
            created = parse_cymmdd(row["ABAADT"]).date()
            viewed = parse_cymmdd(row["ABABDT"]).date()
            assert viewed >= created


class TestInvariantFailure:
    def test_invalid_image_mix_rejected_by_spec(self) -> None:
        with pytest.raises(ConfigurationError):
            ImageMix(tiff=-1, pdf=20, jpeg=20)
        with pytest.raises(ConfigurationError):
            ImageMix(tiff=0, pdf=0, jpeg=0)

    def test_zero_rows_rejected(self) -> None:
        with pytest.raises(ConfigurationError):
            _spec(rows=0)

    def test_empty_pool_rejected(self) -> None:
        with pytest.raises(ConfigurationError):
            _spec(pool=())

    def test_inverted_date_range_rejected(self) -> None:
        with pytest.raises(ConfigurationError):
            _spec(date_from=date(2025, 12, 1), date_to=date(2025, 1, 1))
