# Mapa de imports

> [← Volver al índice](../INDEX.md) · [Diagramas](README.md)

Quién importa a quién dentro de `src/cmcourier/`. Si una flecha apunta al "lado equivocado", es violación de la Constitution Principio I.

## Subdirectorios principales

```mermaid
flowchart TB
    subgraph cli["cli/"]
        APP[app.py]
        CMDS[commands/]
        TUIR[_tui_runner.py]
        DOC[doctor.py]
    end

    subgraph orch["orchestrators/"]
        STG[staged.py]
        MULT[multi_batch.py]
        STR[streaming.py]
    end

    subgraph svc["services/"]
        IDX[indexing.py]
        MAP[mapping.py]
        META[metadata.py]
        AT[auto_tune.py]
        LC[lane_controller.py]
        WPS[worker_pool_stats.py]
    end

    subgraph dom["domain/"]
        MOD[models.py]
        PRT[ports.py]
        EXC[exceptions.py]
    end

    subgraph adp["adapters/"]
        UP[upload/cmis_uploader.py]
        SRC[sources/tabular.py]
        SRCA[sources/as400.py]
        TRK[tracking/sqlite.py]
        TRKA[tracking/as400_niarvilog.py]
        ASM[assembly/pdf_assembler.py]
        POOL[assembly/pool.py]
    end

    subgraph tui["tui/"]
        TAPP[app.py]
        PREP[prep_tab.py]
        UPL[upload_tab.py]
        CHK[chunks_tab.py]
        BCK[bucket_tab.py]
        DET[detail_tab.py]
    end

    subgraph obs["observability/"]
        MET[metrics.py]
        SYS[system_metrics.py]
        PII[pii.py]
    end

    subgraph cfg["config/"]
        SCH[schema.py]
        ENV[env.py]
    end

    cli --> orch
    cli --> adp
    cli --> tui
    cli --> obs
    cli --> cfg
    cli --> svc

    orch --> svc
    orch --> dom

    svc --> dom

    adp --> dom

    tui --> obs
    tui --> svc

    obs -.> dom

    cfg --> dom
```

## Reglas visualizadas

- **`domain/` no tiene flechas salientes** (a otros módulos internos). Solo `from __future__ import annotations`, `dataclasses`, `enum`, `pathlib`, etc.
- **`services/` y `orchestrators/` apuntan a `domain/`**, nunca a `adapters/` o `cli/`.
- **`adapters/` apuntan a `domain/`** (implementan los ports). Nunca al revés.
- **`cli/` es el único que mezcla**: arma los adapters concretos, los inyecta en orchestrators y services.

## Cómo verificar

```bash
# importes desde domain hacia afuera deberían dar cero hits
rg "from cmcourier\.(adapters|services|orchestrators|cli|tui)" src/cmcourier/domain/

# importes de adapters concretos dentro de services
rg "from cmcourier\.adapters" src/cmcourier/services/

# Si cualquiera devuelve hits, hay violación.
```

## Ver también

- [hexagonal-layers.md](hexagonal-layers.md)
- [explanation/architecture-overview.md](../explanation/architecture-overview.md)
- [adr/001-hexagonal-architecture.md](../adr/001-hexagonal-architecture.md)
- [contributing/code-style.md](../contributing/code-style.md)
