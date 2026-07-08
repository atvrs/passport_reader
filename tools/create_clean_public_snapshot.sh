#!/usr/bin/env bash
set -euo pipefail

# Create a clean public snapshot from the current repository HEAD.
#
# The snapshot is made with `git archive`, so it has no old .git history.
# The script then initializes a fresh git repo with one root commit.
#
# Usage:
#   tools/create_clean_public_snapshot.sh
#
# Optional env:
#   SNAPSHOT_BASE=/tmp
#   SNAPSHOT_NAME=passport_reader_public_snapshot
#   PUBLIC_REMOTE=git@github.com:atvrs/passport_reader.git

SNAPSHOT_BASE="${SNAPSHOT_BASE:-/tmp}"
SNAPSHOT_NAME="${SNAPSHOT_NAME:-passport_reader_public_snapshot}"
PUBLIC_REMOTE="${PUBLIC_REMOTE:-}"

SOURCE_DIR="$(git rev-parse --show-toplevel)"
TS="$(date +%Y%m%d_%H%M%S)"
SNAPSHOT_DIR="${SNAPSHOT_BASE}/${SNAPSHOT_NAME}_${TS}"

cd "$SOURCE_DIR"

echo "=== source ==="
pwd
git status --short
git log --oneline --decorate -5

if [ -n "$(git status --short)" ]; then
  echo "ERROR: source repository has uncommitted changes" >&2
  exit 1
fi

mkdir -p "$SNAPSHOT_DIR"
git archive --format=tar HEAD | tar -xf - -C "$SNAPSHOT_DIR"

echo
echo "=== snapshot ==="
echo "$SNAPSHOT_DIR"

cd "$SNAPSHOT_DIR"

echo "$SNAPSHOT_DIR" > /tmp/passport_reader_public_snapshot_dir.txt

if [ -d .git ]; then
  echo "ERROR: unexpected .git directory inside snapshot" >&2
  exit 2
fi

echo
echo "=== audit snapshot ==="
chmod +x tools/audit_public_safety.sh
tools/audit_public_safety.sh .

echo
echo "=== init clean git ==="
git init
git branch -M main
git add .
git commit -m "Initial public release"

if [ -n "$PUBLIC_REMOTE" ]; then
  git remote add origin "$PUBLIC_REMOTE"
  echo
  echo "Remote added:"
  git remote -v
  echo
  echo "Push manually after inspection:"
  echo "  cd '$SNAPSHOT_DIR'"
  echo "  git push -u origin main"
fi

echo
echo "OK: clean public snapshot created"
echo "$SNAPSHOT_DIR"
