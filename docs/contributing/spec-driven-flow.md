# Spec-Driven Development (SDD)

> [← Volver al índice](../INDEX.md) · [Contributing](README.md)

CMCourier no se desarrolla a tirones de PRs. Cada cambio sustantivo arranca con una **spec**, después un **plan**, después un **task breakdown**, y recién entonces el código. Esto es Constitution Principio VII y no se negocia.

Cambios chicos (typo, comentario, bump de version) no necesitan spec. Cambios funcionales, refactors estructurales, performance work — sí.

---

## El workflow en una página

```
1. /sdd-explore <topic>     ← investigar antes de comprometerse
2. /sdd-propose             ← intención + scope + approach
3. /sdd-spec                ← requisitos + escenarios (delta specs)
4. /sdd-design              ← decisiones técnicas
5. /sdd-tasks               ← breakdown ejecutable
6. /sdd-apply               ← implementar en batches (TDD)
7. /sdd-verify              ← validar contra spec
8. /sdd-archive             ← cerrar y persistir
```

Cada fase produce un artefacto en `specs/NNN-feature-slug/`:

```
specs/063-streaming-orchestrator/
├── spec.md          # requisitos + escenarios
├── plan.md          # decisiones técnicas
├── tasks.md         # checklist ejecutable con estado
└── (opcionales)
    ├── research.md
    └── data-model.md
```

---

## Numeración

`specs/` tiene numeración **append-only** de 3 dígitos. Si la última spec es `070-unify-lane-controller`, la próxima es `071-foo-bar`. Nunca renumerés.

El slug es kebab-case, descriptivo: `063-streaming-orchestrator`, `068-aimd-aggressive-scaling`.

---

## El ciclo de commits

Cada spec genera múltiples commits, fase por fase. La convención del repo es:

```
feat(<scope>): <subject> (NNN Phase X)
```

Donde `NNN` es el número de spec y `X` la fase (1, 2, 3...). Ejemplos reales:

```
refactor: remove legacy code-name references (071 Phase 1)
refactor: translate orchestrators + adapters to Spanish (071 Phase 2)
refactor: translate services/domain/config/cli/tui/observability to Spanish (071 Phase 3)
refactor: translate tests to Spanish (071 Phase 4)
docs: translate specs (partial) + CHANGELOG headers + README + docs/ to Spanish (071 Phase 5)
docs(071): CHANGELOG 0.73.0 + version bump (071 Phase 6)
```

La Phase 6 es siempre **CHANGELOG + version bump + `pip install -e . --no-deps`**.

---

## Versionado

Cada spec ship-eada bump-ea una versión menor.

```
0.72.0 → spec 070 archivada
0.73.0 → spec 071 archivada
```

`version` vive en `pyproject.toml`. El bump se hace en la última fase de la spec, junto al CHANGELOG.

---

## CHANGELOG

`CHANGELOG.md` sigue [Keep a Changelog](https://keepachangelog.com/). Cada release tiene:

```markdown
## [X.Y.0] — YYYY-MM-DD — Título corto del cambio

(prosa breve sobre el qué y el por qué)

### Agregado
- bullets

### Cambiado
- bullets

### Removido
- bullets

### Notas
- bullets
```

**No reescribas entries cerradas.** Si una decisión vieja se revierte, agregás una entry nueva con el cambio, no editás la histórica.

---

## TDD estricto (Strict TDD Mode)

Para specs que implementan código (no doc-only), el workflow es **Red → Green → Refactor**:

1. Test que falla por la razón correcta.
2. Mínimo código para pasarlo.
3. Refactor manteniendo tests verdes.

Sin test fallando primero, no se escribe producción. Ver [testing-philosophy.md](testing-philosophy.md).

---

## Quality gates por fase

Cada fase tiene un gate que cumplir antes de pasar a la siguiente:

| Fase | Gate |
|------|------|
| explore | Tradeoffs identificados, alternativas listadas |
| propose | Scope definido, no-goals explícitos |
| spec | Requisitos numerados, escenarios concretos |
| design | Decisiones con justificación, riesgos identificados |
| tasks | Cada task ≤ 1 hora, dependencies marcadas |
| apply | Tests pasan, mypy limpio, ruff limpio |
| verify | Todos los REQ-NNN de spec cubiertos por tests |
| archive | CHANGELOG + version bump committed, spec movida a archive |

---

## Si tu cambio no necesita spec

Estos cambios pueden ir como PR directo, sin SDD:

- Typo en doc o comentario.
- Reformatear bajo ruff format si el hook no lo agarró.
- Bump de version standalone.
- Update de dependency menor (parche o minor que no rompe API).

**Si dudás, hacé spec.** El costo de una spec mal-justificada es bajo; el costo de un cambio funcional sin spec es alto.

---

## Hands-on: tu primera spec

```bash
# 1. Decidí un slug y el siguiente número.
ls specs/ | tail -1   # ej: 071-translate-spanish

# 2. Creá la carpeta.
mkdir specs/072-mi-feature

# 3. Llamá al workflow SDD (si usás el plugin) o escribí los archivos a mano:
#    spec.md, plan.md, tasks.md.

# 4. Branch + implementación + commits convencionales.
git checkout -b 072-mi-feature

# 5. Al cerrar:
#    - bumpeá pyproject.toml version
#    - agregá entry al CHANGELOG.md
#    - .venv/bin/pip install -e . --no-deps
#    - cmcourier --version
#    - FF a main, sin push (a menos que el operador pida explícito)
```

---

## Ver también

- [code-style.md](code-style.md) — convenciones de código
- [testing-philosophy.md](testing-philosophy.md) — TDD estricto
- [Constitution Principio VII](../../.specify/memory/constitution.md)
- [`CONTRIBUTING.md`](../../CONTRIBUTING.md) raíz — workflow git/PR
