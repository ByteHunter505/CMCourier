"""Synthetic RVABREP CSV generator (039).

Streams a deterministic RVABREP CSV with the column shape documented
in REBIRTH §3.2. One ``random.Random(seed)`` drives every choice so
the same seed always produces byte-identical output. The output is
consumed by the existing ``cmcourier mock generate`` (031) which
materializes the physical files on disk.

Constitution:
* Principle I — service module, stdlib + ``cmcourier.domain`` only.
* Principle IV — streaming write (one row at a time via ``csv.writer``);
  memory stays bounded for ``rows=1_000_000``.
* Principle VI — pure functions per pick; ``random.Random`` injected.
"""

from __future__ import annotations

__all__ = [
    "ImageMix",
    "RvabrepGenSpec",
    "generate_rvabrep",
]

import csv
import random
import string
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from cmcourier.domain.exceptions import ConfigurationError
from cmcourier.domain.models import parse_cymmdd

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


# Output column order — REBIRTH §3.2 ABA codes. Matches
# IndexingColumnsModel defaults so the output is consumed by
# ``mock generate`` and every downstream pipeline without a config
# override.
_HEADER: tuple[str, ...] = (
    "ABABCD",  # shortname / index1
    "ABAACD",  # system_id / system_code
    "ABAANB",  # txn_num
    "ABACST",  # delete_code
    "ABACCD",  # index2 / CIF
    "ABADCD",  # index3
    "ABAECD",  # index4
    "ABAFCD",  # index5
    "ABAGCD",  # index6
    "ABAHCD",  # index7 / IDRVI
    "ABABST",  # image_type
    "ABAICD",  # image_path
    "ABAJCD",  # file_name
    "ABAADT",  # creation_date
    "ABABDT",  # last_view_date
    "ABABUN",  # total_pages
)


# REBIRTH §3.2 image-type physical codes.
_IMAGE_TYPE_CODE: dict[str, str] = {
    "tiff": "B",
    "pdf": "O",
    "jpeg": "C",
}


# File-name prefix letter per physical image-type code.
_FILE_PREFIX: dict[str, tuple[str, ...]] = {
    "B": ("D", "M"),
    "C": ("C",),
    "O": ("0",),
}


# Lexicon for shortname generation. Small, banking-flavored, deterministic.
_NAME_LEXICON: tuple[str, ...] = (
    "JUAN",
    "MARIA",
    "PEDRO",
    "ANA",
    "CARLOS",
    "ELENA",
    "LUIS",
    "ROSA",
    "MIGUEL",
    "SOFIA",
    "EMPRESA",
    "TARJETA",
    "CUENTA",
    "PRESTAMO",
    "AFILIADO",
)


# system_id distribution observed in RVILIB_RVABREP.xlsx + REBIRTH §3.2.
_SYSTEM_ID_WEIGHTS: tuple[tuple[str, float], ...] = (
    ("1", 0.70),
    ("5", 0.15),
    ("2", 0.10),
    ("3", 0.05),
)


# Base32 alphabet (RFC 4648, upper) for txn_num bodies.
_BASE32: str = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"


@dataclass(frozen=True, slots=True)
class ImageMix:
    """Image-type proportions. Values must be non-negative; renormalized
    internally so they sum to 1.0."""

    tiff: float = 0.60
    pdf: float = 0.20
    jpeg: float = 0.20

    def __post_init__(self) -> None:
        if min(self.tiff, self.pdf, self.jpeg) < 0:
            raise ConfigurationError("ImageMix weights must be non-negative")
        if self.tiff + self.pdf + self.jpeg == 0:
            raise ConfigurationError("ImageMix weights cannot all be zero")

    def normalized(self) -> tuple[tuple[str, float], ...]:
        total = self.tiff + self.pdf + self.jpeg
        return (
            ("tiff", self.tiff / total),
            ("pdf", self.pdf / total),
            ("jpeg", self.jpeg / total),
        )


@dataclass(frozen=True, slots=True)
class RvabrepGenSpec:
    """Frozen spec consumed by :func:`generate_rvabrep`.

    ``idrvi_pool`` carries the caller-provided IDRVI set (deduped, ordered).
    Distribution within the pool follows a Zipf-style weighting — the first
    element receives the largest share, with rank-based decay.
    """

    rows: int
    seed: int
    idrvi_pool: tuple[str, ...]
    image_mix: ImageMix = ImageMix()
    date_from: date = date(2024, 1, 1)
    date_to: date = date(2025, 12, 31)
    clients: int = 5000
    delete_rate: float = 0.05
    cif_rate: float = 0.95
    zipf_alpha: float = 1.07

    def __post_init__(self) -> None:
        if self.rows <= 0:
            raise ConfigurationError("RvabrepGenSpec.rows must be > 0")
        if not self.idrvi_pool:
            raise ConfigurationError("RvabrepGenSpec.idrvi_pool must be non-empty")
        if self.clients <= 0:
            raise ConfigurationError("RvabrepGenSpec.clients must be > 0")
        if not 0.0 <= self.delete_rate <= 1.0:
            raise ConfigurationError("RvabrepGenSpec.delete_rate must be in [0, 1]")
        if not 0.0 <= self.cif_rate <= 1.0:
            raise ConfigurationError("RvabrepGenSpec.cif_rate must be in [0, 1]")
        if self.date_to < self.date_from:
            raise ConfigurationError("RvabrepGenSpec: date_to must be >= date_from")


# ---------------------------------------------------------------------------
# Per-column pickers
# ---------------------------------------------------------------------------


def _pick_image_type(rng: random.Random, mix: ImageMix) -> str:
    """Return the physical image-type code (B/O/C)."""
    choices = mix.normalized()
    r = rng.random()
    cum = 0.0
    for kind, weight in choices:
        cum += weight
        if r < cum:
            return _IMAGE_TYPE_CODE[kind]
    return _IMAGE_TYPE_CODE[choices[-1][0]]


def _pick_idrvi(rng: random.Random, pool: tuple[str, ...], alpha: float) -> str:
    """Zipf-weighted draw from the IDRVI pool."""
    weights = [1.0 / ((i + 1) ** alpha) for i in range(len(pool))]
    return rng.choices(pool, weights=weights, k=1)[0]


def _pick_system_id(rng: random.Random) -> str:
    r = rng.random()
    cum = 0.0
    for sid, weight in _SYSTEM_ID_WEIGHTS:
        cum += weight
        if r < cum:
            return sid
    return _SYSTEM_ID_WEIGHTS[-1][0]


def _pick_txn_num(idx: int) -> str:
    """Deterministic global-unique txn_num from a row index.

    ``T`` prefix + 6 base32 chars. 32^6 = 1,073,741,824 distinct values.
    """
    n = idx
    body = []
    for _ in range(6):
        body.append(_BASE32[n & 0x1F])
        n >>= 5
    return "T" + "".join(reversed(body))


def _pick_creation_date(rng: random.Random, date_from: date, date_to: date) -> date:
    span_days = (date_to - date_from).days
    if span_days == 0:
        return date_from
    return date_from + timedelta(days=rng.randint(0, span_days))


def _pick_last_view_date(rng: random.Random, creation: date, date_to: date) -> str:
    """``"0"`` with probability 0.9, otherwise CYYMMDD ≥ creation_date."""
    if rng.random() < 0.9:
        return "0"
    span_days = (date_to - creation).days
    if span_days <= 0:
        return _to_cymmdd(creation)
    return _to_cymmdd(creation + timedelta(days=rng.randint(0, span_days)))


def _pick_total_pages(rng: random.Random, image_code: str) -> int:
    if image_code == "O":
        return 1
    r = rng.random()
    if r < 0.70:
        return rng.randint(1, 5)
    if r < 0.95:
        return rng.randint(6, 50)
    return rng.randint(51, 540)


def _pick_file_name(rng: random.Random, image_code: str) -> str:
    prefix = rng.choice(_FILE_PREFIX[image_code])
    body = "".join(rng.choices(string.ascii_uppercase + string.digits, k=7))
    if image_code == "O":
        return f"{prefix}{body}.PDF"
    return f"{prefix}{body}.001"


def _pick_image_path(creation: date) -> str:
    return f"PROD/{creation.year:04d}/{creation.month:02d}/{creation.day:02d}"


def _pick_cif(rng: random.Random) -> str:
    return f"{rng.randint(100000, 999999):06d}"


def _pick_client(rng: random.Random, client_idx: int) -> str:
    """Build a deterministic shortname from a client index.

    Uses the lexicon + the index modulo so the same client_idx always
    yields the same shortname. Two-digit numeric suffix.
    """
    base = _NAME_LEXICON[client_idx % len(_NAME_LEXICON)]
    suffix = (client_idx // len(_NAME_LEXICON)) % 100
    return f"{base}{suffix:02d}"


def _to_cymmdd(d: date) -> str:
    """Render a :class:`datetime.date` as the CYYMMDD string."""
    century_flag = 1 if d.year >= 2000 else 0
    yy = d.year - (2000 if century_flag else 1900)
    return f"{century_flag}{yy:02d}{d.month:02d}{d.day:02d}"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def generate_rvabrep(spec: RvabrepGenSpec, out_path: Path) -> int:
    """Stream a synthetic RVABREP CSV to *out_path*. Return rows written.

    The output is opened with ``newline=""`` so :mod:`csv` controls line
    endings (cross-platform deterministic).
    """
    rng = random.Random(spec.seed)
    # Pre-pick the CIF and the per-client cardinality so the same client
    # always carries the same CIF in the output.
    client_cifs: list[str] = []
    for ci in range(spec.clients):
        ci_rng = random.Random(spec.seed * 10000 + ci)
        client_cifs.append(_pick_cif(ci_rng) if ci_rng.random() < spec.cif_rate else "")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with out_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(_HEADER)
        for idx in range(spec.rows):
            row = _build_row(idx, spec, rng, client_cifs)
            _validate_row(row, idx)
            writer.writerow(row)
            written += 1
    return written


def _build_row(
    idx: int,
    spec: RvabrepGenSpec,
    rng: random.Random,
    client_cifs: list[str],
) -> tuple[str, ...]:
    client_idx = rng.randint(0, spec.clients - 1)
    shortname = _pick_client(rng, client_idx)
    cif = client_cifs[client_idx]
    system_id = _pick_system_id(rng)
    txn_num = _pick_txn_num(idx)
    delete_code = "D" if rng.random() < spec.delete_rate else ""
    idrvi = _pick_idrvi(rng, spec.idrvi_pool, spec.zipf_alpha)
    image_code = _pick_image_type(rng, spec.image_mix)
    creation = _pick_creation_date(rng, spec.date_from, spec.date_to)
    image_path = _pick_image_path(creation)
    file_name = _pick_file_name(rng, image_code)
    creation_str = _to_cymmdd(creation)
    last_view_str = _pick_last_view_date(rng, creation, spec.date_to)
    total_pages = _pick_total_pages(rng, image_code)
    return (
        shortname,
        system_id,
        txn_num,
        delete_code,
        cif,  # index2
        "",  # index3
        "",  # index4
        "",  # index5
        "",  # index6
        idrvi,  # index7
        image_code,
        image_path,
        file_name,
        creation_str,
        last_view_str,
        str(total_pages),
    )


def _validate_row(row: tuple[str, ...], idx: int) -> None:
    """Cheap invariant check — raises ``ConfigurationError`` on failure."""
    (
        shortname,
        _system_id,
        txn_num,
        _delete_code,
        _cif,
        _i3,
        _i4,
        _i5,
        _i6,
        idrvi,
        image_code,
        _image_path,
        file_name,
        creation_str,
        last_view_str,
        total_pages_str,
    ) = row
    if not shortname:
        raise ConfigurationError("empty shortname", row_idx=str(idx))
    if not txn_num.startswith("T"):
        raise ConfigurationError(
            "txn_num must start with 'T'",
            row_idx=str(idx),
            txn_num=txn_num,
        )
    if not idrvi:
        raise ConfigurationError("empty idrvi", row_idx=str(idx))
    if image_code not in _FILE_PREFIX:
        raise ConfigurationError(
            "unknown image_code",
            row_idx=str(idx),
            image_code=image_code,
        )
    if image_code == "O" and not file_name.endswith(".PDF"):
        raise ConfigurationError(
            "PDF row must have .PDF extension",
            row_idx=str(idx),
            file_name=file_name,
        )
    if image_code != "O" and not file_name.endswith(".001"):
        raise ConfigurationError(
            "paged row must have numeric extension",
            row_idx=str(idx),
            file_name=file_name,
        )
    try:
        total_pages = int(total_pages_str)
    except ValueError as exc:
        raise ConfigurationError(
            "total_pages must be integer",
            row_idx=str(idx),
            total_pages=total_pages_str,
        ) from exc
    if image_code == "O" and total_pages != 1:
        raise ConfigurationError(
            "PDF row must have total_pages == 1",
            row_idx=str(idx),
            total_pages=str(total_pages),
        )
    # Date parse — raises ValueError on bad CYYMMDD.
    try:
        parse_cymmdd(creation_str)
    except ValueError as exc:
        raise ConfigurationError(
            "invalid creation_date CYYMMDD",
            row_idx=str(idx),
            creation_date=creation_str,
        ) from exc
    if last_view_str != "0":
        try:
            parse_cymmdd(last_view_str)
        except ValueError as exc:
            raise ConfigurationError(
                "invalid last_view_date CYYMMDD",
                row_idx=str(idx),
                last_view_date=last_view_str,
            ) from exc
