## Summary

Describe the change.

## Testing

Commands run:

```bash
python3 -m py_compile \
  src/parse_passport.py \
  src/process_photo.py \
  src/passport_service.py

python3 tools/test_parser_birth_place.py
```

## Security checklist

- [ ] I did not add real passport photos.
- [ ] I did not add raw OCR output from real documents.
- [ ] I did not add debug images with personal data.
- [ ] I did not add real names, document numbers, dates, addresses, or department codes.
- [ ] I did not add real internal IP addresses, SMB paths, credentials, or private config.
- [ ] I used only synthetic or fully anonymized examples.

## JSON contract impact

- [ ] No JSON contract changes.
- [ ] JSON contract changed and docs were updated.
