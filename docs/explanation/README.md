# Explanations — How CMCourier Works

> Understanding-oriented documentation. **"How does this work and why?"**

An explanation document is for the reader who already knows *what* CMCourier does and now wants to understand *how* and *why*. It can include design rationale, architectural diagrams, comparisons with alternatives, and historical context. It is the place to discuss tradeoffs and the reasoning behind decisions.

If you want practical step-by-step instructions, see [`../how-to/README.md`](../how-to/README.md). If you are looking up a specific fact (a column name, a config field), the future `docs/reference/` directory is the place.

---

## Canonical domain explanation

The single most important explanation document is **outside** this directory:

- **the project's domain spec** — comprehensive specification of the source and target systems, the RVABREP schema, the stage-based pipeline architecture, metadata resolution cascade, CMIS quirks, idempotency model, and observability tiers.

It stays where it is because moving it would invalidate cross-references in already-shipped artifacts (the constitution, CONTRIBUTING, plans). Treat it as canonical when no smaller explanation exists for the topic you care about.

---

## Naming convention

Files in this directory are named `<concept-slug>.md`. Slugs are kebab-case, descriptive, and stable. Renaming is a breaking change for external links — bump `CHANGELOG.md`.

Examples (illustrative, not currently shipped):

- `stage-architecture.md`
- `metadata-resolution-cascade.md`
- `cmis-session-warmup.md`
- `cyymmdd-date-format.md`
- `idempotency-and-the-tracking-store.md`
- `heavy-light-upload-lanes.md` *(post-MVP)*

---

## Available explanations

*(none yet — this section grows as architectural concepts deserve standalone walkthroughs beyond the domain spec)*

| Explanation | Concept | Depth |
|-------------|---------|-------|
| — | — | — |

---

## Writing a new explanation

When adding an explanation:

1. Pick a concept-noun slug. The reader is asking "how does X work?".
2. Open with the *problem* the concept solves. Why does it exist?
3. Walk through the concept, building from first principles. Diagrams, tables, code excerpts welcome.
4. Compare with alternatives where useful. Why this design and not another?
5. Cross-link to the relevant section of the constitution, the domain spec, or specs that codify the concept.
6. Add the explanation to the table above and to `docs/INDEX.md`.

An explanation is **not** a tutorial (no curated walkthrough), **not** a how-to (no practical steps), **not** a reference (not a dry list of facts). It is reasoning, expressed as prose the reader thinks alongside.

---

## Cross-references

- [`docs/INDEX.md`](../INDEX.md) — canonical map of all documentation
- [`docs/how-to/README.md`](../how-to/README.md) — for practical recipes
- the project's domain spec — canonical domain explanation
- [`.specify/memory/constitution.md`](../../.specify/memory/constitution.md) — engineering law (the *why* behind every architectural rule)
