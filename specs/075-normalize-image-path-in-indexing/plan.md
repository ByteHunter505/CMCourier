# 075 — Plan

## Implementación

### Helper privado en `services/indexing.py`

Agregar después de los helpers `_str` / `_to_int` existentes:

```python
def _normalize_image_path(value: str) -> str:
    """075: strippea leading separators del ``ABAICD`` antes de que
    pase al dominio.

    El RVI escribe el ``image_path`` con un leading ``/`` (paths
    "absolutos" desde la raíz del file share). Pre-075 ese path
    llegaba al assembler tal cual, y al concatenarlo con
    ``assembly.source_root`` vía ``Path / Path``, pathlib descartaba
    silenciosamente ``source_root`` (comportamiento documentado:
    `Path("a") / "/b"` devuelve `Path("/b")`).

    Esta normalización aplana backslashes a forward slashes,
    strippea separadores al inicio, y strippea whitespace. Devuelve
    ``str`` para mantener el tipo del campo
    ``RVABREPDocument.image_path``.
    """
    return value.replace("\\", "/").lstrip("/").strip()
```

### Aplicar en el callsite

```python
# services/indexing.py:269 — antes
image_path=_str(row.get(cfg.image_path_column)),

# después
image_path=_normalize_image_path(_str(row.get(cfg.image_path_column))),
```

Una línea modificada + 3 líneas nuevas del helper.

## Tests

Archivo: `tests/unit/services/test_indexing_image_path.py` (nuevo).

```python
from cmcourier.services.indexing import _normalize_image_path

class TestNormalizeImagePath:
    def test_relative_passes_through(self):
        assert _normalize_image_path("RVI9/020526/0004") == "RVI9/020526/0004"

    def test_leading_forward_slash_stripped(self):
        # El caso real del banco.
        assert _normalize_image_path("/RVI9/020526/0004") == "RVI9/020526/0004"

    def test_leading_backslash_stripped_and_separator_normalized(self):
        assert _normalize_image_path("\\RVI9\\020526\\0004") == "RVI9/020526/0004"

    def test_double_leading_slash_stripped(self):
        assert _normalize_image_path("//RVI9/020526/0004") == "RVI9/020526/0004"

    def test_whitespace_stripped(self):
        assert _normalize_image_path("  /RVI9/020526/0004  ") == "RVI9/020526/0004"

    def test_empty_stays_empty(self):
        assert _normalize_image_path("") == ""

    def test_only_separators_becomes_empty(self):
        assert _normalize_image_path("///") == ""

    def test_internal_slashes_preserved(self):
        # No strippeamos en el medio — esos son separadores reales.
        assert _normalize_image_path("/a/b/c/d") == "a/b/c/d"
```

Y un test de integración mínimo que verifique que el
`RVABREPDocument` construido por `_row_to_document` tiene el
`image_path` normalizado:

```python
class TestRowToDocumentImagePath:
    def test_row_with_leading_slash_image_path_is_normalized(self):
        # Construir un mini IndexingService con cols default, pasar
        # una fila con ABAICD="/RVI9/...", aseverar que el
        # RVABREPDocument resultante tiene image_path sin leading /.
        ...
```

## Verificación E2E (informal, post-deploy)

Después del bump:

```powershell
git pull && pip install -e . --no-deps
cmcourier --version    # 0.77.0

cmcourier rvabrep-pipeline run `
  --config sample\config-prod-as400.yaml `
  --batch-id post-075-smoke `
  --total 5
```

El path resuelto debería ser
`sample\mockfiles\RVI9\020526\0004\<filename>` en vez de
`\RVI9\020526\0004\<filename>`.

## Phased commits

1. `feat: add 075 spec, plan, tasks`
2. `fix(indexing): normalize leading separators in RVABREP image_path (075)`
3. `test: cover image_path normalization`
4. `docs(075): CHANGELOG 0.77.0 + version bump`
