#!/usr/bin/env bash
# Throughput benchmark: streaming pipeline against /tmp/mockfiles-mixed.
#
# Usage:
#   scripts/staging/throughput-bench.sh [TOTAL] [CONFIG]
#
# Examples:
#   # quick smoke (100 docs)
#   scripts/staging/throughput-bench.sh 100
#
#   # full 1000-doc steady-state
#   scripts/staging/throughput-bench.sh 1000
#
#   # mega-heavy variant
#   scripts/staging/throughput-bench.sh 500 sample/config-staging-rvabrep-mega-heavy.yaml
#
# Reports total elapsed + cumulative bytes + average throughput at the
# end. Real-time throughput / per-lane occupancy / AIMD activity are on
# the live TUI (open the BUCKET tab with `b`, UPLOAD with `u`).

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

TOTAL="${1:-1000}"
CONFIG="${2:-sample/config-staging-rvabrep-streaming.yaml}"
LOG_DIR="$ROOT/sample/logs"

if [[ ! -f "$CONFIG" ]]; then
    echo "ERROR: config not found: $CONFIG" >&2
    exit 2
fi

# Validate that the assembly source_root exists before launching the
# whole pipeline. If not, point the operator at `mock generate`.
SOURCE_ROOT="$(awk '/^assembly:/,/^[a-z]/' "$CONFIG" \
    | sed -n 's/^[[:space:]]*source_root:[[:space:]]*//p' \
    | head -1)"

if [[ -n "$SOURCE_ROOT" && ! -d "$SOURCE_ROOT" ]]; then
    cat <<MISSING >&2
ERROR: assembly source_root does not exist: $SOURCE_ROOT

Generate the mock file tree first:

  .venv/bin/cmcourier mock generate \\
      --rvabrep-csv sample/rvabrep-5000-heavy.csv \\
      --root $SOURCE_ROOT \\
      --pdf-min 100kb --pdf-max 30mb \\
      --img-min 50kb --img-max 10mb \\
      --seed 42 \\
      --limit 500

MISSING
    exit 3
fi

mkdir -p "$LOG_DIR"
STAMP="$(date +%Y%m%d-%H%M%S)"
RUN_LOG="$LOG_DIR/throughput-bench-${STAMP}.log"

cat <<INFO
==============================================================
  Throughput benchmark
==============================================================
  config        : $CONFIG
  source_root   : ${SOURCE_ROOT:-<not declared in YAML>}
  --total       : $TOTAL
  cmcourier ver : $(.venv/bin/cmcourier --version 2>&1)
  start         : $(date -Iseconds)
  log file      : $RUN_LOG
==============================================================

Open the TUI tabs during the run:
  [u] UPLOAD   — bandwidth current/peak + WORKERS / LANES blocks
  [b] BUCKET   — bucket level + PREP/S5 throughput + lane queues
  [c] CHUNKS   — synthetic chunk row with live s5_done counters
  [q] quit (waits for run to finish; never aborts mid-run)

INFO

T0_NS=$(date +%s%N)

# Pipe stderr to the run log so we can grep batch_summary at the end.
# Stdout still goes to the operator's terminal (the TUI uses stderr).
.venv/bin/cmcourier rvabrep-pipeline run \
    --config "$CONFIG" \
    --total "$TOTAL" \
    2> >(tee -a "$RUN_LOG" >&2)

T1_NS=$(date +%s%N)
ELAPSED_S=$(awk "BEGIN{printf \"%.3f\", ($T1_NS - $T0_NS) / 1e9}")

# Extract the last batch_summary from the pipeline metrics log. The
# observability layer writes structured JSONL — use python for parsing.
PIPELINE_LOG="$LOG_DIR/cmcourier-pipeline-$(date +%Y%m%d).jsonl"
if [[ -f "$PIPELINE_LOG" ]]; then
    SUMMARY=$(.venv/bin/python - "$PIPELINE_LOG" <<'PY'
import json, sys
path = sys.argv[1]
last = None
with open(path, encoding="utf-8") as fh:
    for line in fh:
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if rec.get("kind") == "batch_summary":
            last = rec
if last is not None:
    total_docs = last.get("total_docs", 0)
    elapsed = last.get("elapsed_s", 0.0)
    throughput = last.get("throughput_docs_per_s", 0.0)
    print(f"docs={total_docs} elapsed_s={elapsed} docs_per_s={throughput:.2f}")
PY
)
else
    SUMMARY="(no pipeline log at $PIPELINE_LOG)"
fi

# Tracking DB has the ground-truth byte total via migration_log.
DB_PATH="$(awk '/^tracking:/,/^[a-z]/' "$CONFIG" \
    | sed -n 's/^[[:space:]]*db_path:[[:space:]]*//p' \
    | head -1)"
BYTES_TOTAL=""
if [[ -n "$DB_PATH" && -f "$DB_PATH" ]]; then
    BYTES_TOTAL=$(sqlite3 "$DB_PATH" \
        "SELECT COALESCE(SUM(file_size_bytes), 0) FROM migration_log WHERE status = 'S5_DONE'" \
        2>/dev/null || echo "")
fi

cat <<RESULT

==============================================================
  Run finished
==============================================================
  wall-clock elapsed : ${ELAPSED_S} s
  batch_summary      : $SUMMARY
RESULT

if [[ -n "$BYTES_TOTAL" && "$BYTES_TOTAL" != "0" ]]; then
    MB_TOTAL=$(awk "BEGIN{printf \"%.1f\", $BYTES_TOTAL / 1048576.0}")
    AVG_MBPS=$(awk "BEGIN{printf \"%.2f\", ($BYTES_TOTAL / 1048576.0) / $ELAPSED_S}")
    cat <<BYTES
  total uploaded     : ${MB_TOTAL} MB  ($BYTES_TOTAL bytes)
  avg throughput     : ${AVG_MBPS} MB/s
BYTES
fi

echo "  full log           : $RUN_LOG"
echo "=============================================================="
