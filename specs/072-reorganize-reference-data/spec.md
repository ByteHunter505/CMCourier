# 072 — Sacar reference data de `docs/`

## Por qué

`docs/samples/` está mezclando tres cosas conceptualmente distintas
bajo la misma carpeta, y eso viola un principio implícito: **`docs/`
es para leer, no para ser dependency runtime de código**.

Lo que vive hoy en `docs/samples/`:

| Path | Tamaño | Naturaleza real |
|------|--------|-----------------|
| `config-reference.yaml` | 24 K | **Documentación** (YAML anotado tipo reference) |
| `csv/` (8 archivos) | 68 K | **Fixtures**: `MapeoRVI_CM`, `MetadatosCM`, `ClaseDocumentalCM`, `TriggerExample`, 4 × `metadata_*.csv` |
| `excel/RVILIB_RVABREP.xlsx` | 20 K | **Fixture binaria**: volcado real de tabla AS400 |
| `responses/EjemploRespuestaCMIS.txt` | 4.2 M | **Fixture binaria**: response real de CMIS Browser Binding |
| `cmis_service.py` | 24 K | **Código legacy del proyecto viejo** (untracked, gitignored) |

El problema más serio: el **código de producción depende de la
ruta**. `src/cmcourier/cli/commands/mock.py:320` tiene:

```python
_DEFAULT_IDRVI_SOURCE = Path("docs/samples/csv/MapeoRVI_CM.csv")
```

Eso es un dato productivo que el CLI usa como default — no es
documentación. Si mañana movés o renombrás esa carpeta, `cmcourier
mock rvabrep` se rompe. Hoy `docs/` actúa como sample directory Y
como data directory Y como doc directory.

Ratificación durante el cambio:

* `config-reference.yaml` **sí es doc** — pasa a `docs/reference/`.
* Los fixtures de datos (CSVs, xlsx, response txt) **no son doc** —
  salen a `reference-data/` en la raíz.
* `cmis_service.py` es código legacy huérfano — se borra del disco.

## Qué

### Alcance

* **Nuevo directorio raíz**: `reference-data/` con subcarpetas
  `csv/`, `excel/`, `cmis-responses/`.
* **Movidos vía `git mv`** (preservar history):
  * `docs/samples/csv/`               → `reference-data/csv/`
  * `docs/samples/excel/`             → `reference-data/excel/`
  * `docs/samples/responses/`         → `reference-data/cmis-responses/`
  * `docs/samples/config-reference.yaml` → `docs/reference/config-reference.yaml`
* **Borrado**: `docs/samples/cmis_service.py` (ya untracked +
  gitignored — solo `rm` del filesystem).
* **`docs/samples/`**: eliminado (queda vacío después del move).
* **Código de producción**:
  * `src/cmcourier/cli/commands/mock.py:320` —
    `_DEFAULT_IDRVI_SOURCE` actualizado a
    `Path("reference-data/csv/MapeoRVI_CM.csv")`.
  * `src/cmcourier/cli/commands/mock.py:350` — string en `--help`
    actualizado al nuevo path.
* **Docs vivos** — actualizar referencias en (lista exhaustiva
  verificada con grep):
  * `docs/INDEX.md` (3 líneas)
  * `docs/reference/cli.md` (1 línea)
  * `docs/adr/007-csv-trigger-primary-source.md` (1 línea)
  * `docs/how-to/mock-rvabrep-generator.md` (2 líneas)
  * `docs/how-to/local-staging-simulation.md` (5 líneas)
  * `docs/how-to/developer/add-a-new-config-field.md` (1 línea)
  * `docs/tutorials/README.md` (1 línea)
  * `docs/tutorials/01-the-yaml-config.md` (3 líneas)
  * `docs/tutorials/05-doctor-deep-dive.md` (1 línea)
* **Constitution + skill registry**:
  * `.specify/memory/constitution.md` (2 líneas — mención de
    `docs/samples/` en Principio VIII y en sección de fixtures).
  * `.atl/skill-registry.md` (1 línea — convención de PII).
* **`.gitignore`**: remover entrada de
  `docs/samples/cmis_service.py` (la carpeta deja de existir).
* **CHANGELOG.md**: nueva entrada `[0.74.0]`.
* **pyproject.toml**: `version = "0.74.0"`.
* **Specs viejas**: NO se actualizan. Quedan con paths rotos como
  registro histórico — eso es Keep-a-Changelog para spec dirs.

### Fuera de alcance

* **No se renombran** los CSVs/xlsx por dentro. Los archivos
  mantienen sus nombres exactos.
* **No se reorganizan** dentro de `reference-data/`. El subdir
  layout es 1:1 con el que había en `docs/samples/` (excepto el
  rename `responses/` → `cmis-responses/` para ser explícito).
* **No se tocan los tests** — ningún test referencia
  `docs/samples/` (verificado con grep).

## Criterios de aceptación

1. `docs/samples/` no existe en HEAD.
2. `reference-data/{csv,excel,cmis-responses}/` existe con todo el
   contenido movido vía `git mv` (history preservado).
3. `docs/reference/config-reference.yaml` existe.
4. `cmcourier --version` imprime `0.74.0`.
5. `cmcourier mock rvabrep --help` muestra el nuevo path default
   en la línea de `--idrvi-source`.
6. `rg -F "docs/samples" src/ tests/ docs/ .specify/ .atl/` devuelve
   cero hits (verificación final).
7. `pytest -m unit` pasa.
8. Pre-commit hooks pasan limpios (ruff, ruff-format, mypy).

## Riesgos

* **Specs viejas con paths rotos** — aceptado. Son históricos. Si
  alguien lee `specs/001-bootstrap-python-skeleton/plan.md` y ve
  `docs/samples/csv/`, entiende contextualmente que era el path al
  momento de esa spec.
* **Bookmarks externos** — si algún operador tiene un bookmark a
  `docs/samples/csv/MapeoRVI_CM.csv` en su browser, se le rompe.
  No hay forma de redirigir sin agregar un README stub en
  `docs/samples/` — y eso resucita la carpeta. Aceptado.
* **CHANGELOG entries históricas** — mantienen los paths viejos.
  No se reescribe history.
