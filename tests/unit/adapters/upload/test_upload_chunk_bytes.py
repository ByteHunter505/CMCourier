"""090: ``CmisConfig.upload_chunk_bytes`` controla el tamaño del
chunk de lectura del MultipartEncoder durante el upload.

Pre-090 el chunk size estaba hardcoded a 8192 (8 KB). Con N
workers paralelos el GIL de Python serializaba los reads — cada
``enc.read(8192)`` dispara CPU work (format multipart, copy
buffers, progress callback). Para uploads grandes (>50 MB)
significaba ~6400 GIL acquisitions por archivo por worker.
Default 1 MiB reduce ese factor a ~50, restaurando paralelismo
real.
"""

from __future__ import annotations

import pytest

from cmcourier.adapters.upload.cmis_uploader import CmisConfig

pytestmark = pytest.mark.unit


class TestDefault:
    def test_default_is_one_mebibyte(self) -> None:
        cfg = CmisConfig(
            base_url="http://localhost/cmis", repo_id="TEST", username="u", password="p"
        )
        assert cfg.upload_chunk_bytes == 1 << 20, "090 default must be 1 MiB (1<<20)"


class TestSchemaModel:
    def test_schema_default_matches_dataclass(self) -> None:
        from cmcourier.config.schema import CmisConfigModel

        cfg = CmisConfigModel(base_url="http://localhost/cmis", repo_id="TEST")
        assert cfg.upload_chunk_bytes == 1 << 20

    def test_schema_accepts_explicit_value(self) -> None:
        from cmcourier.config.schema import CmisConfigModel

        cfg = CmisConfigModel(
            base_url="http://localhost/cmis", repo_id="TEST", upload_chunk_bytes=4 << 20
        )
        assert cfg.upload_chunk_bytes == 4 << 20

    def test_schema_rejects_too_small(self) -> None:
        from pydantic import ValidationError

        from cmcourier.config.schema import CmisConfigModel

        with pytest.raises(ValidationError):
            CmisConfigModel(
                base_url="http://localhost/cmis", repo_id="TEST", upload_chunk_bytes=1024
            )

    def test_schema_rejects_too_large(self) -> None:
        from pydantic import ValidationError

        from cmcourier.config.schema import CmisConfigModel

        with pytest.raises(ValidationError):
            CmisConfigModel(
                base_url="http://localhost/cmis",
                repo_id="TEST",
                upload_chunk_bytes=128 << 20,  # 128 MiB excede el límite de 64 MiB
            )
