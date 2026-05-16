# 072 — Plan

## Decisiones técnicas

### Nombre del directorio: `reference-data/`

Tres alternativas consideradas:

* `fixtures/` — choca con `tests/fixtures/` (que ya existe para
  fixtures generadas dinámicamente). Confusión potencial.
* `data/reference/` — anidamiento extra sin justificación inmediata
  (no hay `data/staging/`, `data/prod/` planeado).
* `samples/` (en raíz) — preserva el nombre pero mantiene la
  ambigüedad: "sample" puede leerse como código de ejemplo,
  fixture, o input file.

Elegido `reference-data/` porque:

* "Reference" describe la naturaleza real: estos archivos son
  **referencias de shape del proyecto legacy** (estructura de la
  tabla NIARVILOG/RVABREP, formato de respuestas CMIS, columnas
  del Modelo Documental).
* Es distinto léxicamente de `tests/fixtures/`.
* Plural permite agregar otros tipos de reference data más
  adelante (ej. `reference-data/sql/` con queries históricas) sin
  reorganizar.

### Subcarpetas: 1:1 con renombrado mínimo

```
reference-data/
├── csv/                  ← era docs/samples/csv/
├── excel/                ← era docs/samples/excel/
└── cmis-responses/       ← era docs/samples/responses/
```

`responses/` → `cmis-responses/` porque "responses" en raíz es
demasiado genérico (¿AS400? ¿CMIS? ¿HTTP en general?). El prefijo
deja claro qué API es la fuente.

### `config-reference.yaml` se queda en `docs/`

Va a `docs/reference/config-reference.yaml`. Razón: es **doc
verdadera** (YAML anotado para humanos), no fixture. El operador
lo lee, no lo procesa el código.

### `cmis_service.py` se borra

Es un snippet legacy del proyecto viejo (RVIMigration). Ya está
untracked + gitignored. No tiene referencias en código. No es ni
doc ni fixture — es código histórico que sobrevivió por accidente.

Si en el futuro alguien necesita verlo: `git log --all --full-history
-- docs/samples/cmis_service.py` no lo va a encontrar (nunca
estuvo en git). El operador que lo dejó en su workspace ya tiene
el archivo localmente.

### Movimientos con `git mv` (no `mv`)

`git mv` preserva history: `git log --follow reference-data/csv/MapeoRVI_CM.csv`
sigue funcionando. `mv` + `git add` lo haría aparecer como
nuevo archivo, perdiendo blame para el operador.

### Update del default del CLI (mock.py)

Dos líneas:

```python
# antes
_DEFAULT_IDRVI_SOURCE = Path("docs/samples/csv/MapeoRVI_CM.csv")

# después
_DEFAULT_IDRVI_SOURCE = Path("reference-data/csv/MapeoRVI_CM.csv")
```

```python
# antes
"CSV with an IDRVI column (default: docs/samples/csv/MapeoRVI_CM.csv). "

# después
"CSV with an IDRVI column (default: reference-data/csv/MapeoRVI_CM.csv). "
```

Esto es una **breaking change para operadores que invoquen
`cmcourier mock rvabrep` sin `--idrvi-source`** desde un cwd que
no tenga `reference-data/`. Mitigación: cualquier operador
serio pasa `--idrvi-source` explícito. El default solo se usa en
smoke runs desde la raíz del repo.

### Specs viejas: no se tocan

Constitution implícita: **"specs son inmutables después de
archived"**. Si tocamos `specs/001/plan.md` cambiando un path,
estamos reescribiendo history. Aceptamos que un lector de spec
001 vea un path que ya no existe — el contexto del momento es lo
que importa.

### Phased commits

Para que el git log quede legible:

1. `feat: add 072 spec, plan, tasks` — solo specs/
2. `refactor: relocate reference data out of docs/` — git mv +
   mock.py update + .gitignore update
3. `docs: update path references to reference-data/` — todos los
   docs vivos + constitution + skill registry
4. `docs(072): CHANGELOG 0.74.0 + version bump` — CHANGELOG +
   pyproject.toml

Cada commit pasa pre-commit por sí solo. Si alguno falla, se
arregla y se crea commit nuevo (nunca amend).

## Verificación post-cambio

```bash
# 1. La carpeta vieja ya no existe
test ! -d docs/samples

# 2. La nueva existe con el contenido
ls reference-data/csv/MapeoRVI_CM.csv
ls reference-data/excel/RVILIB_RVABREP.xlsx
ls reference-data/cmis-responses/EjemploRespuestaCMIS.txt

# 3. El YAML está en docs/reference/
ls docs/reference/config-reference.yaml

# 4. Cero hits de la ruta vieja
rg -F "docs/samples" src/ tests/ docs/ .specify/ .atl/ README.md
# debe devolver cero líneas

# 5. Version + CLI funcional
.venv/bin/pip install -e . --no-deps
cmcourier --version       # 0.74.0
cmcourier mock rvabrep --help | grep idrvi-source
# debe mostrar el path nuevo

# 6. Smoke tests
pytest -m unit
```
