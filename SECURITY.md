# Security policy

## Sensitive data

This project processes identity documents. Do not commit:

- real passport photos;
- raw OCR output from real documents;
- debug crops or screenshots containing personal data;
- production logs;
- real names, dates of birth, document numbers, department codes, or addresses;
- real internal IP addresses, hostnames, SMB paths, credentials, or customer data.

Use only synthetic or fully anonymized test data.

## Configuration

Production configuration must live outside git.

Recommended location:

```text
/etc/passport-reader/passport-reader.env
```

The repository contains only public-safe examples:

```text
deploy/passport-reader.env.example
deploy/passport-reader.service
```

## Reporting security issues

Please do not open public issues containing sensitive data.

Report suspected leaks or security problems privately to the repository owner.
