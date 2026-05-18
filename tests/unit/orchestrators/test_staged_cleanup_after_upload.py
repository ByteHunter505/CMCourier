"""085: ``StagedPipeline._cleanup_staged_file`` borra el archivo
ensamblado de ``temp_dir`` después de un ``S5_DONE`` exitoso.

Default behavior: ``keep_staged_files=False`` → unlink.
Opt-out: ``keep_staged_files=True`` → preserva para debug.
Failure del unlink no propaga (no debe abortar un upload que ya
persistió ``S5_DONE``).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cmcourier.domain.models import StagedFile

pytestmark = pytest.mark.unit


def _make_pipeline_stub(*, keep_staged_files: bool) -> object:
    """Construye un objeto mínimo con el contrato que
    ``_cleanup_staged_file`` necesita — no instancia toda la
    ``StagedPipeline`` para mantener el test aislado del wiring."""
    from cmcourier.orchestrators.staged import StagedPipeline

    stub = StagedPipeline.__new__(StagedPipeline)
    stub._keep_staged_files = keep_staged_files  # type: ignore[attr-defined]
    return stub


class TestCleanupOnDefault:
    def test_unlinks_existing_staged_file(self, tmp_path: Path) -> None:
        staged_path = tmp_path / "TXN001.pdf"
        staged_path.write_bytes(b"%PDF-1.4 dummy")
        assert staged_path.exists()

        staged = StagedFile(path=staged_path, size_bytes=14, page_count=1)
        pipeline = _make_pipeline_stub(keep_staged_files=False)

        from cmcourier.orchestrators.staged import StagedPipeline

        StagedPipeline._cleanup_staged_file(pipeline, staged)  # type: ignore[arg-type]
        assert not staged_path.exists(), "staged file should be unlinked post-S5_DONE"

    def test_missing_path_does_not_raise(self, tmp_path: Path) -> None:
        # Idempotencia: si el archivo ya no existe (ej. otro proceso
        # lo borró, o hubo retry y S4 nunca corrió en este run), el
        # cleanup es no-op silencioso.
        ghost = tmp_path / "ghost.pdf"
        staged = StagedFile(path=ghost, size_bytes=0, page_count=0)
        pipeline = _make_pipeline_stub(keep_staged_files=False)

        from cmcourier.orchestrators.staged import StagedPipeline

        StagedPipeline._cleanup_staged_file(pipeline, staged)  # type: ignore[arg-type]


class TestKeepStagedFiles:
    def test_opt_out_preserves_file(self, tmp_path: Path) -> None:
        staged_path = tmp_path / "TXN002.pdf"
        staged_path.write_bytes(b"%PDF-1.4 keep me")

        staged = StagedFile(path=staged_path, size_bytes=16, page_count=1)
        pipeline = _make_pipeline_stub(keep_staged_files=True)

        from cmcourier.orchestrators.staged import StagedPipeline

        StagedPipeline._cleanup_staged_file(pipeline, staged)  # type: ignore[arg-type]
        assert staged_path.exists(), "keep_staged_files=True must NOT unlink"


class TestUnlinkFailureDoesNotPropagate:
    def test_oserror_logged_but_not_raised(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Simula un unlink que tira OSError (típicamente Windows con
        # el archivo abierto por otro proceso). El método NO debe
        # propagar — un cleanup roto post-S5_DONE no puede revertir
        # un upload ya persistido.
        staged_path = tmp_path / "TXN003.pdf"
        staged_path.write_bytes(b"data")
        staged = StagedFile(path=staged_path, size_bytes=4, page_count=1)
        pipeline = _make_pipeline_stub(keep_staged_files=False)

        def boom(self: Path, missing_ok: bool = False) -> None:
            raise OSError("file locked by another process")

        monkeypatch.setattr(Path, "unlink", boom)

        from cmcourier.orchestrators.staged import StagedPipeline

        StagedPipeline._cleanup_staged_file(pipeline, staged)  # type: ignore[arg-type]


class TestConfigDefault:
    def test_assembly_config_default_keeps_false(self) -> None:
        from cmcourier.config.schema import AssemblyConfig

        cfg = AssemblyConfig(
            source_root=Path("/tmp"),
            temp_dir=Path("/tmp/staged"),
        )
        assert cfg.keep_staged_files is False
