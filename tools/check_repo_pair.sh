#!/usr/bin/env bash
set -euo pipefail

# Check private production repo and public repo side-by-side.
#
# Defaults:
#   PRIVATE_REPO=/opt/passport_reader
#   PUBLIC_REPO=/tmp/passport_reader_public_check

PRIVATE_REPO="${PRIVATE_REPO:-/opt/passport_reader}"
PUBLIC_REPO="${PUBLIC_REPO:-/tmp/passport_reader_public_check}"

echo "================================================================================"
echo "PRIVATE / PRODUCTION REPO"
echo "================================================================================"

if [ -d "$PRIVATE_REPO/.git" ]; then
  cd "$PRIVATE_REPO"
  pwd
  git remote -v
  git status --short
  git log --oneline --decorate -5
else
  echo "Missing private repo: $PRIVATE_REPO"
fi

echo
echo "================================================================================"
echo "PUBLIC REPO"
echo "================================================================================"

if [ -d "$PUBLIC_REPO/.git" ]; then
  cd "$PUBLIC_REPO"
  pwd
  git remote -v
  git status --short
  git log --oneline --decorate -10

  echo
  echo "=== public tracked docs ==="
  git ls-files | grep -E 'README.md|SECURITY.md|CONTRIBUTING.md|pull_request_template.md|LICENSE' || true

  echo
  echo "=== public safety audit ==="
  if [ -x tools/audit_public_safety.sh ]; then
    tools/audit_public_safety.sh .
  else
    echo "tools/audit_public_safety.sh not found in public repo"
  fi
else
  echo "Missing public repo: $PUBLIC_REPO"
fi
