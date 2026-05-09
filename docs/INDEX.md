# CMCourier — Documentation Index

> The single map of every document in the project. Pick the quadrant that matches your intent and click through.

This index is **canonical**: every documentation artifact in the repository appears here. Subdirectory READMEs (under `docs/how-to/`, `docs/explanation/`) link back to this page for navigation.

The structure follows the [Diátaxis framework](https://diataxis.fr): documentation is split by *purpose* (learn / solve / look up / understand) rather than by topic.

---

## For everyone

| Document | Purpose |
|----------|---------|
| [`README.md`](../README.md) | Project overview, current status, getting started |
| [`CHANGELOG.md`](../CHANGELOG.md) | Versioned history (Keep a Changelog format) |
| [`CONTRIBUTING.md`](../CONTRIBUTING.md) | Workflow, commit standards, PR rules, SDD discipline |

## Engineering law

| Document | Purpose |
|----------|---------|
| [`.specify/memory/constitution.md`](../.specify/memory/constitution.md) | The 9 immutable principles. Specs and code that violate it are rejected without debate |

## Domain ground truth

| Document | Purpose |
|----------|---------|
| [`docs/domain/CMCOURIER_REBIRTH.md`](domain/CMCOURIER_REBIRTH.md) | Full domain specification — RVI source system, CMIS target system, RVABREP schema, stage architecture, metadata resolution, file assembly, idempotency, observability tiers |

## Project planning

| Document | Purpose |
|----------|---------|
| [`docs/roadmap/POST-MVP.md`](roadmap/POST-MVP.md) | Every feature deferred beyond the MVP, with intent + design + acceptance criteria |
| `specs/<NNN-feature-slug>/` | Per-change SDD artifacts (`spec.md`, `plan.md`, `tasks.md`, optionally `research.md` and `data-model.md`). One folder per change, append-only numbering |

## Reference data (samples from the legacy project)

| Document | Purpose |
|----------|---------|
| [`docs/samples/csv/`](samples/csv/) | Sample CSVs: `MapeoRVI_CM.csv` (Modelo Documental), `MetadatosCM.csv` (per-class metadata definitions), `TriggerExample.csv` (trigger list shape), and per-source metadata samples (`metadata_clients.csv`, `metadata_accounts.csv`, etc.) |
| [`docs/samples/excel/RVILIB_RVABREP.xlsx`](samples/excel/RVILIB_RVABREP.xlsx) | Real RVABREP table dump — column shape and example rows |
| [`docs/samples/responses/EjemploRespuestaCMIS.txt`](samples/responses/EjemploRespuestaCMIS.txt) | Real CMIS Browser Binding response example — useful when implementing the upload adapter |

## How to use (recipes — problem-oriented)

See [`docs/how-to/README.md`](how-to/README.md) for the index of how-to guides and the naming convention.

- *(none yet — this section grows as pipelines, the doctor command, and operator workflows ship)*

## How it works (explanations — understanding-oriented)

See [`docs/explanation/README.md`](explanation/README.md) for the index of explanations and the naming convention.

- *(none yet — this section grows as architectural concepts get standalone walkthroughs; the comprehensive explanation lives in `docs/domain/CMCOURIER_REBIRTH.md`)*

---

## Maintenance

This file is updated by **every change** that adds, moves, or renames a documentation artifact. The change's `tasks.md` includes a task to update this index. CONTRIBUTING.md documents that responsibility.

Future quadrants (deferred until natural content appears):

- **`docs/tutorials/`** — learning-oriented. Created when the first end-to-end walkthrough exists (likely when `rvabrep-pipeline` ships).
- **`docs/reference/`** — information-oriented. Created when the CLI command surface and config schema stabilize (post-MVP).
