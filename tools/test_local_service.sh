#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/opt/passport_reader}"
DATA_ROOT="${DATA_ROOT:-/data/passport_reader}"
IMAGE_PATH="${1:-${PASSPORT_READER_SAMPLE_IMAGE:-samples/test1.jpg}}"
REQ_ID="${2:-LOCAL_RF_TEST_$(date +%Y%m%d_%H%M%S)}"
TIMEOUT_SEC="${TIMEOUT_SEC:-60}"

if [ "$(id -u)" -eq 0 ]; then
  SUDO=""
else
  SUDO="sudo"
fi

cd "$PROJECT_DIR"

if [ ! -f "$IMAGE_PATH" ]; then
  echo "ERROR: image not found: $IMAGE_PATH" >&2
  echo "Usage: $0 /path/to/passport.jpg [REQUEST_ID]" >&2
  exit 2
fi

echo "=== LOCAL SERVICE OCR TEST ==="
echo "project: $PROJECT_DIR"
echo "data_root: $DATA_ROOT"
echo "image: $IMAGE_PATH"
echo "request_id: $REQ_ID"
echo

$SUDO rm -f \
  "$DATA_ROOT/out/$REQ_ID.json" \
  "$DATA_ROOT/error/$REQ_ID.json" \
  "$DATA_ROOT/commands/$REQ_ID.json" \
  "$DATA_ROOT/commands/$REQ_ID.json.tmp" \
  "$DATA_ROOT/processing/$REQ_ID.json" \
  "$DATA_ROOT/in/$REQ_ID.jpg" \
  "$DATA_ROOT/in/$REQ_ID.jpg.tmp"

echo "Copy image tmp..."
$SUDO cp "$IMAGE_PATH" "$DATA_ROOT/in/$REQ_ID.jpg.tmp"

echo "Rename image tmp -> jpg..."
$SUDO mv "$DATA_ROOT/in/$REQ_ID.jpg.tmp" "$DATA_ROOT/in/$REQ_ID.jpg"

TMP_COMMAND="/tmp/$REQ_ID.json.tmp"
cat > "$TMP_COMMAND" <<JSON
{
  "request_id": "$REQ_ID",
  "image_file": "$REQ_ID.jpg"
}
JSON

echo "Write command tmp..."
$SUDO cp "$TMP_COMMAND" "$DATA_ROOT/commands/$REQ_ID.json.tmp"

echo "Rename command tmp -> json..."
$SUDO mv "$DATA_ROOT/commands/$REQ_ID.json.tmp" "$DATA_ROOT/commands/$REQ_ID.json"

RESULT_PATH="$DATA_ROOT/out/$REQ_ID.json"
ERROR_PATH="$DATA_ROOT/error/$REQ_ID.json"

echo "Waiting result: $RESULT_PATH"
for i in $(seq 1 "$TIMEOUT_SEC"); do
  if [ -f "$RESULT_PATH" ]; then
    echo "Result file found after ${i}s."
    break
  fi

  if [ -f "$ERROR_PATH" ]; then
    echo "ERROR: command moved to error: $ERROR_PATH" >&2
    echo "Recent log:" >&2
    $SUDO tail -n 80 "$DATA_ROOT/logs/passport_service.log" >&2 || true
    exit 3
  fi

  sleep 1

done

if [ ! -f "$RESULT_PATH" ]; then
  echo "ERROR: result not found after ${TIMEOUT_SEC}s: $RESULT_PATH" >&2
  echo "Recent log:" >&2
  $SUDO tail -n 120 "$DATA_ROOT/logs/passport_service.log" >&2 || true
  exit 4
fi

python3 - "$RESULT_PATH" "$IMAGE_PATH" <<'PY'
import json
import sys
from pathlib import Path

result_path = Path(sys.argv[1])
image_path = Path(sys.argv[2])

data = json.loads(result_path.read_text(encoding="utf-8-sig"))
validation = data.get("validation") or {}
status = validation.get("status")

print()
print("=== RESULT ===")
print("request_id:", data.get("request_id"))
print("validation.status:", status)

fields = [
    "last_name",
    "first_name",
    "middle_name",
    "sex",
    "birth_date",
    "birth_place",
    "issue_date",
    "department_code",
    "issued_by",
    "document_number",
]

for key in fields:
    print(f"{key}: {data.get(key)}")

print("result_path:", result_path)

if status != "ok":
    raise SystemExit(f"validation.status is not ok: {status}")

# Exact field check only for known repository sample test1.jpg.
if image_path.name == "test1.jpg":
    expected_birth_place = "ГОР. ТЕСТОВСК"
    got = data.get("birth_place")
    if got != expected_birth_place:
        raise SystemExit(
            f"unexpected birth_place for test1.jpg: "
            f"expected {expected_birth_place!r}, got {got!r}"
        )

print()
print("OK: local service OCR test passed")
PY

echo
echo "Recent log:"
$SUDO tail -n 40 "$DATA_ROOT/logs/passport_service.log" || true
