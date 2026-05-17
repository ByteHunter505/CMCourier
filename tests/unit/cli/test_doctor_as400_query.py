"""Tests unitarios para los queries que ``cmcourier doctor`` envía a AS400 (073)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmcourier.cli import doctor as doctor_module
from cmcourier.cli.doctor import (
    CheckStatus,
    _check_as400_connectivity,  # type: ignore[attr-defined]
)
from cmcourier.config.loader import Secrets
from cmcourier.config.schema import As400ConnectionConfig, As400RvabrepSource

pytestmark = pytest.mark.unit


@dataclass
class _StubConfig:
    """Stub minimal para ``_check_as400_connectivity`` — solo necesita ``indexing.source``."""

    indexing: Any


@dataclass
class _StubIndexing:
    source: Any


def _make_config_with_as400_source(query: str = "SELECT * FROM RVILIB.RVABREP") -> _StubConfig:
    conn = As400ConnectionConfig(host="as400.test", port=446, database="RVILIB")
    source = As400RvabrepSource(kind="as400", connection=conn, query=query)
    return _StubConfig(indexing=_StubIndexing(source=source))


def _secrets() -> Secrets:
    return Secrets(
        cmis_username="cmis",
        cmis_password="cmis",
        as400_username="dbuser",
        as400_password="dbpass",
    )


class TestAs400ConnectivityQuery:
    """073: el health-check debe usar ``SELECT 1 FROM SYSIBM.SYSDUMMY1``,
    la pseudo-tabla canónica de DB2 / iSeries. ``SELECT 1`` solo (sin
    ``FROM``) es legal en MySQL/Postgres/SQL Server pero DB2 lo rechaza
    con sqlstate 42000 (syntax error).
    """

    def test_health_check_uses_sysdummy1(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: list[tuple[str, list[Any]]] = []
        fake_source = MagicMock()
        fake_source.query = MagicMock(
            side_effect=lambda sql, params: captured.append((sql, params))
        )
        fake_source.close = MagicMock()

        def fake_ctor(**kwargs: Any) -> MagicMock:
            return fake_source

        monkeypatch.setattr(doctor_module, "As400DataSource", fake_ctor)
        config = _make_config_with_as400_source()
        result = _check_as400_connectivity(config, _secrets())  # type: ignore[arg-type]

        assert result.status == CheckStatus.PASS
        assert captured == [("SELECT 1 FROM SYSIBM.SYSDUMMY1", [])]

    def test_skips_when_source_is_not_as400(self) -> None:
        # Si ``indexing.source`` no es AS400, el check debe skipear sin
        # tocar pyodbc.
        @dataclass
        class _FakeCsvSource:
            kind: str = "csv"

        cfg = _StubConfig(indexing=_StubIndexing(source=_FakeCsvSource()))
        result = _check_as400_connectivity(cfg, _secrets())  # type: ignore[arg-type]
        assert result.status == CheckStatus.SKIP

    def test_fails_when_credentials_missing(self) -> None:
        config = _make_config_with_as400_source()
        no_creds = Secrets(
            cmis_username="cmis",
            cmis_password="cmis",
            as400_username="",
            as400_password="",
        )
        result = _check_as400_connectivity(config, no_creds)  # type: ignore[arg-type]
        assert result.status == CheckStatus.FAIL
        assert "credentials" in result.message.lower()
