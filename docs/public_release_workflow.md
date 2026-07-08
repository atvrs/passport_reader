# Public release workflow

This project processes identity documents, so public releases must be built from
a sanitized working tree and must not expose old private history.

## Recommended repository model

Use two repositories:

```text
atvrs/passport_reader_private   private production/development history
atvrs/passport_reader           public clean repository
```

Do not make the private repository public.

## Sensitive-value patterns

Do not store real sensitive values inside public scripts or documentation.

Exact sensitive-value scans should use a local file outside git, for example:

```text
/tmp/public_sensitive_patterns.txt
```

Run the audit with the default local file:

```bash
tools/audit_public_safety.sh .
```

Or with an explicit local file:

```bash
PASSPORT_READER_SENSITIVE_PATTERNS=/tmp/public_sensitive_patterns.txt \
  tools/audit_public_safety.sh .
```

## Public safety audit

Run before every public push:

```bash
cd /tmp/passport_reader_public_check

tools/audit_public_safety.sh .
```

Expected result:

```text
OK: public safety audit passed
```

## Create a clean public snapshot

From the private repository:

```bash
cd /opt/passport_reader

tools/create_clean_public_snapshot.sh
```

The script creates a new directory under `/tmp` and writes the path to:

```text
/tmp/passport_reader_public_snapshot_dir.txt
```

## Push a clean snapshot manually

After inspection:

```bash
cd "$(cat /tmp/passport_reader_public_snapshot_dir.txt)"

git remote add origin git@github.com:atvrs/passport_reader.git
git push -u origin main
```

## Check private and public repositories

```bash
tools/check_repo_pair.sh
```

Defaults:

```text
PRIVATE_REPO=/opt/passport_reader
PUBLIC_REPO=/tmp/passport_reader_public_check
```

Override example:

```bash
PRIVATE_REPO=/opt/passport_reader \
PUBLIC_REPO=/tmp/passport_reader_public_check \
tools/check_repo_pair.sh
```

## Never commit

- real passport photos;
- raw OCR JSON from real documents;
- debug crops or screenshots containing personal data;
- production logs;
- real names, dates, document numbers, department codes, addresses;
- real internal IP addresses, hostnames, SMB paths, credentials;
- exact old sensitive-value pattern files;
- downloaded archives or unpacked bundle directories.
