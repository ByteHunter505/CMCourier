# Capas hexagonales

> [← Volver al índice](../INDEX.md) · [Diagramas](README.md)

CMCourier sigue Ports & Adapters. Cuatro capas, dependencia direccional estricta.

## Vista de capas

```mermaid
flowchart TB
    CLI["<b>cli/</b><br/>Click commands, entry point<br/>inyecta dependencias"]
    ORCH["<b>orchestrators/</b><br/>MultiBatch, Streaming, Staged<br/>coordinan stages"]
    SVC["<b>services/</b><br/>IndexingService, MappingService,<br/>MetadataService, AutoTuneController,<br/>LaneController"]
    DOM["<b>domain/</b><br/>models · ports · exceptions<br/>(stdlib only)"]
    ADP["<b>adapters/</b><br/>CMIS uploader · SQLite tracking ·<br/>CSV/AS400 sources · PDF assembler"]

    CLI --> ORCH
    ORCH --> SVC
    SVC --> DOM
    ADP --> DOM
    CLI -.crea.-> ADP

    style DOM fill:#fff4d6,stroke:#b8860b,stroke-width:2px
    style ADP fill:#e6f3ff,stroke:#4682b4
    style SVC fill:#f0f8e6,stroke:#6b8e23
    style ORCH fill:#fce4ec,stroke:#c2185b
    style CLI fill:#ede7f6,stroke:#673ab7
```

## Regla de dependencias

- **Solo flechas hacia abajo (o hacia domain).** `services/` nunca importa de `adapters/`. `orchestrators/` nunca importa adapters concretos.
- **`domain/` no importa nada externo.** Solo Python stdlib. Ni `pydantic`, ni `requests`, ni `pyodbc`. Nada.
- **`cli/` es el único que toca todo.** Es el composition root: ahí se instancian los adapters concretos y se inyectan.

## Lo que querés sentir cuando leés el código

| Síntoma | Diagnóstico |
|---------|-------------|
| `from cmcourier.adapters.X import Y` en un service | Violación. Refactorear vía port en `domain/`. |
| `import requests` en `services/` | Violación. Lo mismo. |
| `import pydantic` en `domain/` | Violación. Los modelos del dominio son dataclasses puras. |
| `from cmcourier.orchestrators.X import Y` en un adapter | Violación gigante. Sentido contrario. |

## Ver también

- [explanation/architecture-overview.md](../explanation/architecture-overview.md) — el "por qué"
- [adr/001-hexagonal-architecture.md](../adr/001-hexagonal-architecture.md)
- [Constitution Principio I](../../.specify/memory/constitution.md)
- [file-imports-map.md](file-imports-map.md)
