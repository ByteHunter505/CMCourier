# How-to Guides — Recipes for Specific Tasks

> Problem-oriented documentation. **"How do I…"**

A how-to guide assumes you already know what CMCourier is and want to accomplish a specific goal. It is a sequence of practical steps — no narrative, no deep explanation, no theory. If you want to *understand* how something works, see [`../explanation/README.md`](../explanation/README.md). If you are completely new to the project, start with the [main README](../../README.md) and the [INDEX](../INDEX.md).

---

## Naming convention

Files in this directory are named `how-to-<task-slug>.md` or simply `<task-slug>.md` if the verb is implicit. Slugs are kebab-case, descriptive, and stable. Renaming an existing guide is a breaking change for external links — bump `CHANGELOG.md`.

Examples (illustrative, not currently shipped):

- `run-rvabrep-pipeline.md`
- `configure-cmis-credentials.md`
- `recover-from-failed-batch.md`
- `add-a-new-trigger-source.md`
- `tune-worker-count-for-throughput.md`

---

## Available guides

*(none yet — this section grows as the first commands and pipelines ship)*

| Guide | Goal | Audience |
|-------|------|----------|
| — | — | — |

---

## Writing a new how-to

When adding a guide:

1. Pick a precise verb-based slug. The user is reading this because they want to *do* something.
2. Open with one sentence stating what the reader will accomplish.
3. List prerequisites (tools installed, env vars set, role / permissions).
4. Provide the steps as numbered list with copy-pasteable commands.
5. Close with a verification step — how does the reader know it worked?
6. Add the guide to the table above and to `docs/INDEX.md`.

A how-to is **not** a tutorial. Tutorials teach a concept by walking the reader through a curated example. How-tos solve a real-world problem the reader already has.

---

## Cross-references

- [`docs/INDEX.md`](../INDEX.md) — canonical map of all documentation
- [`docs/explanation/README.md`](../explanation/README.md) — for "how it works"
- [`docs/domain/CMCOURIER_REBIRTH.md`](../domain/CMCOURIER_REBIRTH.md) — domain ground truth
- [`CONTRIBUTING.md`](../../CONTRIBUTING.md) — workflow conventions
