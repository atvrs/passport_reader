#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/opt/passport_reader}"
DATA_ROOT="${DATA_ROOT:-/data/passport_reader}"
SERVICE_NAME="${SERVICE_NAME:-passport-reader.service}"

cd "$PROJECT_DIR"

echo "=== GIT ==="
echo "project: $PROJECT_DIR"
echo "branch: $(git branch --show-current)"
echo "commit: $(git rev-parse --short HEAD)"
echo "status:"
git status --short

echo
echo "=== SYSTEMD ==="
systemctl is-enabled "$SERVICE_NAME" || true
systemctl status "$SERVICE_NAME" --no-pager | sed -n '1,80p'

echo
echo "=== DATA DIRS ==="
for d in in commands processing out error archive logs status work; do
  path="$DATA_ROOT/$d"
  if [ -e "$path" ]; then
    ls -ld "$path"
  else
    echo "MISSING: $path"
  fi
done

echo
echo "=== STATUS JSON ==="
if [ -f "$DATA_ROOT/status/service_status.json" ]; then
  cat "$DATA_ROOT/status/service_status.json"
  echo
else
  echo "MISSING: $DATA_ROOT/status/service_status.json"
fi

echo
echo "=== QUEUES ==="
echo "commands:"
find "$DATA_ROOT/commands" -maxdepth 1 -type f -printf '%TY-%Tm-%Td %TH:%TM %p\n' 2>/dev/null | sort || true
echo "processing:"
find "$DATA_ROOT/processing" -maxdepth 1 -type f -printf '%TY-%Tm-%Td %TH:%TM %p\n' 2>/dev/null | sort || true
echo "error:"
find "$DATA_ROOT/error" -maxdepth 1 -type f -printf '%TY-%Tm-%Td %TH:%TM %p\n' 2>/dev/null | sort | tail -20 || true

echo
echo "=== DISK USAGE ==="
du -sh "$DATA_ROOT" 2>/dev/null || true
du -sh "$DATA_ROOT/archive" 2>/dev/null || true

echo
echo "=== RECENT LOG ==="
tail -n 80 "$DATA_ROOT/logs/passport_service.log" 2>/dev/null || true
