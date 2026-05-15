"""Tests unitarios para el techo del `thread pool` de S5 (057).

Antes de 057 el ``ThreadPoolExecutor`` de S5 se dimensionaba al
``cmis.workers`` inicial, así que el ``ResizableSemaphore`` redimensionado
por `AIMD` nunca podía excederlo — ``pool_in_use`` quedaba clavado
en el conteo inicial. Estos tests fijan tanto el cómputo del techo
como el ``max_workers`` real con el que se construyen los
ejecutores.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor as _RealThreadPoolExecutor
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmcourier.config.schema import AutoTuneConfig, HeavyLightLanesConfig
from cmcourier.orchestrators.staged import StagedPipeline

pytestmark = pytest.mark.unit


def _make_pipeline(
    *,
    workers: int = 4,
    auto_tune: AutoTuneConfig | None = None,
    heavy_light_lanes: HeavyLightLanesConfig | None = None,
) -> StagedPipeline:
    """Un `StagedPipeline` con colaboradores `mock` — suficiente para
    ejercitar los helpers de `dispatch` de S5, que solo tocan el `pool`
    + el controlador de `lane`."""
    return StagedPipeline(
        trigger_strategy=MagicMock(),
        indexing_service=MagicMock(),
        mapping_service=MagicMock(),
        metadata_service=MagicMock(),
        assembler=MagicMock(),
        uploader=MagicMock(),
        tracking_store=MagicMock(),
        workers=workers,
        auto_tune=auto_tune,
        heavy_light_lanes=heavy_light_lanes,
    )


def _recording_executor_factory(captured: dict[str, int]):  # type: ignore[no-untyped-def]
    """Reemplazo `drop-in` para ``ThreadPoolExecutor`` que registra
    ``max_workers`` para cada `pool` ``cmcourier-s5*``, luego delega
    a la clase real. El `pool` de prep de 056 (``cmcourier-prep``) se
    ignora a propósito."""

    def _factory(*args: Any, **kwargs: Any) -> _RealThreadPoolExecutor:
        prefix = str(kwargs.get("thread_name_prefix", ""))
        if prefix.startswith("cmcourier-s5"):
            captured[prefix] = int(kwargs["max_workers"])
        return _RealThreadPoolExecutor(*args, **kwargs)

    return _factory


class TestPoolCeiling057:
    def test_ceiling_is_max_threads_when_auto_tune_enabled(self) -> None:
        pipeline = _make_pipeline(workers=4, auto_tune=AutoTuneConfig(enabled=True, max_threads=16))
        assert pipeline._pool_ceiling() == 16  # noqa: SLF001

    def test_ceiling_is_workers_when_auto_tune_disabled(self) -> None:
        pipeline = _make_pipeline(workers=4, auto_tune=AutoTuneConfig(enabled=False))
        assert pipeline._pool_ceiling() == 4  # noqa: SLF001

    def test_ceiling_is_workers_when_no_auto_tune_config(self) -> None:
        pipeline = _make_pipeline(workers=4, auto_tune=None)
        assert pipeline._pool_ceiling() == 4  # noqa: SLF001

    def test_ceiling_never_below_initial_workers(self) -> None:
        # `cmis.workers` deliberadamente por encima de `auto_tune.max_threads`
        # — el `pool` no debe achicarse por debajo del conteo inicial
        # configurado por el operador.
        pipeline = _make_pipeline(workers=20, auto_tune=AutoTuneConfig(enabled=True, max_threads=8))
        assert pipeline._pool_ceiling() == 20  # noqa: SLF001


class TestSinglePoolSizing057:
    def test_single_pool_sized_to_ceiling_with_auto_tune(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pipeline = _make_pipeline(workers=4, auto_tune=AutoTuneConfig(enabled=True, max_threads=16))
        captured: dict[str, int] = {}
        monkeypatch.setattr(
            "cmcourier.orchestrators.staged.ThreadPoolExecutor",
            _recording_executor_factory(captured),
        )
        # `batch` vacío — el ejecutor igual se construye, sin uploads.
        pipeline._stage_5_single([], "B1", pipeline._metrics)  # noqa: SLF001
        assert captured == {"cmcourier-s5": 16}

    def test_single_pool_uses_workers_without_auto_tune(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pipeline = _make_pipeline(workers=4, auto_tune=None)
        captured: dict[str, int] = {}
        monkeypatch.setattr(
            "cmcourier.orchestrators.staged.ThreadPoolExecutor",
            _recording_executor_factory(captured),
        )
        pipeline._stage_5_single([], "B1", pipeline._metrics)  # noqa: SLF001
        assert captured == {"cmcourier-s5": 4}


class TestDualPoolSizing057:
    def test_both_dual_pools_sized_to_ceiling(self, monkeypatch: pytest.MonkeyPatch) -> None:
        pipeline = _make_pipeline(
            workers=4,
            auto_tune=AutoTuneConfig(enabled=True, max_threads=16),
            heavy_light_lanes=HeavyLightLanesConfig(enabled=True),
        )
        captured: dict[str, int] = {}
        monkeypatch.setattr(
            "cmcourier.orchestrators.staged.ThreadPoolExecutor",
            _recording_executor_factory(captured),
        )
        # Asignación vacía — ambos ejecutores de `lane` igual se construyen.
        pipeline._stage_5_dual(((), ()), "B1", pipeline._metrics)  # noqa: SLF001
        assert captured == {
            "cmcourier-s5-heavy": 16,
            "cmcourier-s5-light": 16,
        }
