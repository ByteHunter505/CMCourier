"""Integration tests for dual heavy/light lane S5 dispatch (036 Phase 2).

Builds a ``StagedPipeline`` with mocked dependencies and drives
``_stage_5`` directly with synthetic ``_StageItem`` lists. Verifies:

* Dual-lane path runs when ``HeavyLightLanesConfig.enabled`` is True
  AND the splitter says not-single-lane.
* Single-lane path runs (and stays byte-identical to pre-036) when
  the config is absent / disabled / batch too small / degenerate.
* Items end up uploaded regardless of lane.
* Heavy and light per-lane stats reflect the actual dispatch.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from cmcourier.config.schema import HeavyLightLanesConfig
from cmcourier.domain.models import (
    CMMapping,
    ResolvedMetadata,
    RVABREPDocument,
    StagedFile,
    TriggerRecord,
)
from cmcourier.orchestrators.staged import StagedPipeline, _StageItem

pytestmark = pytest.mark.integration


def _make_item(txn: str, size_bytes: int) -> _StageItem:
    trigger = TriggerRecord(shortname="CLIENT01", cif="999999", system_id="1")
    doc = RVABREPDocument(
        system_code="1",
        txn_num=txn,
        index1="",
        index2="999999",
        index3="",
        index4="",
        index5="",
        index6="",
        index7="CC03",
        image_type="O",
        image_path="paged_tiff/PROD/2025/11/17",
        file_name=f"{txn}.001",
        creation_date=datetime(2025, 11, 17, tzinfo=UTC),
        last_view_date=None,
        total_pages=1,
        delete_code="",
    )
    mapping = CMMapping(
        clase_id="04.01.01.01.01",
        id_rvi="FF17",
        id_corto="CN01",
        clase_name="Test",
        required_metadata_fields=(),
        cmis_type="",
    )
    metadata = ResolvedMetadata(
        properties={"cmis:objectTypeId": mapping.cm_object_type},
    )
    staged = StagedFile(
        path=Path(f"/tmp/staged-{txn}.pdf"),
        page_count=1,
        size_bytes=size_bytes,
    )
    return _StageItem(
        trigger=trigger,
        document=doc,
        mapping=mapping,
        metadata=metadata,
        staged_file=staged,
    )


def _build_pipeline(
    *,
    workers: int = 4,
    lanes: HeavyLightLanesConfig | None = None,
    upload_returns: str = "cm-abc",
) -> StagedPipeline:
    """Construct a pipeline with mocked deps, just enough for ``_stage_5``."""
    uploader = MagicMock()
    uploader.upload.return_value = upload_returns
    uploader._timeout_s = 60.0

    tracking_store = MagicMock()
    tracking_store.is_stage_done.return_value = False
    tracking_store.is_uploaded.return_value = False

    return StagedPipeline(
        trigger_strategy=MagicMock(),
        indexing_service=MagicMock(),
        mapping_service=MagicMock(),
        metadata_service=MagicMock(),
        assembler=MagicMock(),
        uploader=uploader,
        tracking_store=tracking_store,
        workers=workers,
        heavy_light_lanes=lanes,
    )


_KB = 1024
_MB = 1024 * 1024


class TestSingleLaneBackwardsCompat:
    def test_no_lanes_config_uses_single_pool(self) -> None:
        pipeline = _build_pipeline(workers=4, lanes=None)
        items = [_make_item(f"t{i:03d}", 100 * _KB) for i in range(10)]
        done, failed = pipeline._stage_s5(items, "batch_x")
        assert done == 10
        assert failed == 0
        # Single-lane controller is None.
        assert pipeline.lane_controller is None

    def test_lanes_disabled_uses_single_pool(self) -> None:
        cfg = HeavyLightLanesConfig(enabled=False)
        pipeline = _build_pipeline(workers=4, lanes=cfg)
        items = [_make_item(f"t{i:03d}", 100 * _KB) for i in range(10)]
        done, _failed = pipeline._stage_s5(items, "batch_x")
        assert done == 10
        assert pipeline.lane_controller is None

    def test_small_batch_falls_back_to_single(self) -> None:
        cfg = HeavyLightLanesConfig(enabled=True, heavy_lane_min_batch=50)
        pipeline = _build_pipeline(workers=4, lanes=cfg)
        # 10 items < min_batch=50 → splitter returns single-lane.
        items = [_make_item(f"t{i:03d}", 50 * _MB) for i in range(10)]
        done, _failed = pipeline._stage_s5(items, "batch_x")
        assert done == 10
        assert pipeline.lane_controller is not None
        # Controller exists but wasn't driven (no items dispatched).
        snap = pipeline.lane_controller.snapshot()
        assert snap.heavy.completed == 0
        assert snap.light.completed == 0


class TestDualLaneHappyPath:
    def test_bimodal_batch_dispatches_both_lanes(self) -> None:
        cfg = HeavyLightLanesConfig(
            enabled=True,
            heavy_threshold_bytes=10 * _MB,
            heavy_lane_min_batch=10,
            heavy_initial_ratio=0.5,
        )
        pipeline = _build_pipeline(workers=4, lanes=cfg)
        heavy = [_make_item(f"h{i:03d}", 50 * _MB) for i in range(5)]
        light = [_make_item(f"l{i:03d}", 200 * _KB) for i in range(15)]
        done, failed = pipeline._stage_s5([*heavy, *light], "batch_x")
        assert done == 20
        assert failed == 0
        assert pipeline.lane_controller is not None
        snap = pipeline.lane_controller.snapshot()
        assert snap.heavy.completed == 5
        assert snap.light.completed == 15

    def test_all_heavy_falls_back_to_single(self) -> None:
        """Degenerate split → caller stays on the single-lane path."""
        cfg = HeavyLightLanesConfig(
            enabled=True,
            heavy_threshold_bytes=10 * _MB,
            heavy_lane_min_batch=10,
        )
        pipeline = _build_pipeline(workers=4, lanes=cfg)
        items = [_make_item(f"h{i:03d}", 50 * _MB) for i in range(20)]
        done, _failed = pipeline._stage_s5(items, "batch_x")
        assert done == 20
        # Dual stats stay at zero — single-lane path ran.
        snap = pipeline.lane_controller.snapshot()  # type: ignore[union-attr]
        assert snap.heavy.completed == 0
        assert snap.light.completed == 0


class TestDualLaneFailureRouting:
    def test_failure_in_heavy_lane_counts_per_lane(self) -> None:
        cfg = HeavyLightLanesConfig(
            enabled=True,
            heavy_threshold_bytes=10 * _MB,
            heavy_lane_min_batch=10,
        )
        pipeline = _build_pipeline(workers=4, lanes=cfg)
        # Make the uploader raise CMIS client error on every call.
        from cmcourier.adapters.upload.cmis_uploader import CMISClientError

        pipeline._uploader.upload.side_effect = CMISClientError(  # type: ignore[union-attr]
            status_code=400, response_body="boom"
        )
        heavy = [_make_item(f"h{i:03d}", 50 * _MB) for i in range(5)]
        light = [_make_item(f"l{i:03d}", 200 * _KB) for i in range(15)]
        done, failed = pipeline._stage_s5([*heavy, *light], "batch_x")
        assert done == 0
        assert failed == 20
        snap = pipeline.lane_controller.snapshot()  # type: ignore[union-attr]
        assert snap.heavy.failed == 5
        assert snap.light.failed == 15


# ---------------------------------------------------------------------------
# 039: cmis_type override (Alfresco / non-IBM-CM staging support)
# ---------------------------------------------------------------------------


class TestCmisTypeOverride:
    def test_override_used_when_cmis_type_set(self) -> None:
        pipeline = _build_pipeline(workers=2, lanes=None)
        item = _make_item("TXN_0001", 100 * _KB)
        item.mapping = CMMapping(
            clase_id="01.02.04.01.01",
            id_rvi="FF17",
            id_corto="CN01",
            clase_name="Test",
            required_metadata_fields=(),
            cmis_type="cmis:document",  # 039: explicit override
        )
        pipeline._stage_s5([item], "batch_x")
        # Uploader called with cmis_type as object_type_id, not the
        # derived $t!… value.
        kwargs = pipeline._uploader.upload.call_args.kwargs  # type: ignore[union-attr]
        assert kwargs["object_type_id"] == "cmis:document"

    def test_derived_type_when_cmis_type_empty(self) -> None:
        pipeline = _build_pipeline(workers=2, lanes=None)
        item = _make_item("TXN_0001", 100 * _KB)
        # _make_item sets cmis_type="" by default.
        pipeline._stage_s5([item], "batch_x")
        kwargs = pipeline._uploader.upload.call_args.kwargs  # type: ignore[union-attr]
        # Falls back to the derived IBM CM pattern.
        assert kwargs["object_type_id"].startswith("$t!")
