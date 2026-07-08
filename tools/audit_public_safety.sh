#!/usr/bin/env bash
set -euo pipefail

# Public safety audit for passport_reader.
#
# Important:
#   This script intentionally does NOT contain project-specific sensitive values.
#   Exact sensitive values must be supplied from a local file outside git.
#
# Default exact-pattern file:
#   /tmp/public_sensitive_patterns.txt
#
# Override:
#   PASSPORT_READER_SENSITIVE_PATTERNS=/path/to/local_patterns.txt tools/audit_public_safety.sh .
#
# The script also performs generic checks for private-looking infrastructure,
# risky binary/archive files, and local bundle artifacts.

ROOT_DIR="${1:-.}"
cd "$ROOT_DIR"

echo "=== repo ==="
pwd
git rev-parse --show-toplevel 2>/dev/null || true
git status --short 2>/dev/null || true

CUSTOM_PATTERNS_FILE="${PASSPORT_READER_SENSITIVE_PATTERNS:-/tmp/public_sensitive_patterns.txt}"

echo
echo "=== exact sensitive/private values from local patterns ==="
if [ -f "$CUSTOM_PATTERNS_FILE" ]; then
  if grep -RIn \
      -f "$CUSTOM_PATTERNS_FILE" \
      . \
      --exclude-dir=.git \
      --exclude='audit_public_safety.sh'
  then
    echo
    echo "FAIL: exact sensitive/private values found"
    exit 10
  else
    echo "OK: no exact sensitive/private values from local patterns"
  fi
else
  echo "WARN: local exact-pattern file not found: $CUSTOM_PATTERNS_FILE"
  echo "WARN: exact old-value scan skipped"
fi

echo
echo "=== generic private infrastructure patterns ==="

PRIVATE_INFRA_HITS="$(
  grep -RInE \
    '([0-9]{1,3}\.){3}[0-9]{1,3}|/root/passport_reader|\\\\[0-9]{1,3}(\.[0-9]{1,3}){3}\\|(^|[^A-Za-z0-9_])(password|passwd|secret|api[_-]?key)([^A-Za-z0-9_]|$)' \
    . \
    --exclude-dir=.git \
    --exclude='audit_public_safety.sh' \
    || true
)"

if [ -n "$PRIVATE_INFRA_HITS" ]; then
  echo "$PRIVATE_INFRA_HITS"
  echo
  echo "FAIL: generic private infrastructure pattern found"
  exit 11
else
  echo "OK: no generic private infrastructure patterns"
fi

echo
echo "=== generic passport-like examples ==="

GENERIC_PASSPORT_HITS="$(
  grep -RInE \
    '([0-9]{4}[[:space:]-]?[0-9]{6})|([0-9]{3}-[0-9]{3})|([0-9]{2}\.[0-9]{2}\.[0-9]{4})|([12][0-9]{3}-[0-9]{2}-[0-9]{2})' \
    . \
    --exclude-dir=.git \
    --exclude='audit_public_safety.sh' \
    || true
)"

if [ -n "$GENERIC_PASSPORT_HITS" ]; then
  echo "$GENERIC_PASSPORT_HITS"

  BAD_GENERIC="$(
    echo "$GENERIC_PASSPORT_HITS" \
      | grep -Ev '2099-01-31|2099-02-28|999-999|9999 999999|000-000|0000 000000|REQ_TEST_001|Expected 000-000|Expected 0000 000000' \
      || true
  )"

  if [ -n "$BAD_GENERIC" ]; then
    echo
    echo "FAIL: suspicious passport-like values found"
    exit 12
  fi

  echo
  echo "OK: only allowed synthetic/format examples found"
else
  echo "OK: no passport-like examples"
fi

echo
echo "=== risky files ==="

RISKY_FILES="$(
  find . \
    -path './.git' -prune -o \
    -type f \
    | grep -Ei '\.(jpg|jpeg|png|webp|bmp|tif|tiff|zip|tar|gz|tgz|7z|rar|pdf|docx|xlsx|csv|json)$' \
    || true
)"

if [ -n "$RISKY_FILES" ]; then
  echo "$RISKY_FILES"
  echo
  echo "FAIL: risky files found"
  exit 13
else
  echo "OK: no risky binary/archive/document files"
fi

echo
echo "=== local bundle/apply artifacts ==="

LOCAL_ARTIFACTS="$(
  find . \
    -path './.git' -prune -o \
    \( -type d -name '*bundle*' -o -type f -name 'APPLY_*.md' -o -type f -name '*.zip' \) \
    -print \
    || true
)"

if [ -n "$LOCAL_ARTIFACTS" ]; then
  echo "$LOCAL_ARTIFACTS"
  echo
  echo "FAIL: local artifacts found"
  exit 14
else
  echo "OK: no local bundle/apply artifacts"
fi

echo
echo "=== tests ==="
python3 -m py_compile \
  src/parse_passport.py \
  src/process_photo.py \
  src/passport_service.py

python3 tools/test_parser_birth_place.py

echo
echo "OK: public safety audit passed"
