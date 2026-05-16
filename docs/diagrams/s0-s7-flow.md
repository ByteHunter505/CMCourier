# Flujo S0 → S7

> [← Volver al índice](../INDEX.md) · [Diagramas](README.md)

Vida de un documento desde que un trigger lo nombra hasta que queda confirmado en Content Manager.

## Secuencia

```mermaid
sequenceDiagram
    autonumber
    participant CSV as CSV/RVABREP/local-scan
    participant S0 as S0 Trigger
    participant S1 as S1 Indexing
    participant S2 as S2 Mapping
    participant S3 as S3 Metadata
    participant S4 as S4 Assembly
    participant S5 as S5 Upload
    participant S6 as S6 Tracking
    participant TDB as Tracking DB (SQLite)
    participant CM as CMIS / Content Manager

    CSV->>S0: trigger (shortname, system_id, cif)
    S0->>S1: trigger
    S1->>S1: query RVABREP por shortname+system_id
    alt encontrado y no deleted
        S1->>TDB: is_uploaded(txn_num)?
        alt ya uploaded
            TDB-->>S1: yes
            S1->>S6: mark S1_SKIPPED
        else nuevo
            S1->>S2: RVABREPDocument
            S2->>S2: mapear ID RVI → CM type + folder
            S2->>S3: doc + cm_target
            S3->>S3: resolver propiedades (fallback chain)
            S3->>S4: doc + metadata
            S4->>S4: validar source files, assemble PDF
            S4->>S5: StagedFile + metadata
            S5->>CM: POST multipart
            CM-->>S5: cm_object_id
            S5->>S6: mark S5_DONE
            S6->>TDB: write
        end
    else not found / deleted / duplicate
        S1->>S6: mark error
        S6->>TDB: write
    end
```

## Tracking writes por stage

Cada transición persiste en `migration_log`:

```mermaid
stateDiagram-v2
    direction LR
    [*] --> S0_PENDING
    S0_PENDING --> S0_DONE
    S0_DONE --> S1_PENDING
    S1_PENDING --> S1_DONE
    S1_PENDING --> S1_SKIPPED: ya subido
    S1_DONE --> S2_PENDING
    S2_PENDING --> S2_DONE
    S2_PENDING --> S2_FAILED
    S2_DONE --> S3_PENDING
    S3_PENDING --> S3_DONE
    S3_PENDING --> S3_FAILED
    S3_DONE --> S4_PENDING
    S4_PENDING --> S4_DONE
    S4_PENDING --> S4_FAILED
    S4_DONE --> S5_PENDING
    S5_PENDING --> S5_DONE
    S5_PENDING --> S5_FAILED
    S5_DONE --> [*]
    S1_SKIPPED --> [*]
```

## Thread model por stage

| Stage | Dónde corre | Pool / mecanismo |
|-------|-------------|------------------|
| S0 | main / producer thread | iterator |
| S1, S2, S3 | prep workers (`processing.prep_workers`) | `ThreadPoolExecutor` |
| S4 | process pool (066, default on) | `ProcessPoolExecutor` con `spawn` |
| S5 | upload workers (AIMD-resizable, `cmis.workers`) | `ThreadPoolExecutor` + `ResizableSemaphore` |
| S6 | writer thread (daemon, SQLite WAL) | `queue.Queue` drain loop |

## Ver también

- [explanation/pipeline-stages.md](../explanation/pipeline-stages.md) — narrativa completa
- [state-machine.md](state-machine.md) — más detalle de estados
- [streaming-pipeline.md](streaming-pipeline.md) — vista de pipeline en modo streaming
- [reference/tracking-db-schema.md](../reference/tracking-db-schema.md)
