#!/usr/bin/env bash
# Block any commit message that contains a Co-Authored-By trailer.
# Constitution Principle IX (no AI attribution) and CONTRIBUTING.md.
set -euo pipefail

msg_file="${1:?missing commit message file argument}"

if grep -qiE '^[[:space:]]*Co-Authored-By:' "$msg_file"; then
  echo "ERROR: commit message contains 'Co-Authored-By' - disallowed by Constitution Principle IX." >&2
  echo "If this was human pair-programming, list the co-author in the PR description instead." >&2
  exit 1
fi

exit 0
