"""086: el CLI ``cmcourier sync`` honra ``tracking.as400_sync.columns``.

Pre-086 el ``_load_stores`` del módulo ``sync`` construía el
``As400NiarvilogStore`` SIN pasar ``columns=``. Resultado: los
overrides de columnas en el YAML se ignoraban silenciosamente y el
adapter usaba los defaults canónicos (FINREI, PMRREI, STSCOD…) —
exactamente lo que rompía en producción con tablas NIARVILOG cuyos
nombres físicos diferían.

El ``batch run`` (path por ``wiring.py``) sí honraba el override.
Sólo el CLI ``sync`` estaba roto. 086 alinea ambos paths.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cmcourier.cli.commands import sync as sync_module
from cmcourier.config.schema import (
    As400ConnectionConfig,
    As400SyncConfig,
    NiarvilogColumnsModel,
    TrackingConfig,
)

pytestmark = pytest.mark.unit


def _fake_config_with_overrides() -> MagicMock:
    """``PipelineConfig`` stub con sólo lo que ``_load_stores`` lee."""
    sync_cfg = As400SyncConfig(
        enabled=True,
        library="CUSTOMLIB",
        table="NIARVILOG",
        connection=As400ConnectionConfig(
            host="as400.test",
            port=446,
            database="CUSTOMLIB",
            driver="iSeries Access ODBC Driver",
        ),
        columns=NiarvilogColumnsModel(
            finished_at_column="MY_FINISHED_COL",
            status_column="MY_STATUS_COL",
        ),
    )
    config = MagicMock()
    config.tracking = TrackingConfig(
        db_path=Path("/tmp/test-tracking.db"),
        as400_sync=sync_cfg,
    )
    return config


class TestSyncHonorsColumnsOverride:
    def test_load_stores_passes_columns_from_yaml(self) -> None:
        """086: ``_load_stores`` instancia ``As400NiarvilogStore`` con los
        columns del YAML, no con los defaults canónicos."""
        captured: dict = {}

        def fake_ctor(**kwargs: object) -> MagicMock:
            captured.update(kwargs)
            stub = MagicMock()
            stub.close = MagicMock()
            return stub

        fake_config = _fake_config_with_overrides()
        fake_secrets = MagicMock(as400_username="u", as400_password="p")

        with (
            patch.object(sync_module, "load_config", return_value=fake_config),
            patch.object(sync_module, "load_secrets", return_value=fake_secrets),
            patch.object(sync_module, "As400NiarvilogStore", side_effect=fake_ctor),
            patch.object(sync_module, "SQLiteTrackingStore", MagicMock()),
        ):
            sync_module._load_stores(Path("/dev/null"))  # type: ignore[attr-defined]

        assert "columns" in captured, (
            "086 regression: _load_stores must pass `columns=` to As400NiarvilogStore"
        )
        cols = captured["columns"]
        assert cols.finished_at == "MY_FINISHED_COL", (
            f"finished_at override lost: got {cols.finished_at!r}"
        )
        assert cols.status == "MY_STATUS_COL"
        # Las que NO se overridearon mantienen los defaults canónicos.
        assert cols.txn_num == "TRNNUM"
        assert cols.started_at == "PMRREI"
