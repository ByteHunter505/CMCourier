# CMCourier — Project Rebirth Document

> Comprehensive context document for the rewrite of the RVI Migration Tool as **CMCourier**.
> This file is intentionally exhaustive — it is the single source of truth for picking up the project cold in a new session, in a new repository, with a new agent.

---

## 1. Executive Summary

**CMCourier** is a complete rewrite of an existing tool called `RVIMigration`. The original tool migrates documents from a legacy IBM document management system (RVI) hosted on IBM AS400/IBM i, into a modern IBM Content Manager (CM) repository accessed via the CMIS REST API.

The original project works for some flows but suffered from architectural drift — a 1341-line `pipeline.py` God Object, broken `run()` method due to a bad refactor, and tangled responsibilities across services. Rather than refactor incrementally, the decision was made to rebuild from scratch with **hexagonal architecture** (ports & adapters) while preserving all the hard-won domain knowledge, CMIS integration learnings, and battle-tested config schema.

The rewrite is a **green field code-wise**, but a **brown field domain-wise**. The business rules, the API integration quirks, the file formats, and the data sources are all known and documented in this file.

---

## 2. Business Context — What This Tool Actually Does

### 2.1 The Source System: RVI

**RVI** (acronym likely for *Real Vision* or similar — the exact full name is fuzzy but does not matter for the migration) is a legacy document management system from IBM that runs on **AS400** (also branded **IBM i**, **iSeries**, or **System i**). It has been in production at the bank for years and contains all historical client documentation.

**How RVI stores documents** — and this is the critical part:

1. **The catalog lives on AS400**. There is a master indexing table called `RVABREP` inside the `RVILIB` library. Every document, regardless of how many pages it has, has exactly one row in `RVABREP`.

2. **The actual files live on a Windows file server**, NOT on the AS400. The AS400 only stores metadata pointers.

3. **Multi-page documents are stored page by page as separate files**. If a document has 540 pages, there are 540 individual files on the file server: `DAAAH9X4.001`, `DAAAH9X4.002`, ... `DAAAH9X4.540`. These are typically TIFF, JPEG, or other image formats.

4. **Some documents are native PDFs**. These have a single `.PDF` extension: `0AAAUI0K.PDF`.

5. **The web portal assembles PDFs on demand**. When a banking employee opens a document through the RVI web portal, the application:
   - Looks up the row in `RVABREP`
   - Locates all the page files on the file server
   - Sorts them numerically
   - Converts each image to a PDF page
   - Merges them into a single PDF
   - Streams it to the browser

   The user never sees that there are 540 separate files — they see one PDF. This is the user-facing illusion that this migration must replicate when uploading to the new system.

### 2.2 The Target System: IBM Content Manager (CM)

**IBM Content Manager** is the modern destination. It is a CMIS-compliant content repository (CMIS = Content Management Interoperability Services, an OASIS standard).

**How documents must be uploaded**:

1. **Always as a single assembled PDF**. No page-by-page uploads. The migration must reproduce the assembly that the RVI web portal does today.

2. **Native PDFs go up as-is**. No conversion or assembly needed.

3. **Through the CMIS REST API (Browser Binding)**, not through any IBM SDK. The integration is pure HTTP multipart.

4. **With proper metadata properties** mapped to the CM document class.

5. **Inside specific folders** that follow a `/$type/BAC_XX_XX_XX_XX_XX` hierarchy derived from a mapping table.

### 2.3 The Migration's Job

The tool's job, end to end, is:

1. **Discover** which clients/documents to migrate (the *trigger list*)
2. **Index** — for each client, look up all their documents in RVABREP
3. **Map** each document's RVI type code to a Content Manager document class (folder + object type + required metadata)
4. **Resolve metadata** — for each document, gather the values for each required metadata field by querying multiple sources (AS400 tables, CSV files, the document's own indices)
5. **Assemble** the PDF (merge pages or pass through native PDFs)
6. **Upload** to Content Manager via CMIS with metadata
7. **Track** what was uploaded so it never gets uploaded twice (idempotency)

---

## 3. The AS400 Domain — RVABREP Table Schema

This is the most important data structure in the entire system. Every document has exactly one row here.

### 3.1 Connection Parameters

- **Library**: `RVILIB`
- **Main table**: `RVILIB.RVABREP`
- **Connection**: ODBC via `iSeries Access ODBC Driver` (Windows-only, IBM proprietary)
- **Default port**: `446`
- **Driver is NOT thread-safe** — must use thread-local connections
- **Python library**: `pyodbc`

### 3.2 RVABREP Columns — Field by Field

| Column | Internal Name | Meaning | Example | Notes |
|--------|---------------|---------|---------|-------|
| `ABAACD` | `system_code` | System Code | `"1"`, `"5"` | Groups documents by product/system; matches `TriggerRecord.system_id` |
| `ABAANB` | `txn_num` | Transaction Number | `"123456789"` | **Unique document ID. Primary key for tracking and idempotency.** |
| `ABABCD` | `index1` | Index 1 = ShortName | `"JUANPEREZ01"` | Client identifier; matches `TriggerRecord.shortname` |
| `ABACCD` | `index2` | Index 2 = CIF (often) | `"123456"` | Customer ID, typically 6-digit numeric |
| `ABADCD` | `index3` | Index 3 | varies | Domain-specific |
| `ABAECD` | `index4` | Index 4 | varies | Domain-specific |
| `ABAFCD` | `index5` | Index 5 | varies | Domain-specific |
| `ABAGCD` | `index6` | Index 6 | varies | Domain-specific |
| `ABAHCD` | `index7` | **ID RVI** | `"FF17"`, `"FB01"` | **Document type code. Join key into Modelo Documental mapping.** |
| `ABABST` | `image_type` | Image Type code | `"B"`, `"O"`, `"C"` | Maps to MIME type: B=tiff, O=pdf, C=jpeg |
| `ABAICD` | `image_path` | Path on file server | `"PROD/1999/01/15"` | Relative path; appended to file_server.base_path |
| `ABAJCD` | `file_name` | Physical file name | `"DAAAH9X4.540"` or `"0AAAUI0K.PDF"` | The page-numbered file or native PDF |
| `ABAADT` | `creation_date` | Creation Date | `"1251117"` | **CYYMMDD format — see below** |
| `ABABDT` | `last_view_date` | Last View Date | `"1251020"` or `"0"` | `"0"` if never viewed |
| `ABABUN` | `total_pages` | Total Pages | `540` | For paged documents; 1 for native PDFs |
| `ABACST` | `delete_code` | Delete Code | `""` or `"D"` | **Non-empty = deleted. Must be excluded from migration.** |

### 3.3 The CYYMMDD Date Format

AS400 dates use a 7-digit format that you cannot find in standard libraries.

- **C** = century flag: `0` = 1900s, `1` = 2000s
- **YY** = year within century (00-99)
- **MM** = month (01-12)
- **DD** = day (01-31)

**Example**: `1251117` = `1` (2000s) + `25` (year 2025) + `11` (November) + `17` (day) = **November 17, 2025**

```python
def parse_cymmdd(date_str: str) -> Optional[datetime]:
    if len(date_str) != 7:
        return None
    century = int(date_str[0])
    year = (1900 + century * 100) + int(date_str[1:3])
    return datetime(year, int(date_str[3:5]), int(date_str[5:7]))
```

### 3.4 The File Naming Convention

Documents come in two flavors:

**Paged documents** — multiple files per document:
```
DAAAH9X4.001    ← page 1 (TIFF/JPEG/etc)
DAAAH9X4.002    ← page 2
...
DAAAH9X4.540    ← page 540
```

The portion before the dot (`DAAAH9X4`) is the *file code*. The numeric extension is the page number, **with variable padding**:
- `.1`, `.2`, ... `.9` (single digit)
- `.01`, `.02`, ... `.99` (zero-padded double)
- `.001`, `.002`, ... (zero-padded triple)
- `.1000`, `.1001`, ... (no padding for 4+)

You cannot rely on padding consistency — use `int(extension)` to sort.

**Native PDFs** — single file:
```
0AAAUI0K.PDF
```

Detection rule: `file_name.upper().endswith('.PDF')`

`RVABREP.ABAJCD` always references the FIRST page of a paged document or the only file of a native PDF.

---

## 4. The Modelo Documental — Document Class Mapping

The **Modelo Documental** is a separate mapping table (CSV or AS400) that translates an RVI document type code into a Content Manager document class with its folder, object type, and required metadata fields.

### 4.1 Structure

| Field | Description | Example |
|-------|-------------|---------|
| `ID CLASE DOCUMENTAL` | Hierarchical ID | `"01.02.04.01.01"` |
| `ID RVI` | Join key against `RVABREP.ABAHCD` | `"FF17"` |
| `ID Corto` | Short ID | `"PT57"` |
| `CLASE DOCUMENTAL` | Human-readable class name | `"Autorizacion SMS"` |
| `METADATOS` | Comma-separated list of required metadata fields | `"CIF, NUM_CUENTA_TARJETA, Nombre_Cliente"` |

### 4.2 Computed CM Fields

From `clase_id`, two CM-specific values are computed:

```python
normalized = clase_id.replace('.', '_')
# "01.02.04.01.01" → "01_02_04_01_01"
cm_folder      = f"/$type/BAC_{normalized}"      # "/$type/BAC_01_02_04_01_01"
cm_object_type = f"$t!-2_BAC_{normalized}v-1"    # "$t!-2_BAC_01_02_04_01_01v-1"
```

These are passed to CMIS as the destination folder and the `cmis:objectTypeId`.

### 4.3 Duplicate Handling

If the same `ID RVI` appears multiple times in the mapping (it does — the source data has dupes), **take the first occurrence and ignore the rest**. This is a hard requirement from the business.

---

## 5. The Trigger List

The **trigger list** is the input that drives the migration. It's a 3-column dataset that says "process these clients".

```
ShortName     | CIF     | SystemID
--------------|---------|----------
JUANPEREZ01   | 123456  | 1
MARIAGOMEZ02  | 234567  | 5
...
```

- **ShortName** identifies the client in RVI (matches `RVABREP.ABABCD`)
- **CIF** is the customer number (sometimes missing — see CIF resolution below)
- **SystemID** is the product system code (matches `RVABREP.ABAACD`)

### 5.1 Trigger Source Modes

The tool supports **four** input modes for the trigger list. This was a major source of complexity in the old code and must be designed cleanly with a Strategy pattern from day one.

| Mode | Source | Use case |
|------|--------|----------|
| `csv:alias` | A CSV file | Testing, controlled batches |
| `as400:alias` | A custom SQL query against AS400 | Production, dynamic discovery |
| `direct_rvabrep` | Discover triggers by querying RVABREP directly | Filter-driven runs (e.g., all docs of type FF17) |
| `local_scan` | Scan a local folder for files, cross-reference RVABREP | Migrating files already extracted to disk |

For `direct_rvabrep` and `local_scan`, the CIF is resolved from a secondary **CIF lookup source** — typically a CSV mapping ShortName → CIF, or an AS400 client table.

---

## 6. Metadata Resolution — The Fallback Chain

For each document, the tool must resolve values for every metadata field listed in its Modelo Documental entry. This is the most complex part of the business logic.

### 6.1 The BAC_ Naming Convention

All metadata fields used in IBM Content Manager are prefixed `BAC_` (the bank's namespace).

| Friendly name | CM property ID |
|---------------|----------------|
| `BAC_CIF` | `clbNonGroup.BAC_CIF` |
| `BAC_Nombre_Cliente` | `clbNonGroup.BAC_Nombre_Cliente` |
| `BAC_Shortname` | `clbNonGroup.BAC_Shortname` |
| `BAC_Num_Cuenta` | `clbNonGroup.BAC_Num_Cuenta` |
| `BAC_Num_Cuenta_Tarjeta` | `clbNonGroup.BAC_Num_Cuenta_Tarjeta` |
| `BAC_Fecha_Firma` | `clbNonGroup.BAC_Fecha_Firma` |

The `clbNonGroup.BAC_*` is what the CMIS API actually wants. The `BAC_*` is the friendly name used internally and in config.

### 6.2 Field Aliases

The Modelo Documental's `METADATOS` column may use names like `CIF`, `NUM_PRESTAMO`, `Fecha_Firma`. These need to be normalized to `BAC_CIF`, `BAC_Num_Cuenta`, `BAC_Fecha_Firma` via a **`field_aliases`** map in config:

```yaml
field_aliases:
  CIF: "BAC_CIF"
  NUM_PRESTAMO: "BAC_Num_Cuenta"
  NUM_CUENTA_TARJETA: "BAC_Num_Cuenta_Tarjeta"
  Fecha_Firma: "BAC_Fecha_Firma"
  # ... case-insensitive matching too
```

### 6.3 The Fallback Chain (Per Field)

For each `BAC_*` field, config defines an ordered list of sources to try:

```yaml
metadata:
  BAC_CIF:
    sources:
      - source: "rvabrep"            # Try the document's own index2
        lookup_value_column: "index2"
        validation:
          allowed_pattern: "^\\d{6}$"   # Must be exactly 6 digits
      - source: "trigger"            # Then try the trigger record
        lookup_value_column: "cif"
        validation:
          allowed_pattern: "^\\d{6}$"
    default_value: "000000"          # Last resort if all sources fail validation
```

**Resolution order**:
1. Walk the `sources` list in order
2. For each source, try to fetch the value
3. Validate the value (regex, type, length, allowed pattern, date format)
4. If valid → use it, stop
5. If all sources fail → fall back to `default_value` (which **must also pass validation**)
6. If `default_value` is missing or fails validation → raise `MetadataError`

### 6.4 Source Types

| Source string | Behavior |
|---------------|----------|
| `"rvabrep"` | Read from `RVABREPDocument` attribute (e.g., `index2`, `txn_num`) |
| `"trigger"` | Read from `TriggerRecord` attribute (e.g., `cif`, `shortname`) |
| `"csv:alias"` | CSV lookup: `WHERE lookup_key_column = ?` returning `lookup_value_column` |
| `"as400:alias"` | Run `as400_query` with the lookup key as a `?` parameter |

### 6.5 The CIF Self-Healing Quirk

CIF is the most important lookup key — it's used as the parameter for many other AS400 queries (`Nombre_Cliente`, `Num_Cuenta`, etc.). But `TriggerRecord.cif` is sometimes empty (especially in `local_scan` mode).

**Critical rule**: Before resolving the field loop, if `trigger.cif` is empty, resolve `BAC_CIF` first and write the resolved value back into `trigger.cif`. Only then iterate the rest of the metadata fields. The same applies to `trigger.shortname` if missing.

This was a recent fix in the old codebase and is essential.

### 6.6 Metadata Pre-fetching (Performance Critical)

Resolving metadata one document at a time would do tens of thousands of AS400 queries for a large migration. Instead, the system **pre-fetches** entire AS400 tables into an in-memory cache at startup.

**Strategy**:
1. At pipeline start, scan all `metadata.*.sources` configurations
2. Group by `(alias, table_name)` — extract table from the SQL `FROM` clause
3. For each table, run `SELECT lookup_key, value_columns... FROM table` once
4. Store in cache with key format: `row:{TABLE}:{KEY_VALUE}:{COLUMN}` → value
5. During resolution, point queries hit the cache instead of the network

**Safeguards**:
- Skip pre-fetch for tables in `metadata_prefetch_exclude` (e.g., RVABREP itself, which is huge)
- Skip pre-fetch if `COUNT(*) > metadata_prefetch_max_rows` (default 50,000)
- TTL refresh after `metadata_cache_ttl_minutes` (default 60)

---

## 7. PDF Assembly — File Service Logic

### 7.1 Native PDF Path

```python
if document.is_pdf:
    # Just copy to temp dir and return
    shutil.copy2(file_path, f"{temp_dir}/{txn_num}.pdf")
```

### 7.2 Paged Document Path

```python
# 1. List all files matching FILECODE.* in source_dir
# 2. Filter to numeric extensions (skip .PDF, etc.)
# 3. Sort by int(extension) — handles variable padding
# 4. Try img2pdf fast path: convert(list_of_paths) → bytes → file
# 5. If fast path fails (mixed PDF+image pages), fall back to:
#    - Pillow Image.save() per page → individual PDFs
#    - PyPDF2 PdfMerger to combine
```

### 7.3 The img2pdf Fast Path

`img2pdf.convert(page_files)` accepts a list of image paths and produces a multi-page PDF in one shot, in-memory, lossless. **This is dramatically faster** than the Pillow + PdfMerger fallback. Always try this path first; only fall back when there are mixed image+PDF pages.

### 7.4 Temp Directory Trap

**Do not use `./tmp` as the temp dir on Windows machines that have OneDrive sync.** OneDrive locks files for syncing and creates I/O conflicts that destroy throughput.

```python
# Diversion logic from the old code
if temp_dir in ("./tmp", "tmp", ".\\tmp", "tmp\\"):
    temp_dir = os.path.join(tempfile.gettempdir(), "rvi_migration_tmp")
```

Use the system temp directory (`%TEMP%` on Windows) — it's on the local disk, fast, and not synced.

### 7.5 Image Type → MIME Type Mapping

```yaml
image_types:
  mapping:
    B: "image/tiff"
    O: "application/pdf"
    C: "image/jpeg"
```

Used as a hint for img2pdf but it auto-detects from file content anyway. Default fallback: `application/octet-stream`.

---

## 8. IBM CMIS Browser Binding — The Upload Protocol

This is **the most quirky part** of the entire system. IBM Content Manager exposes CMIS Browser Binding (REST/JSON), but with several IBM-specific behaviors that aren't in the standard documentation.

### 8.1 Connection Parameters

```yaml
cmis:
  base_url: "http://10.41.47.144:9080/opencmcmis/browser"
  repo_id: "$x!icmnlsdb_cmis"      # YES, the dollar sign is real
  username: "..."
  password: "..."
  timeout_seconds: 300
  verify_ssl: false
```

### 8.2 Mandatory Session Warmup

**Before any POST, you MUST do a GET to establish a JSESSIONID cookie.**

```
GET {base_url}/{repo_id}?cmisselector=repositoryInfo
```

The response sets a `JSESSIONID` cookie. Subsequent POSTs will fail with HTTP 401 if you skip this. The original code learned this the hard way.

**Per thread**: Each worker thread maintains its own `requests.Session` with its own warmed-up cookie. Use thread-local storage.

### 8.3 Folder Creation

**URL format**:
```
POST {base_url}/{repo_id}/root/{folder_path}
```

**Multipart body**:
```
cmisaction        = "createFolder"
propertyId[0]     = "cmis:objectTypeId"
propertyValue[0]  = "cmis:folder"
propertyId[1]     = "cmis:name"
propertyValue[1]  = "<folder_segment>"
```

**Recursive creation**: Walk the path from root, creating each segment. Skip system folders that start with `$` (like `$type`) — those always exist and trying to create them returns errors.

**HTTP 409 (Conflict)**: Treat as success — it means another thread created the folder concurrently.

**Cache locally**: Maintain an in-memory `set` of created folder paths. Once you've created or verified a folder, never check it again.

### 8.4 Document Upload

**URL format**:
```
POST {base_url}/{repo_id}/root/{cm_folder}
```

**Multipart body**:
```
cmisaction        = "createDocument"
propertyId[0]     = "cmis:objectTypeId"
propertyValue[0]  = "$t!-2_BAC_01_02_04_01_01v-1"
propertyId[1]     = "cmis:name"
propertyValue[1]  = "0AAAUI0K.pdf"
propertyId[2]     = "cmis:contentStreamMimeType"
propertyValue[2]  = "application/pdf"
propertyId[3]     = "clbNonGroup.BAC_CIF"
propertyValue[3]  = "123456"
propertyId[4]     = "clbNonGroup.BAC_Nombre_Cliente"
propertyValue[4]  = "JUAN PEREZ"
... etc ...
content           = (filename, <file stream>, mime_type)
```

### 8.5 Streaming Uploads

**Do NOT load the entire PDF into memory before posting.** Use `requests-toolbelt`'s `MultipartEncoder` for streaming:

```python
from requests_toolbelt import MultipartEncoder

with open(file_path, "rb") as f:
    fields = {**form_data}
    fields["content"] = (document_name, f, mime_type)
    m = MultipartEncoder(fields=fields)
    response = session.post(url, data=m, headers={"Content-Type": m.content_type})
```

A 540-page TIFF document can be hundreds of MB. Loading it into memory crushes the worker.

### 8.6 Bandwidth Limiting

A `BandwidthLimiter` class wrapping the file stream throttles read rate using a token bucket. Configurable via `cmis.max_bandwidth_mbps` (`0.0` = unlimited). Important for shared corporate networks where you can't saturate the link.

### 8.7 Retry Policy

| HTTP | Behavior |
|------|----------|
| `201` | Success — parse `cmis:objectId` from response |
| `401` | Session expired — re-warmup, retry |
| `409` | Conflict (folder creation only) — treat as success |
| `4xx` (other) | Bad request — do NOT retry, fail fast, log full payload as curl-equivalent for debugging |
| `5xx` | Server error — exponential backoff retry |
| `ConnectionError 10053` | Windows abort — server/network congestion. Use **double the normal retry delay**, log as ERROR, the issue is usually too many concurrent threads. |

### 8.8 Parsing the Object ID

The `objectId` lives in different places depending on the response shape:

```python
data = response.json()
# Try succinct properties first (most common)
if "succinctProperties" in data:
    return data["succinctProperties"]["cmis:objectId"]
# Fall back to standard properties
if "properties" in data:
    return data["properties"]["cmis:objectId"]["value"]
# Last resort
return str(data.get("id", "unknown"))
```

---

## 9. Idempotency & Tracking

The migration **must be safely re-runnable**. If it's interrupted, restarting must skip everything already uploaded. If a network blip causes a partial batch, retrying must not duplicate uploads.

### 9.1 The Tracking Store

The original system supports two backends:

- **SQLite** (default, recommended for development and most production scenarios)
- **AS400** (for environments where the bank wants tracking centralized in the legacy system)

The tracking store implements a single interface — both backends are interchangeable.

### 9.2 SQLite Schema (Reference)

```sql
CREATE TABLE migration_log (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    trigger_shortname TEXT NOT NULL,
    trigger_cif       TEXT NOT NULL,
    trigger_system_id TEXT NOT NULL,
    rvabrep_txn_num   TEXT NOT NULL,
    rvabrep_file_name TEXT NOT NULL,
    cm_object_id      TEXT,
    cm_folder         TEXT,
    cm_object_type    TEXT,
    status            TEXT NOT NULL DEFAULT 'PENDING',
    error_message     TEXT,
    source_file_path  TEXT,
    page_count        INTEGER,
    file_size_bytes   INTEGER,
    started_at        TIMESTAMP,
    completed_at      TIMESTAMP,
    retry_count       INTEGER DEFAULT 0,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(rvabrep_txn_num)              -- This is the idempotency anchor
);

CREATE TABLE migration_batch (
    batch_id        TEXT UNIQUE NOT NULL,
    started_at      TIMESTAMP,
    completed_at    TIMESTAMP,
    total_records   INTEGER DEFAULT 0,
    uploaded        INTEGER DEFAULT 0,
    failed          INTEGER DEFAULT 0,
    skipped         INTEGER DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'RUNNING'
);

-- For the 3-phase pipeline (resolve metadata → assemble → upload)
CREATE TABLE preprocess_staging (
    batch_id            TEXT NOT NULL,
    rvabrep_txn_num     TEXT NOT NULL,
    cm_folder           TEXT,
    cm_object_type      TEXT,
    metadata_json       TEXT,
    staged_file_path    TEXT,
    staged_file_size    INTEGER,
    page_count          INTEGER,
    status              TEXT NOT NULL DEFAULT 'PENDING',
    -- ...
    UNIQUE(rvabrep_txn_num, batch_id)
);

-- Cross-mode reuse cache: if metadata was resolved in mode A,
-- mode B can reuse it without re-querying AS400
CREATE TABLE document_cache (
    rvabrep_txn_num   TEXT PRIMARY KEY,
    metadata_json     TEXT,
    cm_folder         TEXT,
    cm_object_type    TEXT,
    staged_file_path  TEXT,
    staged_file_size  INTEGER,
    page_count        INTEGER,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 9.3 SQLite Performance Tuning

```sql
PRAGMA journal_mode = WAL;        -- Concurrent readers + one writer
PRAGMA synchronous = OFF;         -- Don't fsync after every write (acceptable for tracking)
PRAGMA cache_size = -64000;       -- 64MB memory cache
```

### 9.4 Async Write Queue

To avoid lock contention from many worker threads writing to SQLite simultaneously, the original system uses a **single background writer thread** that consumes a queue:

```
Worker threads → put (sql, params) → queue
                                      ↓
                               Writer thread (single)
                                      ↓
                              Batch up to 500 items
                                      ↓
                              Single commit per batch
```

This is a major performance win and should be preserved.

### 9.5 Status State Machine

```
PENDING → PROCESSING → UPLOADED
                    ↘
                     FAILED → (retry → PROCESSING)
                    ↘
                     SKIPPED  (already uploaded)
```

For the 3-phase pipeline:

```
PENDING → METADATA_RESOLVED → ASSEMBLED → UPLOADING → UPLOADED
                                       ↘            ↘
                                       FAILED      FAILED
```

---

## 10. Stage-Based Pipeline Architecture

The system is built as **composable atomic stages**, not as a fixed set of "execution modes". Every operational flow is a specific composition of stages applied to a batch of documents. Stages are first-class entities with explicit inputs, outputs, and failure semantics; pipelines are named compositions exposed as CLI commands.

This replaces the old mental model of "Mode A / Mode B / Mode C" — each of those was a different composition, but the composition was hidden inside imperative code. By making stages explicit we gain: stage-by-stage resumability, granular failure diagnosis, deterministic batch behavior, and trivial composition of new pipelines.

### 10.1 The Atomic Stages

Every pipeline is built from these stages:

| Stage | Name | Input | Output | Failure mode |
|-------|------|-------|--------|--------------|
| **S0** | Trigger Acquisition | Source descriptor (CSV path, SQL, folder, RVABREP filter) | `Iterable<TriggerRecord>` | Source unreachable, malformed input |
| **S1** | RVABREP Indexing | `TriggerRecord` | `List<RVABREPDocument>` | Record not found, duplicate matches, deleted (`ABACST != ""`) |
| **S2** | Document Class Mapping | `RVABREPDocument.id_rvi` | `CMMapping` (cm_folder + cm_object_type + required_metadata_fields) | `ID RVI` not in Modelo Documental |
| **S3** | Metadata Resolution | `RVABREPDocument` + `CMMapping` | `ResolvedMetadata` (dict of `BAC_*` → value) | All sources failed AND default invalid |
| **S4** | File Verification & Assembly | `RVABREPDocument` | `StagedFile` (path + size_bytes + page_count) | Source files missing, assembly failure |
| **S5** | Upload | `StagedFile` + `CMMapping` + `ResolvedMetadata` | `CMObjectId` | CMIS error, retry budget exhausted |
| **S6** | Tracking *(transversal)* | Stage outcome (any of S0–S5, S7) | Persisted state in tracking store | DB write failure (logged, never blocks pipeline) |
| **S7** | Cleanup | `StagedFile` | (deleted from temp) | I/O error (logged, non-fatal) |

**Why S2 is separate from S3**: a missing mapping (`ID RVI` not registered in Modelo Documental) is a different operational problem than a missing metadata value (CIF unresolved). Separating them gives the operator clearer diagnosis and lets the `doctor` command (§10.5) report each class of problem independently.

**Why S6 is transversal**: tracking is invoked after every stage's success or failure to update per-document state. It is not serial; failures in S6 must never block the pipeline.

**Why S7 is explicit**: bundling cleanup into S5 loses temp files when S5 fails partially. Explicit S7 ensures cleanup happens both on success and on graceful pipeline shutdown.

### 10.2 Pipelines as CLI Commands

A **pipeline** is a named, ordered subset of stages applied to a batch. **Each pipeline is its own CLI command**, never a config flag. This is a deliberate departure from the old `datasource_mode` config field.

| Pipeline | Stages | Use case |
|----------|--------|----------|
| `rvabrep-pipeline` | `S0(direct_rvabrep) → S1 → S2 → S3 → S4 → S5 → S7` | Production: discover documents by RVI filter (e.g., all `FF17` in system `1`) and process end-to-end |
| `csv-trigger-pipeline` | `S0(csv) → S1 → S2 → S3 → S4 → S5 → S7` | Controlled batches: explicit list of clients from CSV |
| `as400-trigger-pipeline` | `S0(as400) → S1 → S2 → S3 → S4 → S5 → S7` | Production: trigger list comes from a custom AS400 query |
| `local-scan-pipeline` | `S0(local_scan) → S1 → S2 → S3 → S4 → S5 → S7` | Files already extracted to disk; cross-reference RVABREP for metadata |
| `single-doc` | `S1 → S2 → S3 → S4 → S5 → S7` (one shortname/system) | Debugging, ad-hoc operator pushes |

S6 is implicit and runs after every other stage in every pipeline.

Adding a new pipeline = adding a new command that composes existing stages. No changes to stage internals required.

### 10.3 Stage-by-Stage Execution and Resume

Any pipeline can be invoked at full speed (all stages back-to-back) or stage-by-stage on a previously-prepared batch. This generalizes the old "3-phase pipeline" mode to all pipelines.

```
cmcourier rvabrep-pipeline run --batch-size 1000             # full run, all stages
cmcourier rvabrep-pipeline run --batch <id> --stage S3       # only S3 on existing batch
cmcourier rvabrep-pipeline run --batch <id> --from S3        # S3 onward (resume from S3)
cmcourier rvabrep-pipeline run --batch <id> --resume         # auto-resume from last successful stage
```

**Per-stage state machine** in tracking (one row per document per batch):

```
S1_PENDING → S1_DONE → S2_PENDING → S2_DONE → S3_PENDING → S3_DONE
          ↘                      ↘                      ↘
        S1_FAILED              S2_FAILED              S3_FAILED

(continues through S5_DONE)
```

A stage processes only documents in `Sn_PENDING` for the given batch. Documents in `Sn_FAILED` are surfaced for explicit retry (`cmcourier batch retry-failed --batch <id> --stage Sn`).

### 10.4 Batch as First-Class

All pipelines process documents in **configurable batches** (default 1000 per batch). Default batch size lives **per pipeline** in config — different pipelines have different optimal sizes (a `local-scan-pipeline` may want 100, a `rvabrep-pipeline` may want 1000+).

**Two batches are kept in flight at any time**: one being uploaded (S5 active) and one being prepared (S0–S4 active for the next batch). This producer-consumer model maintains throughput by overlapping I/O-bound preparation with network-bound upload.

**Why batch-then-upload (instead of streaming each doc through to upload)**:
- The full size distribution of the batch is visible before upload begins, enabling the future heavy/light lane scheduler (§10.7) to make informed decisions.
- Pre-flight validation (§10.5) can run on the full batch and abort cheaply if the batch is unprocessable.
- Failure mode is predictable: a metadata-resolution failure in document 999 of 1000 surfaces during prep, not after 998 successful uploads.

### 10.5 Pre-Flight Validation

Before any pipeline executes, automatic pre-flight validation runs unless `--skip-doctor` is passed. The same validation logic is exposed as the standalone `cmcourier doctor` command for ad-hoc operator use.

Validation checks:

1. **Connectivity**: AS400 reachable + sample query OK; CMIS reachable + `repo_id` valid + JSESSIONID warmup OK
2. **Mapping completeness**: every `ID RVI` that will appear in the upcoming batch has a mapping in Modelo Documental
3. **CM type alignment**: for each unique CM class in the batch, the `cm_object_type` exists in CM (CMIS `getTypeDefinition`); required metadata fields per CM are all present in our config; warn on extra fields config that CM does not expect
4. **Metadata source health**: for each metadata field, at least one source responds; if a `default_value` is defined, it must pass its own validation regex
5. **Sample dry-run**: take the first document of the batch and process it through S1–S4 without uploading; surface any error early

Pre-flight failures abort the pipeline before any side effect. The `doctor` command runs the same checks against arbitrary batches or globally.

### 10.6 TUI by Default

Every pipeline displays a Rich TUI with two switchable tabs:
- **PREP tab**: live progress of S0–S4 on the batch being prepared (per-stage progress bars, error rate, current operation)
- **UPLOAD tab**: live progress of S5 on the batch being uploaded (workers active, throughput, p95 latency, slow uploads)

The exception is `cmcourier background` — file-logging only, no TUI, designed to run unattended (cron, scheduled task, supervised service).

### 10.7 Adaptive Heavy / Light Upload Lanes (Post-MVP)

A future enhancement splits S5 into two adaptive worker pools:
- **Heavy lane**: few workers, large files
- **Light lane**: many workers, small files
- Lanes share total worker budget; rebalance dynamically based on queue depth

This solves head-of-line blocking when a batch contains a heterogeneous file size distribution. Detailed design and acceptance criteria live in `docs/roadmap/POST-MVP.md §1`.

**MVP behavior**: a single S5 worker pool with N configurable workers, no size-aware scheduling.

---

## 11. CLI Surface

Top-level command structure under `cmcourier`. Each pipeline is a first-class command; utility commands live alongside.

```
cmcourier
│
├── doctor [--check connections|mapping|metadata|cm-types|all]
│       Pre-flight validation (§10.5). Same checks as automatic
│       pre-flight, runnable standalone for operator triage.
│
├── rvabrep-pipeline run [--batch-size N | --batch <id> [--stage Sn | --from Sn | --resume]] [--skip-doctor]
├── csv-trigger-pipeline run    [...same flags...]
├── as400-trigger-pipeline run  [...same flags...]
├── local-scan-pipeline run     [...same flags...]
├── single-doc <shortname> <system_id>
│       Pipelines (§10.2). All accept stage-by-stage / resume flags.
│       TUI on by default; --no-tui for headless.
│
├── background --pipeline <name> --batch-size N
│       Same pipelines, but no TUI. Designed for unattended execution
│       (cron, scheduled task, supervised service).
│
├── batch
│   ├── list [--status <status>]               # Show batches and their state
│   ├── show <id>                              # Detailed batch state with per-stage counts
│   ├── retry-failed --batch <id> [--stage Sn] # Reset FAILED → PENDING for retry
│   └── export-report --batch <id> --format csv|json
│
├── inspect
│   ├── trigger [--source <descriptor>]        # Preview first N triggers from any source
│   ├── document <shortname> <system_id>       # Preview RVABREP records for one client
│   ├── mapping <id_rvi>                       # Show CM mapping for an ID RVI
│   └── mapping-stats                          # Modelo Documental summary
│
└── as400-query "SQL"
        Raw debug query against AS400.
```

All commands accept `--config / -c` to override the config file path. `doctor` is invoked automatically before any pipeline run unless `--skip-doctor` is passed.

---

## 12. Configuration Specification

**File**: `config/config.yaml` — single source of truth, validated by Pydantic at startup.

The original `config.yaml` is well-designed and **must be copied verbatim** to the new project. Below is the complete shape annotated with intent:

```yaml
# Registry of named connections — referenced everywhere as "type:alias".
# Note: there is no global `datasource_mode` flag. Each pipeline command
# selects its own source explicitly (§10.2), and per-field metadata sources
# are listed in `metadata.<field>.sources` below.
datasources:
  as400:
    default:                        # Alias name; can have multiple aliases
      host: "10.x.x.x"
      port: 446
      database: "RVILIB"
      username: ""                  # Override via env: AS400_USERNAME
      password: ""                  # Override via env: AS400_PASSWORD
      driver: "iSeries Access ODBC Driver"
  csv:
    trigger_list: "./data/trigger_list.csv"
    clients: "./data/metadata_clients.csv"
    rvabrep_export: "./data/rvabrep_export.csv"
    modelo_doc: "./data/modelo_documental.csv"
    accounts: "./data/metadata_accounts.csv"
    cards: "./data/metadata_cards.csv"
    dates: "./data/metadata_dates.csv"

# Step 1: Where the trigger list comes from
trigger:
  source: "csv:trigger_list"        # csv:alias | as400:alias | direct_rvabrep | local_scan
  as400_query: "SELECT SHORTNAME, CIF, SYSTEMID FROM RVILIB.TRIGGER_TABLE"
  local_scan_path: "./data/mock_images"
  col_shortname: "ShortName"
  col_cif: "CIF"
  col_system_id: "SystemID"
  cif_lookup:                       # For modes where CIF must be resolved
    source: "csv:clients"
    as400_query: "SELECT SHORT_NAME, CIF FROM SYSTEM.TABLE WHERE SHORT_NAME = ?"
    match_column: "Short_Name"
    return_column: "CIF"
  filters:
    systems: []                     # e.g., ["1", "5"]
    document_types: []              # e.g., ["FF17", "AA01"]

# Step 2: RVABREP source + column name mapping
rvabrep:
  source: "csv:rvabrep_export"
  as400_table: "RVILIB.RVABREP"
  columns:
    ABAACD: "ABAACD"   # System Code
    ABAANB: "ABAANB"   # Transaction Number
    ABABCD: "ABABCD"   # Index 1
    ABACCD: "ABACCD"   # Index 2
    # ... rest of the columns ...

# Step 3: Tracking backend
tracking:
  backend: "sqlite"                 # sqlite | as400:alias
  sqlite_path: "./data/migration_tracking.db"
  as400_library: "RVILIB"
  as400_table: "MIGRATION_LOG"
  as400_batch_table: "MIGRATION_BATCH"

# Step 4a: Mapping (Modelo Documental)
mapping:
  source: "csv:modelo_doc"
  as400_table: ""
  col_clase_id: "ID CLASE DOCUMENTAL"
  col_id_rvi: "ID RVI"
  col_id_corto: "ID Corto"
  col_clase_name: "CLASE DOCUMENTAL"
  col_metadata_list: "METADATOS"

# Step 4b: Metadata pre-fetch + field aliases + per-field source rules
metadata_prefetch: true
metadata_cache_ttl_minutes: 60
metadata_prefetch_max_rows: 50000
metadata_prefetch_exclude: ["RVABREP"]
metadata_prefetch_skip_count: false

field_aliases:
  CIF: "BAC_CIF"
  Nombre_Cliente: "BAC_Nombre_Cliente"
  Short_Name: "BAC_Shortname"
  ShortName: "BAC_Shortname"
  NUM_PRESTAMO: "BAC_Num_Cuenta"
  NUM_CUENTA_TARJETA: "BAC_Num_Cuenta_Tarjeta"
  Fecha_Firma: "BAC_Fecha_Firma"
  # ... all variants the source data might use ...

metadata:
  BAC_CIF:
    sources:
      - source: "rvabrep"
        lookup_value_column: "index2"
        validation: { allowed_pattern: "^\\d{6}$" }
      - source: "trigger"
        lookup_value_column: "cif"
        validation: { allowed_pattern: "^\\d{6}$" }
    default_value: "000000"
  BAC_Nombre_Cliente:
    sources:
      - source: "as400:default"
        as400_query: "SELECT NOMBRE FROM RVILIB.CLIENT_TABLE WHERE CIF = ?"
        lookup_key_column: "CIF"
        lookup_value_column: "Nombre_Cliente"
      - source: "csv:clients"
        lookup_key_column: "CIF"
        lookup_value_column: "Nombre_Cliente"
  # ... more fields ...

# Steps 5-6: File server + image type → MIME mapping
file_server:
  base_path: "./mock_files"
  is_local: true
  path_separator: "/"

image_types:
  mapping:
    B: "image/tiff"
    O: "application/pdf"
    C: "image/jpeg"

# Step 7: CMIS / IBM Content Manager
cmis:
  base_url: "http://10.41.47.144:9080/opencmcmis/browser"
  repo_id: "$x!icmnlsdb_cmis"
  username: ""                      # env: CMIS_USERNAME
  password: ""                      # env: CMIS_PASSWORD
  timeout_seconds: 300
  verify_ssl: false
  max_bandwidth_mbps: 0.0           # 0 = unlimited
  property_catalog:
    BAC_CIF: "clbNonGroup.BAC_CIF"
    BAC_Nombre_Cliente: "clbNonGroup.BAC_Nombre_Cliente"
    BAC_Shortname: "clbNonGroup.BAC_Shortname"
    BAC_Num_Cuenta: "clbNonGroup.BAC_Num_Cuenta"
    BAC_Num_Cuenta_Tarjeta: "clbNonGroup.BAC_Num_Cuenta_Tarjeta"
    BAC_Fecha_Firma: "clbNonGroup.BAC_Fecha_Firma"

# Concurrency + retries
processing:
  batch_size: 100
  thread_count: 20
  discovery_worker_ratio: 25        # 1 discovery thread per N processing threads
  temp_dir: "./tmp"
  max_retries: 3
  retry_delay_seconds: 5
  progress_log_interval: 50
  cleanup_temp_files: true
  auto_tune:                        # Adaptive thread count via AIMD (optional)
    enabled: false
    min_threads: 2
    max_threads: 50
    target_p95_ms: 5000.0
    adjustment_interval_s: 30
    warmup_seconds: 60
    timeout_auto_adjust: true
    min_timeout_s: 30
    max_timeout_s: 600

# 3-phase pipeline staging
preprocess:
  staging_dir: "./staging"
  max_files_per_folder: 1000
  as400_staging_table: "PREPROC_STG"
  as400_batch_table: "PREPROC_BATCH"

# Logging
logging:
  level: "INFO"
  log_dir: "./logs"
  max_log_size_mb: 50
  backup_count: 10
  log_format: "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
  interactive_filter:
    show_metadata_details: false
    show_upload_start: true
    show_upload_result: true
    show_progress_logs: false
```

**Environment variable overrides** (already implemented in original schema, must preserve):
- `AS400_USERNAME`, `AS400_PASSWORD` → datasources.as400.default.{username,password}
- `CMIS_USERNAME`, `CMIS_PASSWORD` → cmis.{username,password}

---

## 13. Bugs in the Current Codebase (For Reference Only)

Documenting these so they don't reappear in the rewrite.

### Bug 1 — Critical: `pipeline.run()` is broken

In `core/pipeline.py`, `scan_and_resolve()` was inserted in the middle of `run()`'s body. The `run()` method effectively ends after `prefetch_all()` (line ~111) and returns `None`. The threading/discovery/worker code (lines ~218-468) is unreachable dead code inside `scan_and_resolve()` after its return statement. There's even a comment `# ... in run() ...` at line ~308 confirming where it was supposed to be.

**Affected commands**: `background`, `migrate-batch`, `speed-test`, `retry-failed` — all fail silently.

### Bug 2: `scan_and_resolve()` calls non-existent methods

```python
self.tracking_store.stage_for_upload(...)   # Not in TrackingStore
self.tracking_store.update_batch_count(...) # Not in TrackingStore
```

### Bug 3: `preview_mapping` references non-existent attributes

In `cli/interactive.py`:
```python
mapping.primary_keys     # Doesn't exist on CMMapping
mapping.other_metadata   # Doesn't exist on CMMapping (only metadata_fields)
```

### Bug 4: `mark_preprocess_failed` SQL references wrong column

In SQLite tracking store:
```sql
UPDATE preprocess_staging SET status='FAILED', preprocessed_at=?
```
The column is named `metadata_resolved_at` / `assembled_at` / `uploaded_at` — there is no `preprocessed_at`. This update will throw at runtime.

---

## 14. Proposed Architecture for CMCourier

### 14.1 Hexagonal Architecture (Ports & Adapters)

```
┌──────────────────────────────────────────────────────────────────┐
│                            CLI (cli/)                            │
│         Click commands, dashboard UI, logging setup              │
└─────────────────────────────┬────────────────────────────────────┘
                              │ injects dependencies into
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│                   Orchestrators (orchestrators/)                 │
│   Thin coordinators. NO business logic. NO direct I/O.           │
│   ─ batch.py         (Mode A: parallel batch with workers)       │
│   ─ phases.py        (Mode B: 3-phase pipeline)                  │
│   ─ single.py        (Mode C: one document)                      │
└─────────────────────────────┬────────────────────────────────────┘
                              │ uses
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│                       Services (services/)                       │
│   Stateful services with caching/prefetch. Pure logic.           │
│   ─ trigger.py       (Strategy pattern for 4 source modes)       │
│   ─ document.py      (RVABREP query + batch fetch)               │
│   ─ mapping.py       (Modelo Documental cache)                   │
│   ─ metadata.py      (Prefetch + fallback chain + validation)    │
└─────────────────────────────┬────────────────────────────────────┘
                              │ depends on (via interfaces)
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│                          Domain (domain/)                        │
│   ─ models.py        (TriggerRecord, Document, CMMapping, ...)   │
│   ─ ports.py         (Abstract interfaces — IDataSource, ...)    │
│   ─ exceptions.py    (Typed error hierarchy)                     │
│   NO external dependencies. Pure Python.                         │
└──────────────────────────────────────────────────────────────────┘
                              ▲
                              │ implements
┌─────────────────────────────┴────────────────────────────────────┐
│                       Adapters (adapters/)                       │
│   Concrete implementations of the ports.                         │
│   ─ sources/as400.py     (IDataSource via pyodbc)                │
│   ─ sources/csv.py       (IDataSource via pandas)                │
│   ─ tracking/sqlite.py   (ITrackingStore + WAL + async writer)   │
│   ─ tracking/as400.py    (ITrackingStore via pyodbc)             │
│   ─ assembly/pdf.py      (IAssembler via img2pdf + Pillow)       │
│   ─ upload/cmis.py       (IUploader via requests + toolbelt)     │
└──────────────────────────────────────────────────────────────────┘
```

### 14.2 Project Layout

```
cm-courier/
├── README.md
├── CLAUDE.md                          # Domain knowledge (this doc, condensed)
├── pyproject.toml                     # Modern Python packaging
├── requirements.txt
├── docker-compose.yml                 # Alfresco for integration tests (optional)
│
├── src/cmcourier/                     # All code under one importable package
│   ├── __init__.py
│   ├── domain/
│   │   ├── __init__.py
│   │   ├── models.py
│   │   ├── ports.py
│   │   └── exceptions.py
│   ├── adapters/
│   │   ├── __init__.py
│   │   ├── sources/
│   │   │   ├── as400.py
│   │   │   └── csv.py
│   │   ├── tracking/
│   │   │   ├── sqlite.py
│   │   │   └── as400.py
│   │   ├── assembly/
│   │   │   └── pdf.py
│   │   └── upload/
│   │       └── cmis.py
│   ├── services/
│   │   ├── trigger.py
│   │   ├── document.py
│   │   ├── mapping.py
│   │   └── metadata.py
│   ├── orchestrators/
│   │   ├── batch.py
│   │   ├── phases.py
│   │   └── single.py
│   ├── config/
│   │   ├── schema.py
│   │   └── env.py                     # Env override logic, isolated
│   ├── cli/
│   │   ├── app.py                     # Click root
│   │   ├── commands/
│   │   │   ├── interactive.py
│   │   │   ├── background.py
│   │   │   └── phases.py
│   │   └── ui/
│   │       ├── dashboard.py
│   │       └── logging.py             # Single source of logging setup
│   └── main.py
│
├── config/
│   └── config.yaml                    # Copied from old project
│
├── data/                              # Test fixtures
│   ├── trigger_list.csv
│   ├── modelo_documental.csv
│   ├── rvabrep_export.csv
│   └── ...
│
├── tests/
│   ├── unit/
│   │   ├── domain/
│   │   ├── services/
│   │   └── orchestrators/             # Mock adapters
│   └── integration/
│       ├── adapters/                  # Real CSV, SQLite, Alfresco
│       └── pipeline/                  # End-to-end with mocks
│
└── scripts/
    ├── seed_alfresco.py               # Setup test repo in Alfresco
    └── generate_mock_files.py         # Build test image stacks
```

### 14.3 Port Definitions (Domain Interfaces)

```python
# domain/ports.py
from abc import ABC, abstractmethod
from typing import Iterator, List, Optional, Dict
from .models import TriggerRecord, Document, CMMapping, MigrationRecord

class IDataSource(ABC):
    @abstractmethod
    def query(self, sql: str, params: Optional[list] = None) -> List[dict]: ...
    @abstractmethod
    def query_stream(self, sql: str, params: Optional[list] = None) -> Iterator[dict]: ...
    @abstractmethod
    def get_by_fields(self, filters: dict) -> List[dict]: ...
    @abstractmethod
    def get_by_fields_in(self, field: str, values: list, fixed_filters: dict) -> List[dict]: ...
    @abstractmethod
    def get_all(self) -> Iterator[dict]: ...
    @abstractmethod
    def count(self) -> int: ...
    @abstractmethod
    def close(self) -> None: ...

class ITrackingStore(ABC):
    @abstractmethod
    def is_uploaded(self, txn_num: str) -> bool: ...
    @abstractmethod
    def mark_processing(self, record: MigrationRecord) -> None: ...
    @abstractmethod
    def mark_uploaded(self, txn_num: str, cm_object_id: str) -> None: ...
    @abstractmethod
    def mark_failed(self, txn_num: str, error: str) -> None: ...
    @abstractmethod
    def start_batch(self, total_records: int) -> str: ...
    @abstractmethod
    def complete_batch(self, batch_id: str) -> None: ...
    # ... 3-phase staging methods ...
    # ... document_cache methods ...
    @abstractmethod
    def close(self) -> None: ...

class IAssembler(ABC):
    @abstractmethod
    def assemble(self, document: Document) -> tuple[str, int]:
        """Return (path_to_pdf, file_size_bytes)."""

class IUploader(ABC):
    @abstractmethod
    def ensure_folder(self, folder_path: str) -> None: ...
    @abstractmethod
    def upload(
        self,
        file_path: str,
        folder_path: str,
        object_type_id: str,
        document_name: str,
        mime_type: str,
        properties: Dict[str, str],
    ) -> str:
        """Returns CM object ID."""
    @abstractmethod
    def test_connection(self) -> dict: ...
```

### 14.4 What Changes vs. Old Code

| Concern | Old | New |
|---------|-----|-----|
| `pipeline.py` | 1341-line God Object | Split into 3 orchestrators, each <300 lines |
| Trigger source dispatch | Nested IF/ELIF in TriggerService | Strategy pattern: `TriggerSourceStrategy` interface + 4 implementations |
| Connection management | Singleton ConnectionManager | Constructor injection of `IDataSource` instances |
| CMIS upload | Mixed in service | Pure adapter, isolated behind `IUploader` |
| Logging setup | Duplicated in 3 CLI files | Single `cli/ui/logging.py` |
| `scan_and_resolve` | Mid-method intrusion | Its own orchestrator: `LocalScanOrchestrator` |
| Tests | Two stale unit test files | Real test pyramid: unit (mocked) + integration (Alfresco/SQLite/CSV) |

### 14.5 What's Preserved

These are battle-tested and must be replicated faithfully:

1. **Config schema** — Pydantic, env overrides, validation logic
2. **CMIS integration** — session warmup, multipart, retries, bandwidth limiter
3. **Metadata pre-fetch** — bulk table loading + granular cache key format
4. **SQLite tracking** — WAL + async writer queue + batch commits
5. **PDF assembly** — img2pdf fast path + Pillow fallback
6. **3-phase pipeline** — separation of resolve / assemble / upload
7. **Document cache** — cross-mode reuse table
8. **Idempotency** — UNIQUE constraint on `rvabrep_txn_num`
9. **CIF self-healing** — resolve CIF early before the field loop
10. **Filename sort by `int(extension)`** — handles variable padding

---

## 15. Implementation Order

Build in this sequence — each layer enables the next:

**Phase 0 — Bootstrap (1 day)**
- Create repo, pyproject.toml, requirements.txt
- Copy `config/config.yaml` from old project
- Set up pre-commit hooks, formatter (black/ruff), pytest

**Phase 1 — Domain (1 day)**
- `domain/models.py` — pure dataclasses
- `domain/ports.py` — abstract interfaces
- `domain/exceptions.py` — typed exceptions

**Phase 2 — Config (0.5 day)**
- Port the Pydantic schema verbatim
- Port the env override logic
- Unit tests for config loading

**Phase 3 — Adapters (3-4 days)**
- `adapters/sources/csv.py` — pandas-based CSV (unit-testable easily)
- `adapters/sources/as400.py` — pyodbc + thread-local connections
- `adapters/tracking/sqlite.py` — WAL + async writer queue
- `adapters/assembly/pdf.py` — img2pdf + Pillow fallback
- `adapters/upload/cmis.py` — session warmup + multipart + retries + bandwidth limiter
- Each adapter has its own integration test

**Phase 4 — Services (2-3 days)**
- `services/mapping.py` — load Modelo Documental, cache by ID RVI
- `services/document.py` — RVABREP queries, batch fetching
- `services/metadata.py` — prefetch + fallback chain + validation + CIF self-healing
- `services/trigger.py` — Strategy pattern over the 4 source modes

**Phase 5 — Orchestrators (2 days)**
- `orchestrators/single.py` — simplest, no threading
- `orchestrators/phases.py` — three independent phases
- `orchestrators/batch.py` — discovery thread pool + worker pool + queues

**Phase 6 — CLI (1-2 days)**
- Wire commands, dashboard, logging
- Integration test against Alfresco for the upload path

**Phase 7 — Polish & Docs (1 day)**
- README, CLAUDE.md
- docker-compose for Alfresco integration testing
- CI pipeline if applicable

**Total estimate**: 11-14 working days for a single experienced developer. Less if pair-programming with an agent. The original took longer because of accidental architecture; the rewrite is fast because all the discovery is already done.

---

## 16. Testing Strategy

### 16.1 Unit Tests (Fast, No I/O)

- All domain logic
- All services with mocked ports
- Validation logic in metadata service
- Trigger source strategies with mock data sources
- PDF assembly with fixture images
- Tracking state transitions

### 16.2 Integration Tests (Slower, Real Adapters)

- SQLite tracking with real DB file (in-memory or tmpdir)
- CSV sources with fixture files
- PDF assembly with real image stacks (small ones)
- CMIS uploader against **Alfresco** in Docker

### 16.3 Alfresco for CMIS Integration

```yaml
# docker-compose.yml
services:
  alfresco:
    image: alfresco/alfresco-content-repository-community:latest
    ports: ["8080:8080"]
    environment:
      JAVA_OPTS: "-Xmx2g -Xms1g"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/alfresco"]
      interval: 30s
```

Alfresco is CMIS Browser Binding compliant. It will validate:
- Session warmup logic
- Multipart upload structure
- Folder creation behavior
- Retry/error paths

It will NOT validate:
- IBM-specific object type naming (`$t!-2_BAC_*v-1`)
- IBM-specific property names (`clbNonGroup.BAC_*`)

For those, end-to-end tests must run against the real IBM CM in staging.

### 16.4 No DB2/AS400 Mock

Don't bother. The CSV adapter covers all dev/test needs. AS400 testing happens in staging against the real system, where the ODBC driver behavior matters.

---

## 17. Operational Considerations

### 17.1 Deployment

- Single Python application
- Runs on Windows (production) or Linux (staging) — both supported
- AS400 ODBC driver must be installed on the host (Windows: IBM iSeries Access; Linux: IBM i Access for Linux)
- All dependencies via `requirements.txt`
- Logs to `./logs/` directory with rotation

### 17.2 Network Considerations

- AS400 connections over port 446
- CMIS over HTTP/HTTPS to the CM server
- File server access via UNC paths or local-mounted shares
- Bandwidth limiting available for shared corporate networks

### 17.3 Failure Modes & Recovery

| Failure | Recovery |
|---------|----------|
| Process killed mid-batch | Re-run; idempotency skips uploaded docs |
| Network blip during upload | Built-in retry with exponential backoff |
| AS400 timeout | Retry with backoff; reduce thread count if persistent |
| File missing on file server | Document marked FAILED with specific error, batch continues |
| CMIS auth expired | Auto-rewarm session, retry |
| Disk full in temp dir | Document marked FAILED, batch continues |

### 17.4 Observability

The system tracks operational metrics across multiple dimensions. Each dimension is independently switchable via the `observability` config section so production runs can disable expensive sampling.

**Logging tiers** (separate files, configurable):
- **Application log** (`./logs/app-{date}.log`) — structured JSON, one event per line. Includes `pipeline`, `stage`, `batch_id`, `txn_num`, `outcome`, `duration_ms`. Always on.
- **Pipeline metrics** (`./logs/metrics-{date}.jsonl`) — per-stage timings (`s0_ms`, `s1_ms`, …, `s5_ms`), p50/p95/p99 latency, throughput in docs/sec. Cheap; default on.
- **Network metrics** (`./logs/network-{date}.jsonl` or embedded) — per-request timing for AS400 queries and CMIS uploads: connection time, send time, server time, response size. Cheap; default on.
- **System metrics** (`./logs/system-{date}.jsonl`) — CPU%, RAM, disk read/write IOPS, network bytes in/out, sampled at configurable interval (default 5s). Some CPU cost; **OFF by default in MVP**, post-MVP feature (see `docs/roadmap/POST-MVP.md §3`).
- **Slow operations report** (`./logs/slow-ops-{batch_id}.jsonl`) — top-N slowest operations per batch, threshold configurable.

**Configuration**:

```yaml
observability:
  enabled: true                    # master switch
  pipeline_metrics: true           # per-stage timings
  network_metrics: true            # request timing
  system_metrics: false            # MVP: off; psutil sampling has CPU cost
  log_dir: "./logs"
  log_format: "json"               # json | text
  rotation_mb: 100
  retention_days: 30
  system_sample_interval_s: 5
  slow_op_threshold_ms: 5000
  slow_op_top_n: 20
```

**Bottleneck identification** — with all tiers enabled, offline log analysis (post-MVP tooling, see `docs/roadmap/POST-MVP.md §5`) attributes slow batches to:
- **CPU**-bound (PDF assembly throughput, metadata regex validation)
- **Memory**-bound (worker count too high, large files buffered)
- **Disk IO**-bound (temp dir on slow disk, OneDrive sync interference, staging dir contention)
- **Network**-bound (CMIS bandwidth ceiling, AS400 query latency, JSESSIONID re-warmup churn)

**Live TUI dashboard** during pipeline runs (§10.6): two tabs (PREP / UPLOAD) with real-time progress, throughput, slow operations.

**Telemetry summary** at end of batch: per-stage counts (DONE / FAILED), per-stage p50/p95 latency, total throughput, top-10 slowest operations, exit code reflecting any FAILED documents.

**PII discipline** (Constitution Principle VIII): all loggers route through the central masking helper in `cli/ui/logging.py`. CIF, customer names, and account numbers never appear in INFO logs.

---

## 18. Glossary

| Term | Meaning |
|------|---------|
| **AS400** | IBM legacy server platform, also called IBM i, iSeries, System i |
| **CIF** | Customer Information File — the 6-digit customer ID at the bank |
| **CM** | IBM Content Manager — the target system |
| **CMIS** | Content Management Interoperability Services — OASIS standard REST API |
| **CYYMMDD** | AS400 7-digit date format (Century + YY + MM + DD) |
| **DB2 for i** | The relational database engine on AS400 |
| **ID RVI** | The document type code in RVABREP (`ABAHCD`); join key into Modelo Documental |
| **JSESSIONID** | Java session cookie required by IBM CMIS endpoint |
| **Modelo Documental** | The mapping table from ID RVI to CM document class |
| **ODBC** | Open Database Connectivity — the standard way to talk to AS400 from Python |
| **RVABREP** | The master document index table on AS400 |
| **RVI** | The legacy document management system being migrated from |
| **RVILIB** | The AS400 library (= namespace/schema) where RVI tables live |
| **ShortName** | The client identifier in RVI (`RVABREP.ABABCD`) |
| **SystemID** | The product/system code (`RVABREP.ABAACD`) |
| **TriggerRecord** | One row of the trigger list — drives one iteration of the pipeline |
| **txn_num** | Transaction number — unique document ID (`RVABREP.ABAANB`) |

---

## 19. First Session Bootstrap Prompt

Use this verbatim as the first message when opening the new repo with a fresh agent:

> *"Vamos a crear CMCourier desde 0. Es un rewrite del proyecto RVIMigration. Leé el archivo CMCOURIER_REBIRTH.md (o equivalente en este repo) que tiene todo el contexto del dominio, la arquitectura propuesta, y el orden de implementación. Empezá por la Fase 0 — bootstrap del repo — y confirmame antes de pasar a la Fase 1."*

The agent should:
1. Read this document fully
2. Confirm understanding of domain
3. Set up `pyproject.toml`, formatter, pytest, hooks
4. Copy `config/config.yaml` from old project (or ask where to find it)
5. Wait for green light before starting domain layer

---

## 20. Final Notes

- This document is the **ground truth**. If something contradicts the old code, this document wins.
- The old code is a reference for *how things were solved*, not a template for *how things should be structured*.
- When in doubt about a CMIS/AS400 quirk, check the old code's specific implementation — those quirks were learned the hard way.
- Don't over-engineer. The architecture above is the right level — don't add more layers (no Application Services / Domain Events / CQRS unless there's a specific reason).
- Keep CLAUDE.md in the new repo lean — link to this REBIRTH doc for deep dives.

End of document.
