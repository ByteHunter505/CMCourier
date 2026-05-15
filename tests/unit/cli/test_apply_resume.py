"""Tests unitarios para ``cmcourier.cli.app._apply_resume`` (044).

Ejercita cada camino de código de la detección de resume reescrita
sin levantar un `pipeline` real ni una DB de tracking — `patch`eamos
``SQLiteTrackingStore`` para que devuelva ``BatchDetails`` canónicos.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from cmcourier.cli import app as cli_app
from cmcourier.domain.models import BatchDetails

pytestmark = pytest.mark.unit


@dataclass
class _FakeBatchInfo:
    """Reemplazo mínimo para `BatchInfo` (solo lo que carga `BatchDetails`)."""

    batch_id: str = "B-TEST"


def _details(stage_counts: dict[str, dict[str, int]]) -> BatchDetails:
    """Construye un `BatchDetails` con el dict de pivot dado. Las
    etapas / outcomes faltantes caen a 0 para igualar la forma del
    `pivot` de producción."""
    full: dict[str, dict[str, int]] = {
        stage: dict.fromkeys(("DONE", "FAILED", "PENDING"), 0)
        for stage in ("S0", "S1", "S2", "S3", "S4", "S5")
    }
    for stage, outcomes in stage_counts.items():
        full[stage].update(outcomes)
    return BatchDetails(
        info=_FakeBatchInfo(),  # type: ignore[arg-type] — duck typing
        stage_counts=full,
        failed_records=(),
    )


class _FakeStore:
    """Sustituto mínimo para `SQLiteTrackingStore` usado por `_apply_resume`."""

    def __init__(self, details: BatchDetails | None) -> None:
        self._details = details
        self.closed = False

    def get_batch_details(self, batch_id: str) -> BatchDetails | None:  # noqa: ARG002
        return self._details

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def patch_store(monkeypatch: pytest.MonkeyPatch):
    """`Patch`ea el import tardío de `SQLiteTrackingStore` dentro de `_apply_resume`.

    La función hace ``from cmcourier.adapters.tracking import
    SQLiteTrackingStore`` de forma `lazy` — interceptamos ese
    atributo del módulo.
    """

    def _patch(details: BatchDetails | None):
        from cmcourier.adapters import tracking as _tracking

        monkeypatch.setattr(
            _tracking,
            "SQLiteTrackingStore",
            lambda _path: _FakeStore(details),
        )

    return _patch


@pytest.fixture
def fake_config():
    """Un objeto de config mínimo con el atributo `.tracking.db_path`
    que la función lee."""

    class _Tracking:
        db_path = "/tmp/unused.db"

    class _Config:
        tracking = _Tracking()

    return _Config()


class TestApplyResume044:
    """Cada test guía a `_apply_resume` por una rama de decisión."""

    def test_missing_batch_id_exits_2(self, fake_config: Any) -> None:
        with pytest.raises(SystemExit) as exc:
            cli_app._apply_resume(fake_config, None, 1)
        assert exc.value.code == 2

    def test_unknown_batch_id_exits_1(self, fake_config: Any, patch_store: Any) -> None:
        patch_store(None)  # el store devuelve None para el `batch`
        with pytest.raises(SystemExit) as exc:
            cli_app._apply_resume(fake_config, "MISSING", 1)
        assert exc.value.code == 1

    def test_truly_clean_exits_0(
        self, fake_config: Any, patch_store: Any, capsys: pytest.CaptureFixture[str]
    ) -> None:
        patch_store(_details({"S5": {"DONE": 824}}))
        with pytest.raises(SystemExit) as exc:
            cli_app._apply_resume(fake_config, "B-CLEAN", 1)
        assert exc.value.code == 0
        captured = capsys.readouterr()
        assert "Nothing to resume" in captured.out

    def test_failed_pending_priority(self, fake_config: Any, patch_store: Any) -> None:
        """FAILED/PENDING en la etapa N gana sobre DONE en una etapa
        posterior — el camino de retry en la misma etapa es más
        conservador que saltar hacia adelante.
        """
        patch_store(
            _details(
                {
                    "S3": {"FAILED": 5},
                    "S4": {"DONE": 100},
                }
            )
        )
        assert cli_app._apply_resume(fake_config, "B-MIX", 1) == 3

    def test_s4_done_gap_resolves_to_5(self, fake_config: Any, patch_store: Any) -> None:
        """Escenario §H.1 de staging: matar a mitad de S5 deja 543
        docs en S4_DONE (esperando que un `worker` los reclame) + 281
        ya en S5_DONE. Antes de 044 esto se veía 'clean' → 0 docs
        procesados. Post-044 la detección de `gap` resuelve a
        from_stage=5.
        """
        patch_store(
            _details(
                {
                    "S4": {"DONE": 543},
                    "S5": {"DONE": 281},
                }
            )
        )
        assert cli_app._apply_resume(fake_config, "B-KILLED", 1) == 5

    def test_s2_done_gap_resolves_to_3(self, fake_config: Any, patch_store: Any) -> None:
        """Caso simétrico: matar más temprano en el `pipeline`."""
        patch_store(_details({"S2": {"DONE": 500}}))
        assert cli_app._apply_resume(fake_config, "B-EARLY", 1) == 3

    def test_explicit_from_stage_beats_clean(self, fake_config: Any, patch_store: Any) -> None:
        """`escape hatch` del operador: `--resume --batch-id X
        --from-stage N` cuando el `batch` PARECE estar `clean`. Antes
        de 044 el early-exit `is clean` mataba el override explícito.
        Post-044 `explicit-from-stage` gana incondicionalmente
        mientras el `batch` exista.
        """
        patch_store(_details({"S5": {"DONE": 824}}))
        assert cli_app._apply_resume(fake_config, "B-REPLAY", 5) == 5

    def test_explicit_from_stage_beats_gap_detection(
        self, fake_config: Any, patch_store: Any
    ) -> None:
        """Si el override explícito está seteado, la auto-detección de
        `gap` no corre — confiamos en el operador."""
        patch_store(
            _details(
                {
                    "S4": {"DONE": 543},
                    "S5": {"DONE": 281},
                }
            )
        )
        assert cli_app._apply_resume(fake_config, "B-OVERRIDE", 3) == 3

    def test_quiet_suppresses_clean_message(
        self,
        fake_config: Any,
        patch_store: Any,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        patch_store(_details({"S5": {"DONE": 100}}))
        with pytest.raises(SystemExit) as exc:
            cli_app._apply_resume(fake_config, "B-CLEAN", 1, quiet=True)
        assert exc.value.code == 0
        captured = capsys.readouterr()
        assert "Nothing to resume" not in captured.out
