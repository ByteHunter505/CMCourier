# CMCourier

> Migración de documentos bancarios de **IBM RVI / AS400** a **IBM Content Manager** vía **CMIS REST**. Idempotente, observable, parallelizable.

**Versión actual**: `0.73.0` — pipeline MVP de punta a punta, modo `streaming` listo, AIMD + lanes en producción, TUI live de 5 tabs.

```bash
$ cmcourier --help
$ cmcourier doctor --config config.yaml
$ cmcourier csv-trigger-pipeline run --config config.yaml --batch-id 2026-05-15-001
```

---

## Documentación

> **El mapa canónico está en [`docs/INDEX.md`](docs/INDEX.md).** Una sola página que te lleva a todo: tutoriales, recetas, referencia, arquitectura, runbooks y ADRs.

Atajos rápidos:

| Si querés... | Andá a |
|--------------|--------|
| Entender qué hace el proyecto en 30 min | [`docs/ONBOARDING.md`](docs/ONBOARDING.md) |
| Tu primera corrida de cero a producción | [`docs/tutorials/`](docs/tutorials/README.md) |
| Una receta para una tarea específica | [`docs/how-to/`](docs/how-to/README.md) |
| Consultar un flag, un campo de config, una exception | [`docs/reference/`](docs/reference/README.md) |
| Entender el **por qué** detrás del diseño | [`docs/explanation/`](docs/explanation/README.md) |
| Decisiones arquitectónicas con su contexto | [`docs/adr/`](docs/adr/README.md) |
| Apagar un fuego en producción | [`docs/runbooks/`](docs/runbooks/README.md) |
| Diagramas (Mermaid) | [`docs/diagrams/`](docs/diagrams/README.md) |
| Las reglas no negociables | [`.specify/memory/constitution.md`](.specify/memory/constitution.md) |
| Historial versionado | [`CHANGELOG.md`](CHANGELOG.md) |

---

## Qué hace

Cada documento del legacy IBM RVI atraviesa **8 stages atómicos** (S0–S7):

1. **S0 — Trigger** — leer un CSV/RVABREP/local-scan para saber qué procesar.
2. **S1 — Indexing** — querear RVABREP en AS400 (o su mirror CSV) para resolver metadata RVI.
3. **S2 — Mapping** — convertir el `ID RVI` a un tipo de Content Manager + folder destino.
4. **S3 — Metadata resolution** — resolver las propiedades CMIS con cadena de fallback configurable (trigger → CSV → AS400 → default).
5. **S4 — Assembly** — tomar los TIFFs/PDFs del file server y armar el PDF final.
6. **S5 — Upload** — POST multipart a CMIS Browser Binding, con HTTP/2, AIMD auto-tune y circuit breaker.
7. **S6 — Tracking** — persistir el estado en SQLite (WAL) + opcionalmente AS400 NIARVILOG.
8. **S7 — Idempotency marker** — garantizar que re-correr una migración nunca sube duplicados.

Detalle completo en [`docs/explanation/pipeline-stages.md`](docs/explanation/pipeline-stages.md).

---

## Características clave

- **Dos modos de ejecución**: `batched` (multi-batch overlap N=2) y `streaming` (producer-consumer con bucket acotado, memoria peak fija independiente del total). Ver [`streaming-vs-batched`](docs/explanation/streaming-vs-batched.md).
- **AIMD auto-tune** del pool S5: multiplicative growth (1.25×) + soft halve (0.75×) + tolerance threshold (1.5×). Recalibrado en spec 068 — alcanza techo en 2.5 min vs 11 min del aditivo. Ver [`aimd-auto-tuning`](docs/explanation/aimd-auto-tuning.md).
- **Heavy/light lanes**: dual semáforo en S5 para evitar head-of-line blocking entre docs grandes y chicos. Rebalance dirigido por drain. Ver [`heavy-light-lanes`](docs/explanation/heavy-light-lanes.md).
- **ProcessPool en S4**: PDF assembly bypassa el GIL con `multiprocessing.get_context("spawn")`. Default on. Ver [`processpool-for-pdf-assembly`](docs/explanation/processpool-for-pdf-assembly.md).
- **TUI live de 5 tabs** (PREP, UPLOAD, CHUNKS, BUCKET, DETAIL) construida en Textual. Throughput, p95, lanes, slow-ops, drill-down por documento.
- **HTTP/2 multiplexing** via `httpx[http2]` con ALPN — los N workers comparten conexión TCP.
- **Idempotencia cross-batch** garantizada por UNIQUE constraint en `(rvabrep_txn_num, batch_id)` + check `is_uploaded()` en S1 (marker `S1_SKIPPED`, spec 062).
- **Observabilidad por tiers**: app log (T1), pipeline metrics (T2), network events (T3), slow-ops aggregation (T4), system metrics via psutil (T5).
- **Pre-flight doctor**: 12+ checks (`connections`, `mapping`, `metadata`, `cm-targets`) antes de tocar producción.
- **PII masking** por defecto: CIF, account numbers, customer names nunca a INFO. Constitution Principle VIII.

---

## Arquitectura

**Hexagonal (Ports & Adapters)** con cuatro capas + dependencia direccional estricta:

```
cli/ → orchestrators/ → services/ → domain/ ← adapters/
```

- `domain/` — modelos, ports (interfaces), exceptions. **Cero dependencias externas.** Solo stdlib.
- `adapters/` — implementan ports. Único lugar donde vive el I/O (HTTP CMIS, ODBC AS400, SQLite, PDF).
- `services/` — lógica de negocio. Dependen de ports, nunca de adapters concretos.
- `orchestrators/` — coordinan services. Sin lógica de negocio, sin I/O directo.
- `cli/` — composition root. Instancia adapters concretos y los inyecta.

Diagrama: [`docs/diagrams/hexagonal-layers.md`](docs/diagrams/hexagonal-layers.md).
Profundidad: [`docs/explanation/architecture-overview.md`](docs/explanation/architecture-overview.md).
Ratificación: [`.specify/memory/constitution.md`](.specify/memory/constitution.md) Principio I.

---

## Stack técnico

| Capa | Tecnología |
|------|------------|
| Lenguaje | Python 3.11+ |
| Config | Pydantic v2 (validación en startup) |
| CLI | Click |
| AS400 | pyodbc + iSeries Access ODBC (conexiones thread-local) |
| HTTP | `httpx[http2]` (multiplexing CMIS) |
| CSV | pandas |
| Ensamblado PDF | img2pdf (fast) + Pillow + PyPDF2 (fallback) |
| Tracking | SQLite WAL + opcional AS400 NIARVILOG |
| TUI | Textual |
| Observabilidad | psutil (system metrics), structured JSON logs |
| Testing | pytest + pytest-cov (coverage ≥ 80%) |
| Lint / format | ruff |
| Type check | mypy --strict |
| Packaging | pyproject.toml (PEP 621) |

---

## Quickstart

### Pre-requisitos

- Python 3.11+ (verificado en 3.11 y 3.12)
- Compilador C + headers ODBC (`pyodbc` lo necesita):
  - **Linux** (Debian/Ubuntu): `sudo apt install build-essential unixodbc-dev`
  - **macOS**: `brew install unixodbc`
  - **Windows**: instalar el [IBM iSeries Access ODBC Driver](https://www.ibm.com/support/pages/ibm-i-access-client-solutions)
- Git

### Instalar (editable + dev tools)

```bash
git clone <repo> CMCourier
cd CMCourier
python3 -m venv .venv
source .venv/bin/activate          # Linux / macOS
# .venv\Scripts\activate            # Windows

pip install -e ".[dev]"
pre-commit install
pre-commit install --hook-type commit-msg
```

### Smoke test

```bash
pytest -m unit              # solo unit tests (rápidos)
cmcourier --help            # confirma que el CLI está instalado
cmcourier --version         # debe imprimir 0.73.0
```

### Variables de entorno (cuando corras migraciones reales)

Credenciales **siempre** en env, **nunca** en YAML committeado (Constitution Principles V/VIII):

```bash
export AS400_USERNAME="..."
export AS400_PASSWORD="..."
export CMIS_USERNAME="..."
export CMIS_PASSWORD="..."
```

### Tu primera corrida (mock + Alfresco staging)

Setup completo en [`docs/tutorials/00-getting-started.md`](docs/tutorials/00-getting-started.md). El recorrido por todos los comandos en [`docs/tutorials/04-all-commands-tour.md`](docs/tutorials/04-all-commands-tour.md).

---

## Tests

```bash
pytest                          # todo
pytest -m unit                  # unit (mockean ports)
pytest -m integration           # integration (real SQLite/CSV/Alfresco)
pytest -m "not slow"            # excluir tests lentos
pytest --cov src/cmcourier --cov-report=html
```

Filosofía completa: [`docs/contributing/testing-philosophy.md`](docs/contributing/testing-philosophy.md).

---

## Contribuir

CMCourier es **Spec-Driven**. Cada cambio funcional arranca con una spec bajo `specs/NNN-feature-slug/`. Sin spec, no se mergea código.

Lectura mínima antes de tu primer PR:

1. [`docs/ONBOARDING.md`](docs/ONBOARDING.md) — 30 min, mapa mental del proyecto.
2. [`.specify/memory/constitution.md`](.specify/memory/constitution.md) — los 9 principios inmutables.
3. [`docs/contributing/code-style.md`](docs/contributing/code-style.md) — convenciones de Python, naming, límites de tamaño.
4. [`docs/contributing/spec-driven-flow.md`](docs/contributing/spec-driven-flow.md) — el workflow SDD paso a paso.
5. [`docs/contributing/testing-philosophy.md`](docs/contributing/testing-philosophy.md) — TDD estricto, qué se mockea.
6. [`CONTRIBUTING.md`](CONTRIBUTING.md) — workflow git, conventional commits, reglas de PR.

**Reglas duras**:
- Funciones ≤ 50 líneas (Constitution III).
- Conventional Commits únicamente. Sin `Co-Authored-By`. Sin atribución a AI.
- Nunca `--no-verify`. Si un hook falla, arreglá la causa.
- `mypy --strict` debe pasar.
- Coverage ≥ 80% (`pyproject.toml [tool.coverage.report]`).

---

## Estado y roadmap

- [x] Pipeline MVP de punta a punta (csv-trigger, rvabrep, local-scan, single-doc)
- [x] CMIS Browser Binding + HTTP/2 + AIMD + lanes + circuit breaker
- [x] SQLite tracking + AS400 NIARVILOG distributed sync
- [x] TUI live de 5 tabs
- [x] Streaming orchestrator + ProcessPool S4
- [x] Pre-flight doctor + 12 checks
- [x] Mock data generator (`cmcourier mock`)
- [x] Smoke contra Alfresco 23.x (staging) sin failures
- [ ] Dry run con datos reales contra staging del banco
- [ ] Primera migración productiva

Roadmap completo de features diferidas: [`docs/roadmap/POST-MVP.md`](docs/roadmap/POST-MVP.md).

Historial detallado por versión: [`CHANGELOG.md`](CHANGELOG.md).

---

## Licencia

Por definir por el dueño del proyecto. Hasta entonces, tratá este repositorio como propietario — no distribuir sin permiso.
