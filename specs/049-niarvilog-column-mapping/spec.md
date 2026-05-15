# 049 — Nombres de columna / identificadores de NIARVILOG configurables

## Por qué

El banco corre CMCourier contra varios entornos AS400 (dev / test /
prod, más variantes por-sucursal). A lo largo de esos entornos la
tabla de coordinación ``NIARVILOG`` tiene las **mismas 15 columnas**
pero los **nombres físicos de las columnas difieren**, y los
**nombres de library / tabla** también difieren.

Hoy solo la mitad de eso es configurable:

- **Nombres de columna RVABREP** — ya resuelto. ``IndexingColumnsModel``
  (``schema.py:147``) es un mapa lógico→físico de columnas; el
  operador redefine ``indexing.columns.*`` por entorno.
- **Library + tabla de NIARVILOG** — ya resuelto.
  ``As400SyncConfig.library`` / ``.table`` (``schema.py:451-452``)
  están wireados al ``As400NiarvilogStore`` (``wiring.py:203-204``).
- **Nombres de columna de NIARVILOG** — **NO resuelto.** Los 15
  nombres físicos (``SISCOD``, ``TRNNUM``, ``DOCFRM``, ``IMGARC``,
  ``IMGTIP``, ``CTECIF``, ``CTENUM``, ``STSCOD``, ``IDNBAC``,
  ``TIPIDN``, ``OBJIDN``, ``NUMREI``, ``PMRREI``, ``FINREI``,
  ``EERRMSG``) están **hard-coded** en ``as400_niarvilog.py`` — en
  la constante ``_SELECT_COLUMNS`` y en cada ``UPDATE`` /
  ``INSERT`` / ``WHERE`` / ``SELECT`` y en las claves del dict de
  parseo de filas. Un entorno cuyo NIARVILOG usa nombres distintos
  no se puede configurar — necesita un cambio de código.

049 cierra ese gap, simétrico a lo que ``IndexingColumnsModel``
hace para RVABREP.

## Nota de seguridad (en alcance)

Los nombres de columna / library / tabla de NIARVILOG **no** son
bind-parameters — un identificador SQL nunca puede ser un
placeholder ``?``, tiene que ser string-interpolado en el statement.
Eso hace que cada identificador configurable sea una superficie
potencial de SQL-injection. Por eso 049 agrega **validación de
identificadores** a todos:

- el nuevo ``NiarvilogColumnsModel`` valida cada uno de sus 15
  campos,
- ``As400SyncConfig.library`` / ``.table`` ganan la **misma**
  validación (pre-049 se interpolaban en ``_full_table()`` **sin
  validación** — un issue latente que esta spec también arregla).

Un identificador válido matchea ``^[A-Za-z@#$][A-Za-z0-9@#$_]{0,127}$``
(reglas de identificador ordinario de DB2 for i: ``@``, ``#``, ``$``
cuentan como letras; máximo 128 chars). Cualquier otra cosa levanta
en config-load.

## Qué

### 1. `NiarvilogColumnsModel` en `schema.py`

Un nuevo ``BaseModel`` (``_STRICT``) — mapa lógico→físico, 15
campos, defaults iguales a los nombres físicos hard-coded actuales
así los configs y tests existentes son byte-idénticos cuando se
omite el bloque:

```python
class NiarvilogColumnsModel(BaseModel):
    model_config = _STRICT
    system_id_column: str = "SISCOD"
    txn_num_column: str = "TRNNUM"
    doc_format_column: str = "DOCFRM"
    image_archive_column: str = "IMGARC"
    image_type_column: str = "IMGTIP"
    client_cif_column: str = "CTECIF"
    client_num_column: str = "CTENUM"
    status_column: str = "STSCOD"
    idcm_column: str = "IDNBAC"
    cm_type_column: str = "TIPIDN"
    cm_object_id_column: str = "OBJIDN"
    retry_count_column: str = "NUMREI"
    started_at_column: str = "PMRREI"
    finished_at_column: str = "FINREI"
    error_message_column: str = "EERRMSG"

    @field_validator("*")
    @classmethod
    def _valid_sql_identifier(cls, v: str) -> str: ...
```

Cuelga de ``As400SyncConfig`` como
``columns: NiarvilogColumnsModel = Field(default_factory=...)``.

```yaml
tracking:
  as400_sync:
    enabled: true
    library: MIBIB
    table: MININARVILOG
    connection: {host: 10.0.0.1}
    columns:
      status_column: ESTADO
      txn_num_column: NUMTRX
      # ... cualquier subset; los campos omitidos mantienen el default canónico
```

### 2. Dataclass `NiarvilogColumns` + builder de SQL en el adapter

``as400_niarvilog.py`` ya importa ``As400ConnectionConfig`` desde
``config.schema`` (línea 47), así que el límite "los adapters no
importan schema" de la constitución ya está cruzado acá para el
tipo de conexión. Para evitar *profundizar* eso, 049 introduce un
dataclass frozen ``NiarvilogColumns`` **en el módulo del adapter**
(el tipo propio del adapter), y ``wiring.py`` traduce
``NiarvilogColumnsModel`` → ``NiarvilogColumns`` — el mismo patrón
que usa ``IndexingService`` (``IndexingColumnsModel`` →
``IndexingColumnsConfig``).

``As400NiarvilogStore.__init__`` gana ``columns: NiarvilogColumns |
None = None`` (default a ``NiarvilogColumns()`` con nombres
canónicos → cada caller / test existente queda inalterado).

Cada identificador SQL hard-coded se reemplaza por
``self._cols.<field>``:

- Constante ``_SELECT_COLUMNS`` → un ``_select_columns()``
  construido desde el modelo.
- ``try_claim`` — ``UPDATE`` (SET status/idcm/cm_type, WHERE pk +
  status='N') + ``_insert_new_claim`` ``INSERT`` (13 columnas).
- ``mark_uploaded`` / ``mark_uploaded_by_txn`` — ``UPDATE`` SET
  status/cm_object_id/error WHERE pk-o-txn.
- ``mark_failed`` — ``UPDATE`` SET status/error/retry WHERE pk.
- ``read_state`` / ``read_state_by_txn`` — ``SELECT`` + la
  construcción de ``NiarvilogRow`` ahora keya el dict resultado
  por los nombres físicos **configurados**.
- ``cleanup_stale_in_progress`` — ``UPDATE`` SET status WHERE
  status + finished_at.
- ``_full_table()`` — forma sin cambios, pero ``library`` /
  ``table`` ahora llegan pre-validados.

Los *valores* ``STSCOD`` (``'N'`` / ``'I'`` / ``'O'`` / ``'F'``)
son data, no identificadores — se quedan literales. ``NiarvilogRow``
mantiene sus nombres de campo lógicos (``siscod``, ``trnnum``, …)
— es la forma interna de retorno del adapter, inalterada.

### 3. Wiring

``_build_idempotency_coordinator`` (``wiring.py:~199``) pasa
``columns=_niarvilog_columns_from_schema(sync_cfg.columns)`` al
``As400NiarvilogStore``.

## Fuera de alcance

- Validación de nombres de columna RVABREP. Los nombres físicos
  RVABREP **no** se interpolan en SQL — para la fuente RVABREP de
  AS400 el operador provee la ``query`` completa y
  ``IndexingColumnsModel`` mapea las claves del dict del
  *result-set* (a nivel pandas). Sin superficie de injection, sin
  cambio necesario.
- Perfiles de config por-entorno / un mecanismo de config-include.
  Cada entorno mantiene su propio YAML completo, como hoy.
- Cambiar el **schema lógico** de NIARVILOG (los 15 campos, la PK
  compuesta, la máquina de estados de ``STSCOD``). 049 solo hace
  configurables los *nombres físicos*.
- Un shim de migración. Pre-producción — los únicos configs
  NIARVILOG en el repo son fixtures de test; omitir el bloque
  ``columns`` mantiene los defaults canónicos, así que no hay nada
  que migrar.

## Criterios de aceptación

- ``tracking.as400_sync.columns`` carga; omitido → defaults
  canónicos; parcial → override por-campo.
- Un identificador inválido (espacios, ``;``, comillas, dígito
  inicial, > 128 chars) en cualquier campo ``columns.*``, o en
  ``library`` / ``table``, levanta ``ValidationError`` /
  ``ConfigurationError`` en tiempo de carga.
- ``As400NiarvilogStore`` construido con ``NiarvilogColumns``
  custom emite SQL usando los nombres custom — asserteado sobre
  las tuplas ``(sql, params)`` capturadas para ``try_claim`` /
  ``mark_uploaded`` / ``mark_failed`` / ``read_state`` /
  ``cleanup_stale_in_progress``.
- ``read_state`` parsea un result set keyeado por nombres
  **custom**.
- Con columnas default, cada aserción existente de
  ``test_as400_niarvilog.py`` sigue pasando (SQL byte-idéntico
  para el caso default).
- ``wiring`` pasa las columnas traducidas a través.
- Suite completa unit + integration verde; mypy + ruff limpios.
- Entrada ``CHANGELOG.md [0.52.0]``; ``pyproject.toml`` 0.51.0 →
  0.52.0; ``docs/how-to/as400-sync.md`` documenta el nuevo bloque.

## Notas sobre estrategia de tests

Mismo enfoque que el ``test_as400_niarvilog.py`` existente — fake
de ``pyodbc`` en el límite cursor/conexión, assertear sobre los
strings SQL grabados. 049 agrega una clase
``TestConfigurableColumns`` que construye el store con una
``NiarvilogColumns`` no-default y assertea que los identificadores
custom aparecen en el SQL emitido (y los canónicos no). Los tests
de validación de identificador viven en
``tests/unit/config/test_schema.py``.
