"""087: ``As400NiarvilogStore._build_connection_string`` incluye
``CommitMode=0`` (= ``*NONE``) para desactivar commitment control.

Pre-087, el driver IBM i Access ODBC abría la conexión con default
``*CHG``, que requiere que la tabla NIARVILOG esté journaled. Tablas
no journaled rompían con::

    SQL7008 - <table> in <library> not valid for operation

CMCourier no usa transacciones multi-statement — el claim atómico
viene del ``WHERE STSCOD='N'``, no del ``conn.commit()``. Con
``CommitMode=0`` funciona contra tablas journaled o no.
"""

from __future__ import annotations

import pytest

from cmcourier.adapters.tracking.as400_niarvilog import As400NiarvilogStore
from cmcourier.config.schema import As400ConnectionConfig

pytestmark = pytest.mark.unit


def _store() -> As400NiarvilogStore:
    return As400NiarvilogStore(
        connection=As400ConnectionConfig(
            host="as400.test",
            port=446,
            database="LIBHJJ",
            driver="IBM i Access ODBC Driver",
        ),
        username="u",
        password="p",
        library="LIBHJJ",
        table="RVIMGLOG",
    )


class TestCommitModeDisabled:
    def test_connection_string_includes_commit_mode_zero(self) -> None:
        store = _store()
        conn_str = store._build_connection_string()  # type: ignore[attr-defined]
        assert "CommitMode=0" in conn_str, (
            "087 regression: connection string must include CommitMode=0 "
            "to avoid SQL7008 on non-journaled NIARVILOG tables"
        )

    def test_connection_string_preserves_other_params(self) -> None:
        store = _store()
        conn_str = store._build_connection_string()  # type: ignore[attr-defined]
        # Sanity check: el fix de 087 no rompe los parámetros existentes.
        for required in (
            "DRIVER={IBM i Access ODBC Driver}",
            "SYSTEM=as400.test",
            "PORT=446",
            "DATABASE=LIBHJJ",
            "UID=u",
            "PWD=p",
        ):
            assert required in conn_str, f"missing connection param: {required}"
