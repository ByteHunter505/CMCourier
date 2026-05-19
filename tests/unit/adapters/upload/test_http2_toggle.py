"""089: ``CmisConfig.http2`` permite optar fuera de HTTP/2.

Default ``True`` preserva spec 060 (negocia h2 vía ALPN, fallback
1.1). ``False`` fuerza HTTP/1.1 — cada worker mantiene su propia
conexión TCP, evitando la serialización del flow-control window
compartido de HTTP/2 multiplexing.

Caso productivo: 30 workers subiendo archivos > 50 MB toparon en
20 MB/s agregado bajo HTTP/2 multiplexing aunque el link da 1 Gbps.
Forzar HTTP/1.1 separa cada upload en su propia conexión TCP con
flow window independiente.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from cmcourier.adapters.upload.cmis_uploader import CmisConfig, CmisUploader

pytestmark = pytest.mark.unit


def _cfg(**overrides: object) -> CmisConfig:
    defaults: dict[str, object] = {
        "base_url": "http://localhost/cmis",
        "repo_id": "TEST",
        "username": "u",
        "password": "p",
        "pool_size": 8,
    }
    defaults.update(overrides)
    return CmisConfig(**defaults)  # type: ignore[arg-type]


class TestDefault:
    def test_default_enables_http2(self) -> None:
        cfg = _cfg()
        assert cfg.http2 is True, "089 default must preserve spec 060 (h2 enabled)"


class TestHttpxClientReceivesFlag:
    def test_http2_true_passes_through(self) -> None:
        with patch("cmcourier.adapters.upload.cmis_uploader.httpx.Client") as ctor:
            ctor.return_value = MagicMock()
            CmisUploader(_cfg(http2=True))
        kwargs = ctor.call_args.kwargs
        assert kwargs["http2"] is True

    def test_http2_false_forces_http_1_1(self) -> None:
        with patch("cmcourier.adapters.upload.cmis_uploader.httpx.Client") as ctor:
            ctor.return_value = MagicMock()
            CmisUploader(_cfg(http2=False))
        kwargs = ctor.call_args.kwargs
        assert kwargs["http2"] is False, (
            "089: http2=False must propagate to httpx.Client to force HTTP/1.1"
        )


class TestSchemaDefault:
    def test_cmis_config_model_default_http2_true(self) -> None:
        from cmcourier.config.schema import CmisConfigModel

        cfg = CmisConfigModel(base_url="http://localhost/cmis", repo_id="TEST")
        assert cfg.http2 is True

    def test_cmis_config_model_opt_out(self) -> None:
        from cmcourier.config.schema import CmisConfigModel

        cfg = CmisConfigModel(base_url="http://localhost/cmis", repo_id="TEST", http2=False)
        assert cfg.http2 is False
