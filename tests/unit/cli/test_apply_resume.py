"""Unit tests for ``cmcourier.cli.app._apply_resume`` (044).

Exercises every code path in the rewritten resume detection without
spinning up a real pipeline or tracking DB — we patch
``SQLiteTrackingStore`` to return canned ``BatchDetails``.
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
    """Minimal stand-in for BatchInfo (only what BatchDetails carries)."""

    batch_id: str = "B-TEST"


def _details(stage_counts: dict[str, dict[str, int]]) -> BatchDetails:
    """Build a BatchDetails with the given pivot dict. Missing stages /
    outcomes fall back to 0 to match the production pivot shape."""
    full: dict[str, dict[str, int]] = {
        stage: dict.fromkeys(("DONE", "FAILED", "PENDING"), 0)
        for stage in ("S0", "S1", "S2", "S3", "S4", "S5")
    }
    for stage, outcomes in stage_counts.items():
        full[stage].update(outcomes)
    return BatchDetails(
        info=_FakeBatchInfo(),  # type: ignore[arg-type] — duck typed
        stage_counts=full,
        failed_records=(),
    )


class _FakeStore:
    """Minimal substitute for SQLiteTrackingStore used by _apply_resume."""

    def __init__(self, details: BatchDetails | None) -> None:
        self._details = details
        self.closed = False

    def get_batch_details(self, batch_id: str) -> BatchDetails | None:  # noqa: ARG002
        return self._details

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def patch_store(monkeypatch: pytest.MonkeyPatch):
    """Patch the late import of SQLiteTrackingStore inside _apply_resume.

    The function does ``from cmcourier.adapters.tracking import
    SQLiteTrackingStore`` lazily — we intercept that module attribute.
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
    """A minimal config object with the .tracking.db_path attribute the
    function reads."""

    class _Tracking:
        db_path = "/tmp/unused.db"

    class _Config:
        tracking = _Tracking()

    return _Config()


class TestApplyResume044:
    """Each test drives _apply_resume through one decision branch."""

    def test_missing_batch_id_exits_2(self, fake_config: Any) -> None:
        with pytest.raises(SystemExit) as exc:
            cli_app._apply_resume(fake_config, None, 1)
        assert exc.value.code == 2

    def test_unknown_batch_id_exits_1(self, fake_config: Any, patch_store: Any) -> None:
        patch_store(None)  # store returns None for the batch
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
        """FAILED/PENDING at stage N wins over DONE at later stage —
        same-stage retry path is more conservative than skipping ahead.
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
        """The §H.1 staging scenario: kill mid-S5 leaves 543 docs at
        S4_DONE (waiting for a worker to claim them) + 281 already at
        S5_DONE. Pre-044 this looked 'clean' → 0 docs processed.
        Post-044 the gap detection resolves to from_stage=5.
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
        """Symmetrical case: kill earlier in the pipeline."""
        patch_store(_details({"S2": {"DONE": 500}}))
        assert cli_app._apply_resume(fake_config, "B-EARLY", 1) == 3

    def test_explicit_from_stage_beats_clean(self, fake_config: Any, patch_store: Any) -> None:
        """The operator escape hatch: --resume --batch-id X --from-stage N
        where the batch APPEARS clean. Pre-044 the 'is clean' early-exit
        killed the explicit override. Post-044 explicit-from-stage wins
        unconditionally as long as the batch exists.
        """
        patch_store(_details({"S5": {"DONE": 824}}))
        assert cli_app._apply_resume(fake_config, "B-REPLAY", 5) == 5

    def test_explicit_from_stage_beats_gap_detection(
        self, fake_config: Any, patch_store: Any
    ) -> None:
        """If explicit override is set, gap auto-detection doesn't run —
        we trust the operator."""
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
