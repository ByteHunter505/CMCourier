# 075 — Normalizar `image_path` en IndexingService

## Por qué

El `ABAICD` (`image_path_column`) del RVABREP real del banco viene con
**leading forward-slash**: `/RVI9/020526/0004`. Es la convención de
paths que el sistema RVI heredado escribe — paths "absolutos" desde
la raíz del file share donde vive el archivo.

Pre-075 `services/indexing.py:269` lo toma tal cual:

```python
image_path=_str(row.get(cfg.image_path_column)),
```

Después `adapters/assembly/pdf_assembler.py:105` lo concatena con
`assembly.source_root`:

```python
src = self._cfg.source_root / doc.image_path / doc.file_name
```

Y acá entra el comportamiento documentado de `pathlib`: **cuando el
segundo operando es absoluto, el primero se descarta**.

```python
>>> Path("sample/mockfiles") / "/RVI9/020526/0004" / "DOC.001"
WindowsPath('/RVI9/020526/0004/DOC.001')   # source_root evaporado
```

Resultado: el assembler busca el archivo en el root del drive
(`C:\RVI9\020526\0004\DOC.001` en Windows, `/RVI9/020526/0004/DOC.001`
en Linux), **completamente ignorando `assembly.source_root`**. Para
el operador que está corriendo pruebas con archivos mockeados bajo
`sample\mockfiles\RVI9\...`, los archivos están físicamente donde
deberían pero el assembler los busca en otro lado.

Esto es la **misma clase de bug que 074** (CHAR padding) — un
detalle de representación AS400/RVI se cuela al dominio. El fix
sigue el mismo patrón: normalizar en la frontera entre
adapter/source y dominio.

> Nota: `services/mock/planner.py` ya tiene `normalize_image_path()`
> que justamente strippea leading separators y normaliza
> backslashes a forward slashes. El planner del **mock generate** lo
> usa al generar el árbol de archivos en disco — por eso los
> archivos mockeados quedan en el lugar "correcto" relativo al
> `--root`. El bug es que la **pipeline real** no aplica la misma
> normalización al leer del RVABREP. El mock generate y la pipeline
> real interpretan el mismo `ABAICD` de forma diferente.

## Qué

### Alcance

Normalizar `image_path` en `services/indexing.py:269` antes de
construir `RVABREPDocument`:

```python
# Antes
image_path=_str(row.get(cfg.image_path_column)),

# Después
image_path=_normalize_image_path(_str(row.get(cfg.image_path_column))),
```

Donde `_normalize_image_path` es un helper privado al módulo
`indexing.py` que hace:

1. Convierte backslashes a forward slashes (`"\\"` → `"/"`).
2. Strippea leading separators (`lstrip("/")`).
3. Strippea whitespace que haya quedado.

Esta es **exactamente la misma lógica** que `normalize_image_path`
del planner, pero devuelve `str` (no `Path`) para mantener el tipo
del field `RVABREPDocument.image_path: str`.

### Casos cubiertos por la normalización

| Input `ABAICD` | Después de normalizar |
|----------------|------------------------|
| `RVI9/020526/0004` | `RVI9/020526/0004` (pasa sin tocar) |
| `/RVI9/020526/0004` (el caso real) | `RVI9/020526/0004` |
| `\RVI9\020526\0004` (Windows-style) | `RVI9/020526/0004` |
| `//RVI9/020526/0004` (doble slash) | `RVI9/020526/0004` |
| ` /RVI9/020526/0004 ` (whitespace) | `RVI9/020526/0004` |

### Casos NO cubiertos (fuera de alcance — siguen rompiendo si aparecen)

* `C:\some\path` (drive letter explícito) — sigue siendo absoluto.
  Se decide caso por caso si el banco usa eso (raro en AS400).
* `\\server\share\path` (UNC) — `lstrip("/")` deja `server/share/path`,
  pero pierde la semántica UNC. En la práctica: si el RVI escribe
  UNC paths, el operador debe configurar `source_root` como la raíz
  del share y dejar el ABAICD relativo desde ahí.

Si alguno de los casos NO cubiertos aparece en producción, va a
otra spec.

### Decisión de no reutilizar el helper del planner

`services/mock/planner.normalize_image_path` devuelve `Path`.
Cambiar su return type rompería los tests del planner (varios
`assert ... == Path("...")`). Más limpio: duplicar 3 líneas de
lógica en un helper específico del IndexingService. Si en el
futuro aparece un tercer consumer, se centraliza.

## Criterios de aceptación

1. Un `RVABREPDocument` construido desde una fila con
   `ABAICD = "/RVI9/020526/0004"` queda con
   `image_path = "RVI9/020526/0004"`.
2. Un assembly de ese doc lee de
   `<source_root>/RVI9/020526/0004/<filename>`, no de
   `/RVI9/020526/0004/<filename>`.
3. Test unit que cubre los 5 casos de la tabla de arriba.
4. `pytest -m unit` pasa.
5. ruff + ruff-format + mypy verdes.

## Riesgos

* **Si un banco usa `\\server\share\...` (UNC)**: la normalización
  va a strippear los leading slashes y la semántica UNC se pierde.
  Mitigación: el operador configura `source_root: \\server\share`
  y `ABAICD` empieza con la sub-ruta. Si esto aparece, lo
  resolvemos en otra spec.
* **Tests de integración existentes** que asumen que `image_path`
  llega "tal cual" del RVABREP: revisar los fixtures. Si los
  fixtures usan paths relativos (lo normal), no cambia nada.
