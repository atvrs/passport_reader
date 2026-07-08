# Contributing

Contributions are welcome.

## Before submitting changes

Please make sure that your changes do not include:

- real passport photos;
- raw OCR output from real documents;
- debug images with personal data;
- production logs;
- real personal data;
- real internal IP addresses or SMB paths;
- credentials or private deployment files.

## Tests

Run at least:

```bash
python3 -m py_compile \
  src/parse_passport.py \
  src/process_photo.py \
  src/passport_service.py

python3 tools/test_parser_birth_place.py
```

## Pull requests

In your pull request, describe:

- what changed;
- how it was tested;
- whether the change affects parsing behavior;
- whether the change affects the JSON contract.
