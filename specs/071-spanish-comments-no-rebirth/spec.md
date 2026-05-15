# 071 — Comentarios en español + remoción del code-name antiguo

## Por qué

Cambio cosmético solicitado por el operador. Dos transformaciones en
una sola spec:

1. **Quitar todas las referencias al code-name antiguo** en código,
   specs, CHANGELOG y README. Pre-071 muchos docstrings citaban el
   code-name + sección (`§X.Y`) apuntando al doc de dominio bajo
   `docs/domain/`. Esa convención ya no es relevante — el operador
   quiere mantener el código autocontenido sin esa muleta.

2. **Traducir comentarios y docstrings a español**. Los nombres de
   variables, funciones, clases, módulos quedan en inglés (es lo
   que el operador prefiere — código en inglés, prosa en español).
   Términos técnicos sin traducción natural (`race condition`,
   `back-pressure`, `multipart`, `multiplexing`, `fan-out`, etc.)
   quedan entre backticks en inglés.

## Qué

### Alcance

* **Código**: todos los archivos `.py` en `src/cmcourier/` y `tests/`.
  ~184 archivos, ~44.000 líneas totales (estimo ~13.000 líneas son
  comentarios + docstrings).
* **Specs**: todos los directorios bajo `specs/` (~71 directorios,
  cada uno con spec.md, plan.md, tasks.md).
* **`CHANGELOG.md`**: entrada por entrada.
* **`README.md`**: todo el contenido.

### Convenciones

* **Docstrings de módulo**: en español. Primera línea = resumen
  corto, después detalles.
* **Docstrings de clase y función**: en español. Args / Returns /
  Raises (cuando existen) traducidos.
* **Comentarios in-line (`# ...`)**: en español.
* **Nombres de identificadores**: inglés (clases, funciones,
  variables, atributos, métodos, módulos, paquetes, parámetros).
* **Términos técnicos sin traducción natural**: backticks +
  inglés. Ejemplos: `back-pressure`, `race condition`, `fan-out`,
  `poison pill`, `multipart`, `multiplexing`, `keep-alive`,
  `chunked transfer encoding`, `connection pool`, `worker pool`,
  `thread pool`, `process pool`, `GIL`, `ALPN`, `pipe`, `bucket`.
* **Términos de dominio CMCourier**: pueden traducirse libremente
  o quedar como están si son más claros en inglés. Ejemplos:
  `chunk` → `chunk` o "lote"; `worker` → `worker` o "trabajador";
  `stage` → `stage` o "etapa". Se prefiere la forma que el
  operador usa en la conversación (español natural con backticks
  alrededor del término técnico cuando ayuda).
* **Identificadores entre backticks**: se mantienen tal cual
  (`StreamingOrchestrator`, `bucket_size`, `S5_DONE`, etc.).
* **Referencias al code-name antiguo + sección**: se eliminan
  completamente o se reemplazan por "el spec de dominio" / "la
  spec arquitectónica" cuando agregan contexto útil, o se borran
  cuando son ruido histórico.

### Lo que NO cambia

* Nombres de archivos, directorios, paquetes.
* Identificadores Python (variables, funciones, clases, módulos).
* Cadenas de texto a usuario final (CLI output, mensajes de log,
  excepciones) — quedan en inglés porque eso es lo que el
  operador ve hoy en producción.
* Identificadores en tests (`test_x_y_z` queda en inglés).
* Mensajes de commit y branches (convencional inglés).

### Estilo de traducción

* Voseo + rioplatense cuando ayude a sonar natural. Pero como
  son docstrings técnicos, generalmente neutro funciona mejor
  ("el método devuelve..." en lugar de "el método te devuelve...").
* Verbos en presente (la voz documental estándar).
* No traducir palabra-por-palabra: reescribir si el español
  natural difiere de la estructura inglesa.

## Plan de ejecución (6 fases)

Detalle en `plan.md`. Resumen:

1. **Fase 1**: Quitar las referencias al code-name antiguo en todos
   los archivos (search + replace controlado, ~109 menciones en
   código + las que haya en specs y docs). Una commit.
2. **Fase 2 (yo)**: Traducir `orchestrators/` y `adapters/` —
   código crítico con docstrings densos.
3. **Fase 3 (sub-agentes paralelo)**: `services/`, `domain/`,
   `config/`, `cli/`, `tui/`, `observability/`.
4. **Fase 4 (sub-agentes paralelo)**: `tests/`.
5. **Fase 5 (sub-agente)**: `specs/`, `CHANGELOG.md`, `README.md`.
6. **Fase 6**: Verificar (`pytest`, `ruff`, `mypy`), confirmar
   cero hits del code-name antiguo (case-insensitive grep debe dar
   cero), release dance (0.72.0 → 0.73.0), FF a main.

## Fuera de alcance

* Reescribir el contenido técnico de los docstrings — esto es solo
  traducción + remoción del code-name antiguo.
* Cambiar nombres de identificadores (clases, funciones, etc.).
* Reorganizar archivos.
* Cambios funcionales — cero cambios a la lógica.
* Tests nuevos.

## Criterios de aceptación

* Un grep case-insensitive del code-name antiguo en `src tests
  specs CHANGELOG.md README.md` retorna cero hits.
* Todos los docstrings y comentarios en `src/` y `tests/` están
  en español (revisión visual + spot-checks).
* `pytest tests/unit tests/integration -q` verde — cero cambios
  funcionales.
* `ruff check` y `mypy src` limpios.
* `CHANGELOG.md [0.73.0]` describe el refactor cosmético.
* `pyproject.toml` 0.72.0 → 0.73.0.
* FF a main.
