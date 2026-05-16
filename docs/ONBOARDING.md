# Onboarding — CMCourier en 30 minutos

> [← Volver al índice](INDEX.md)

Llegaste nuevo al proyecto. Esta página te lleva de cero a "entiendo qué hace, entiendo cómo está armado, sé dónde mirar cuando tengo una pregunta" — en aproximadamente media hora de lectura activa.

No es un tutorial paso a paso (para eso tenés [tutorials/](tutorials/README.md)). Es un mapa mental.

---

## 1. Qué hace CMCourier en una frase

Migra documentos bancarios de un sistema legacy **IBM RVI sobre AS400** a **IBM Content Manager** vía la **API CMIS REST**. Lee triggers (qué documentos migrar) de un CSV externo, resuelve metadata, ensambla los archivos físicos (TIFFs → PDF), los sube vía CMIS, y registra cada paso en un tracking store SQLite para garantizar idempotencia.

Es un rewrite de un proyecto previo (`RVIMigration`) que se transformó en un God Object. CMCourier existe para que esa historia no se repita — y la `.specify/memory/constitution.md` codifica esa promesa.

---

## 2. Mapa de carpetas (5 minutos)

```
CMCourier/
├── src/cmcourier/         # El código
│   ├── cli/               # Click commands, entry point
│   ├── orchestrators/     # Coordinan stages (MultiBatch, Streaming)
│   ├── services/          # Lógica de negocio por stage
│   ├── domain/            # Modelos, ports (interfaces), exceptions
│   ├── adapters/          # I/O real: CMIS HTTP, SQLite, AS400, PDF
│   ├── config/            # Pydantic schema + env vars
│   ├── tui/               # Textual dashboard (5 tabs)
│   └── observability/     # Métricas, logs, samplers
├── tests/                 # unit/, integration/, e2e/
├── specs/                 # SDD artifacts por cambio (1 carpeta por spec)
├── docs/                  # Esto. INDEX.md es la entrada.
├── scripts/               # Scripts de staging, helpers
├── .specify/memory/       # constitution.md (ley de ingeniería)
└── pyproject.toml         # Dependencies, entry point, ruff/mypy/pytest config
```

**Regla de dependencias** (Constitution Principio I): `cli/ → orchestrators/ → services/ → domain/ ← adapters/`. Nunca al revés. `domain/` no importa nada externo, solo stdlib.

Si entendés ese diagrama, entendés el 80% de la arquitectura. El detalle profundo está en [explanation/architecture-overview.md](explanation/architecture-overview.md).

---

## 3. Mapa de stages — la vida de un documento (10 minutos)

Cada documento pasa por 8 stages (S0 a S7). Cuando alguien diga "se rompe en S4" o "el throughput está limitado por S5", ya sabés a qué se refiere.

| # | Nombre | Qué hace |
|---|--------|----------|
| S0 | Trigger acquisition | Lee el CSV/RVABREP/local-scan para saber qué procesar |
| S1 | Indexing | Querea RVABREP en AS400 (o CSV mirror) para obtener metadata RVI |
| S2 | Mapping | Convierte `ID RVI` → tipo de Content Manager + folder destino |
| S3 | Metadata resolution | Resuelve propiedades CMIS con cadena de fallback (trigger → CSV → AS400 → default) |
| S4 | Assembly | Toma los TIFFs/PDFs físicos del file server y arma el PDF final |
| S5 | Upload | POST multipart a CMIS Browser Binding |
| S6 | Tracking | Persiste el estado del documento en SQLite + opcionalmente NIARVILOG en AS400 |
| S7 | Idempotency marker | Verifica que un re-run no vuelva a subir lo ya subido |

Lectura recomendada: [explanation/pipeline-stages.md](explanation/pipeline-stages.md) — tiene el diagrama de secuencia completo.

---

## 4. Dos modos de ejecución

- **`batched`** (default) — usa `MultiBatchOrchestrator` con `batches_in_flight=2`: mientras el chunk N sube, el N+1 prepara.
- **`streaming`** (063) — usa `StreamingOrchestrator` con un `queue.Queue` acotado (`bucket_size`) como buffer producer-consumer. Memoria peak ~`bucket_size`, independiente del total de documentos.

Decidís en el YAML: `processing.mode: "batched"` o `"streaming"`. Para entender el tradeoff: [explanation/streaming-vs-batched.md](explanation/streaming-vs-batched.md).

---

## 5. Los 9 principios de la Constitution (5 minutos)

Leelos. Están en `.specify/memory/constitution.md`. Resumen:

1. **Hexagonal Architecture is Non-Negotiable** — dependency direction estricta.
2. **Idempotency is Sacred** — `rvabrep_txn_num` con UNIQUE constraint.
3. **Single Responsibility** — funciones ≤ 50 líneas. Sin excepciones.
4. **Streaming over Buffering** — multipart encoder, cursor streaming, file iteration.
5. **Configuration over Code** — un solo YAML, validado por Pydantic al startup.
6. **AS400 is Not Mocked** — el ODBC driver no es portable; CSVDataSource cubre dev/test.
7. **Spec-Driven Development** — sin spec en `specs/`, no se mergea código.
8. **No PII at INFO** — CIF, names, accounts: nunca a INFO o below.
9. **Verify Before Claiming** — "dejame verificar" supera a "claro que sí".

Estos principios no se debaten, se respetan. Si una decisión de diseño choca con uno, primero amendment a la Constitution (vía `.specify/amendments/`), después código.

---

## 6. Orden de lectura recomendado

Si tenés 30 minutos:

1. Este documento (estás acá).
2. [README.md](../README.md) raíz del proyecto.
3. [explanation/architecture-overview.md](explanation/architecture-overview.md).
4. [explanation/pipeline-stages.md](explanation/pipeline-stages.md).
5. `.specify/memory/constitution.md`.

Si tenés 2 horas, agregá:

6. [explanation/streaming-vs-batched.md](explanation/streaming-vs-batched.md).
7. [explanation/aimd-auto-tuning.md](explanation/aimd-auto-tuning.md).
8. [explanation/heavy-light-lanes.md](explanation/heavy-light-lanes.md).
9. Una corrida con el [tutorial 06-first-streaming-run](tutorials/06-first-streaming-run.md).

Si vas a contribuir código:

10. [contributing/code-style.md](contributing/code-style.md).
11. [contributing/spec-driven-flow.md](contributing/spec-driven-flow.md).
12. [contributing/testing-philosophy.md](contributing/testing-philosophy.md).

---

## 7. Setup local (en serio, 5 minutos)

```bash
git clone <repo> CMCourier && cd CMCourier
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pre-commit install
pytest -m unit  # smoke
cmcourier --help
```

Si algo falla: [tutorials/00-getting-started.md](tutorials/00-getting-started.md) tiene la versión detallada.

---

## 8. Tu primer cambio

Si te asignan un cambio, leé:

- [contributing/spec-driven-flow.md](contributing/spec-driven-flow.md) — el workflow SDD que usa este proyecto.
- [how-to/developer/](how-to/developer/README.md) — recetas para tareas comunes (agregar config field, agregar propiedad CMIS, etc).
- [reference/error-codes.md](reference/error-codes.md) — todas las exceptions con su trigger.

---

## 9. Dónde mirar cuando tenés una pregunta

| Tu pregunta | Andá a |
|-------------|--------|
| "¿Cómo corro esto?" | [tutorials/](tutorials/README.md) |
| "¿Cómo hago X?" | [how-to/](how-to/README.md) |
| "¿Qué hace este flag / campo / exception?" | [reference/](reference/README.md) |
| "¿Por qué está hecho así?" | [explanation/](explanation/README.md) o [adr/](adr/README.md) |
| "Se rompió en producción, ¿qué hago?" | [runbooks/](runbooks/README.md) |
| "¿Cuáles son las reglas?" | `.specify/memory/constitution.md` |
| "¿Qué cambió y cuándo?" | [CHANGELOG.md](../CHANGELOG.md) |
| Glosario | [reference/glossary.md](reference/glossary.md) |

---

## Ver también

- [INDEX.md](INDEX.md) — mapa completo de la documentación
- [contributing/code-style.md](contributing/code-style.md)
- [contributing/spec-driven-flow.md](contributing/spec-driven-flow.md)
- [contributing/testing-philosophy.md](contributing/testing-philosophy.md)
