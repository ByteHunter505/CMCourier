# 074 — Plan

## Decisión: dónde aplicar el strip

Dos lugares candidatos:

1. **En el adapter `As400DataSource`** al materializar rows de
   pyodbc — un solo punto, aplica a TODOS los consumers de AS400
   (S1 indexing, S3 metadata sources, mock generate, as400-query
   passthrough).

2. **En cada consumer (`IndexingService`, `MetadataService`, etc.)**
   — más localizado pero requiere recordarlo en cada lugar nuevo.
   Defectos: (a) duplicación; (b) cada consumer puede olvidarse;
   (c) la frontera entre dominio y representación-de-DB2 queda
   leakeada.

**Elegido: opción 1.** El adapter es la frontera correcta para
absorber detalles de representación de DB2. Domain y services
trabajan con strings limpios, sin asumir cosas de la fuente.

## Implementación

Agregar un helper a nivel de módulo en `adapters/sources/as400.py`:

```python
def _normalize_row(columns: list[str], row: Any) -> dict[str, Any]:
    """074: strippea trailing whitespace de valores ``str`` —
    los CHAR(N) de DB2/iSeries vuelven padded a longitud fija con
    espacios, y eso filtra hacia el dominio (delete-code, idempotency
    key, matching de triggers, etc.). Strippeamos en la frontera
    del adapter para que el resto del sistema trate strings limpios.

    Solo afecta valores ``str``. Tipos numéricos, ``date``/``datetime``,
    ``bool``, ``None``, ``bytes`` pasan sin tocar.
    """
    return {
        col: (value.strip() if isinstance(value, str) else value)
        for col, value in zip(columns, row, strict=False)
    }
```

Y reemplazar las dos llamadas:

```python
# query() línea 95 — antes:
rows = [dict(zip(columns, row, strict=False)) for row in cursor.fetchall()]
# después:
rows = [_normalize_row(columns, row) for row in cursor.fetchall()]

# query_stream() línea 137 — antes:
yield dict(zip(columns, row, strict=False))
# después:
yield _normalize_row(columns, row)
```

Cambio mecánico, idéntico en los dos puntos.

## Tests

Archivo nuevo: `tests/unit/adapters/sources/test_as400_normalize.py`.

Tests directos a `_normalize_row` (función pura, fácil de testear sin
DB2 / pyodbc):

1. `test_str_with_trailing_spaces_is_stripped`
   ```python
   assert _normalize_row(["ABACST"], [" "])  == {"ABACST": ""}
   assert _normalize_row(["ABABCD"], ["SHORT1  "]) == {"ABABCD": "SHORT1"}
   ```

2. `test_str_with_leading_and_trailing_spaces_is_stripped_both_ways`
   ```python
   assert _normalize_row(["X"], ["  YES  "]) == {"X": "YES"}
   ```

3. `test_non_str_values_pass_through_untouched`
   ```python
   d = _normalize_row(["I", "F", "B", "N"], [5, 1.5, True, None])
   assert d == {"I": 5, "F": 1.5, "B": True, "N": None}
   ```

4. `test_date_and_datetime_preserved`
   ```python
   from datetime import date, datetime
   d = _normalize_row(
       ["DA", "DT"], [date(2026, 5, 17), datetime(2026, 5, 17, 12, 0)]
   )
   assert d["DA"] == date(2026, 5, 17)
   assert d["DT"] == datetime(2026, 5, 17, 12, 0)
   ```

5. `test_bytes_pass_through`
   ```python
   d = _normalize_row(["BLOB"], [b"binary"])
   assert d == {"BLOB": b"binary"}
   ```

6. `test_empty_string_stays_empty`
   ```python
   assert _normalize_row(["X"], [""]) == {"X": ""}
   ```

7. `test_mixed_row`
   ```python
   d = _normalize_row(
       ["ABABCD", "ABACST", "ABABUN", "ABAADT"],
       ["SHORT1  ", " ", 5, date(2026, 5, 17)],
   )
   assert d == {
       "ABABCD": "SHORT1",
       "ABACST": "",
       "ABABUN": 5,
       "ABAADT": date(2026, 5, 17),
   }
   ```

Verificación integration (opcional pero recomendado): un test que
mockee pyodbc para devolver rows padded, llame
`As400DataSource.query`, y asevere que las rows vuelven trimmed.

## Phased commits

1. `feat: add 074 spec, plan, tasks — strip AS400 CHAR padding`
2. `fix(adapters): strip whitespace from AS400 string columns at materialization (074)`
3. `test: cover As400DataSource._normalize_row`
4. `docs(074): CHANGELOG 0.76.0 + version bump`

## Verificación post-cambio

```bash
pytest -m unit                                            # smoke completo
pytest tests/unit/adapters/sources/test_as400_normalize.py -v
cmcourier --version                                       # 0.76.0
```

Y desde el cliente productivo (Windows):

```powershell
git pull
pip install -e . --no-deps
cmcourier rvabrep-pipeline run --config <yaml> --batch-id smoke --total 5
# Ya no debería tirar "Every RVABREP record for the trigger is marked deleted"
# para filas cuyo ABACST viene como " " (CHAR padding).
```
