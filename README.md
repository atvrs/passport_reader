# passport_reader

File-based OCR service for extracting structured data from Russian internal passport photos.

The service watches an input directory for JSON commands, processes passport images with OpenCV and PaddleOCR, and writes normalized JSON results for integration with external systems such as accounting or ERP software.

## Current status

Implemented:

- passport crop detection;
- PaddleOCR-based text recognition;
- Russian internal passport parser;
- filesystem command queue;
- atomic input/output JSON workflow;
- systemd service template;
- service status JSON;
- archive retention;
- log rotation;
- sample production runbooks and integration notes.

Planned:

- parser abstraction by document type;
- foreign passport / MRZ support;
- additional parsers for other countries and document layouts.

## Important security note

Do not commit real passport photos, raw OCR output, debug images, production logs, or real personal data to this repository.

Use only synthetic or fully anonymized test data.

Production-specific settings should be stored outside git, for example:

```text
/etc/passport-reader/passport-reader.env
```

Recommended local/private files are ignored by `.gitignore`:

- `.env`
- `*.env`
- `*.local`
- `*.private`
- `local/`
- `private/`

## Repository layout

```text
src/
  crop_passport.py        Passport crop detection
  ocr_paddle.py           PaddleOCR wrapper
  parse_passport.py       Russian internal passport parser
  process_photo.py        Single-photo processing pipeline
  passport_service.py     File-based service loop

deploy/
  passport-reader.service       systemd unit template
  passport-reader.env.example   environment file example

docs/
  json_contract.md
  service_mode.md
  systemd_service.md
  1c_file_exchange.md
  production_runbook.md
  security_checklist.md
  multi_document_plan.md

tools/
  check_production_status.sh
  test_local_service.sh
  test_ocr_smb_ps2.ps1
  test_parser_birth_place.py
```

## Installation overview

Clone the repository:

```bash
git clone git@github.com:atvrs/passport_reader.git
cd passport_reader
```

Copy the environment template:

```bash
sudo mkdir -p /etc/passport-reader
sudo cp deploy/passport-reader.env.example /etc/passport-reader/passport-reader.env
sudo nano /etc/passport-reader/passport-reader.env
```

Copy and enable the systemd unit:

```bash
sudo cp deploy/passport-reader.service /etc/systemd/system/passport-reader.service
sudo systemctl daemon-reload
sudo systemctl enable passport-reader.service
sudo systemctl start passport-reader.service
```

Check status:

```bash
systemctl status passport-reader.service
```

## File exchange model

The service uses filesystem-based exchange.

Typical directory structure:

```text
/data/passport_reader/in
/data/passport_reader/commands
/data/passport_reader/processing
/data/passport_reader/out
/data/passport_reader/error
/data/passport_reader/archive
/data/passport_reader/logs
/data/passport_reader/status
/data/passport_reader/work
```

External system workflow:

1. Write image as temporary file.
2. Atomically rename image to final name.
3. Write command JSON as temporary file.
4. Atomically rename command JSON to final name.
5. Wait for result JSON in `out/`.

Command example:

```json
{
  "request_id": "REQ_TEST_001",
  "image_file": "REQ_TEST_001.jpg"
}
```

Result example:

```json
{
  "request_id": "REQ_TEST_001",
  "status": "ok",
  "document_type": "rf_internal",
  "fields": {
    "last_name": "ТЕСТОВ",
    "first_name": "ТЕСТ",
    "middle_name": "ТЕСТОВИЧ",
    "birth_date": "2099-01-31",
    "sex": "МУЖ",
    "birth_place": "ГОР. ТЕСТОВСК",
    "issue_date": "2099-02-28",
    "department_code": "999-999",
    "issued_by": "ТЕСТОВЫМ ОТДЕЛОМ МВД ГОР. ТЕСТОВСКА",
    "document_number": "9999 999999"
  }
}
```

## Tests

Syntax check:

```bash
python3 -m py_compile \
  src/parse_passport.py \
  src/process_photo.py \
  src/passport_service.py
```

Parser regression test:

```bash
python3 tools/test_parser_birth_place.py
```

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE).
