# Agregar un sistema fuente nuevo

> [← Volver al índice](../../INDEX.md) · [How-to](../README.md) · [Developer](README.md)

CMCourier abstrae cualquier origen de datos (CSV, AS400, lo que venga) detrás de un único port: `IDataSource`. Para sumar uno nuevo — por ejemplo, leer la tabla RVABREP desde un PostgreSQL en lugar del DB2 sobre AS400 — implementás el contrato del port, lo registrás en el wiring, agregás el `kind` al schema y escribís integration tests con el adapter real.

## Cuándo aplica

- El banco migra parte de su stack y la tabla RVABREP termina en otra base.
- Querés exponer una fuente nueva (Postgres, Snowflake, archivo Parquet) para metadata sources.
- Tenés un experimento de feature flag que necesita un origen distinto sin tocar el resto del pipeline.

## El contrato del port

`src/cmcourier/domain/ports.py:IDataSource` exige seis métodos. Cualquiera nuevo los implementa todos — `NotImplementedError` solo es aceptable cuando la semántica realmente no aplica al backend (ej. `query`/`query_stream` en `TabularDataSource`, que no tiene SQL).

```python
class IDataSource(ABC):
    @abstractmethod
    def query(self, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]: ...

    @abstractmethod
    def query_stream(self, sql: str, params: list[Any] | None = None) -> Iterator[dict[str, Any]]: ...

    @abstractmethod
    def get_by_fields(self, filters: Mapping[str, Any]) -> list[dict[str, Any]]: ...

    @abstractmethod
    def get_by_fields_in(
        self,
        field: str,
        values: list[Any],
        fixed_filters: Mapping[str, Any],
    ) -> list[dict[str, Any]]: ...

    @abstractmethod
    def get_all(self) -> Iterator[dict[str, Any]]: ...

    @abstractmethod
    def count(self) -> int: ...

    @abstractmethod
    def close(self) -> None: ...
```

Invariantes de comportamiento:

- Los valores `NaN` / `NULL` se normalizan a `None` antes de salir (`TabularDataSource._normalize_row` es la referencia).
- Las claves de las filas son siempre `str` (forzá `str(k)` aunque el backend ya garantice strings).
- `query_stream` y `get_all` son lazy — no materializar el set completo en RAM.
- `close()` libera cursors / file handles / pools. Idempotente.
- Los errores de configuración → `ConfigurationError`. Los errores de I/O → propagar la excepción del backend para que el orquestador la clasifique.

## Pasos (caso: PostgreSQL para reemplazar AS400 como RVABREP source)

### 1. Implementá el adapter en `src/cmcourier/adapters/sources/postgres.py`

Esqueleto mínimo — los detalles internos los copiás de `as400.py`:

```python
from __future__ import annotations

__all__ = ["PostgresDataSource"]

from collections.abc import Iterator, Mapping
from typing import Any

import psycopg

from cmcourier.domain.exceptions import ConfigurationError
from cmcourier.domain.ports import IDataSource


class PostgresDataSource(IDataSource):
    def __init__(self, *, host: str, port: int, dbname: str,
                 username: str, password: str,
                 table: str | None = None, query: str | None = None) -> None:
        if bool(table) == bool(query):
            raise ConfigurationError("requires exactly one of `table` or `query`")
        self._table = table
        self._query = query
        self._conn = psycopg.connect(
            host=host, port=port, dbname=dbname, user=username, password=password,
        )
        self._closed = False

    # query / query_stream: server-side cursor, normalizar NULL → None
    # get_by_fields: parameterized WHERE col = %s AND ...
    # get_by_fields_in: chunkea values en batches (~50) si el backend lo necesita
    # get_all: `SELECT * FROM <table | (query) AS T>` via query_stream
    # count: SELECT COUNT(*) sobre la misma base
    # close: idempotente (chequea self._closed)
```

Mirá `src/cmcourier/adapters/sources/as400.py` para conexiones thread-local y manejo de pyodbc, y `tabular.py` para la normalización de filas (`_normalize_row`).

### 2. Sumá el `kind` al schema

Editar `src/cmcourier/config/schema.py`:

```python
class PostgresConnectionConfig(BaseModel):
    model_config = _STRICT
    host: str
    port: int = Field(default=5432, ge=1, le=65535)
    dbname: str


class PostgresRvabrepSource(BaseModel):
    model_config = _STRICT
    kind: Literal["postgres"]
    connection: PostgresConnectionConfig
    query: str
    # alternativamente, `table: str | None = None` + model_validator


RvabrepSourceUnion = Annotated[
    CsvRvabrepSource | As400RvabrepSource | PostgresRvabrepSource,
    Field(discriminator="kind"),
]
```

Y el equivalente para metadata sources si el adapter también va a alimentar S3 (`PostgresMetadataSourceConfig`, mismo patrón que `As400MetadataSourceConfig`).

### 3. Registralo en el factory

`src/cmcourier/config/wiring.py:_build_rvabrep_source` es el dispatch único — agregale la rama:

```python
def _build_rvabrep_source(indexing_cfg: IndexingConfig, secrets: Secrets) -> IDataSource:
    source = indexing_cfg.source
    if isinstance(source, CsvRvabrepSource):
        return TabularDataSource(source.csv_path)
    if isinstance(source, As400RvabrepSource):
        # ... validación de env vars y construcción ...
    if isinstance(source, PostgresRvabrepSource):
        # username/password desde env vars nuevas — agregá los campos
        # en config/env.py:Secrets primero.
        return PostgresDataSource(
            host=source.connection.host,
            port=source.connection.port,
            dbname=source.connection.dbname,
            username=secrets.postgres_username,
            password=secrets.postgres_password,
            query=source.query,
        )
    raise ConfigurationError("unknown indexing.source.kind", kind=getattr(source, "kind", "<missing>"))
```

Si el adapter va a usarse como metadata source, agregá la rama equivalente en `_build_metadata_sources`.

### 4. Exportalo desde `adapters/sources/__init__.py`

```python
__all__ = ["As400DataSource", "PostgresDataSource", "TabularDataSource"]

from cmcourier.adapters.sources.as400 import As400DataSource
from cmcourier.adapters.sources.postgres import PostgresDataSource
from cmcourier.adapters.sources.tabular import TabularDataSource
```

### 5. Integration tests con adapter REAL

Por Constitución (Principio VI), nunca mockeamos AS400 — el sustituto canónico para dev/test es `TabularDataSource` sobre fixtures CSV. Para tu fuente nueva el criterio es análogo: en CI corré los tests contra una instancia real (testcontainers de Postgres es el patrón usual) y dejá `TabularDataSource` para los tests de pipeline que solo necesitan comportamiento `IDataSource`-shaped.

Test mínimo, en `tests/integration/adapters/test_postgres_data_source.py`:

```python
import pytest
from cmcourier.adapters.sources import PostgresDataSource

pytestmark = pytest.mark.integration


def test_get_all_yields_all_rows(pg_source: PostgresDataSource) -> None:
    rows = list(pg_source.get_all())
    assert len(rows) == 100
    assert all(isinstance(k, str) for k in rows[0])


def test_get_by_fields_normalizes_nulls(pg_source: PostgresDataSource) -> None:
    rows = pg_source.get_by_fields({"ABABCD": "SHORT001"})
    assert rows[0]["ABACCD"] is None  # NULL → None
```

La fixture `pg_source` (con testcontainers o similar) vive en un `conftest.py` local. Sumá un test_smoke al `tests/test_smoke.py` si la fuente va a producción.

## Verificación

```bash
pytest tests/unit/adapters/ -v
pytest tests/integration/adapters/test_postgres_data_source.py -v
pytest tests/integration/config/ -v               # cubre el wiring
mypy src/cmcourier/adapters/sources/postgres.py    # strict no aplica acá, pero corré igual
cmcourier doctor --config postgres-staging.yaml --check connections
```

## Gotchas

- **`get_all` debe ser lazy**. El pre-fetch de metadata itera la fuente entera; si materializás todo, una tabla de 200k filas te come la RAM.
- **Sin SQL inyectado**: cuando interpolás identificadores (nombres de columna, tabla), validá contra una regex restrictiva — ver `NiarvilogColumnsModel._check_identifier` para el patrón DB2.
- **`close()` idempotente**: el orquestador puede llamarlo más de una vez en caminos de error.
- **Thread safety**: si el driver no es thread-safe (pyodbc es el caso), usá `threading.local()` para mantener una conexión por thread, igual que `As400DataSource`.
- **No mockees el port en tests del SUT que lo consume**. La práctica del repo es usar `TabularDataSource` real sobre fixtures (ver `tests/unit/services/test_metadata.py`). Mockear `IDataSource` esconde bugs de contrato.
- **Env vars nuevas**: las credenciales nunca van al YAML — agregalas a `config/env.py:Secrets` y documentalas en el `README.md` ("Cómo empezar").

## Ver también

- `src/cmcourier/domain/ports.py` — el contrato completo de `IDataSource`
- `src/cmcourier/adapters/sources/tabular.py` — referencia simple (CSV/XLSX, sin SQL)
- `src/cmcourier/adapters/sources/as400.py` — referencia con SQL + thread-local connections
- `src/cmcourier/config/wiring.py` — `_build_rvabrep_source` y `_build_metadata_sources`
- `.specify/memory/constitution.md` — Principio I (puertos puros), Principio VI (no mockear AS400)
