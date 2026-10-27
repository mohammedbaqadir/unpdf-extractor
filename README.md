# unpdf-extractor

Deterministic PDF-to-SQLite extraction using approved profiles.

Extraction runs locally. Tesseract with `ara` and `eng` data is used for scanned
PDFs. No LLM is called. The network is used only to download a profile that is
not already local or cached.

## Install locally

```powershell
uv tool install --editable .
```

## Commands

```powershell
unpdf-extractor --help                    overview
unpdf-extractor help run                  one command or topic
unpdf-extractor help all                  every topic on one page

unpdf-extractor run --type fasah-import C:\docs
unpdf-extractor run --family fasah C:\docs
unpdf-extractor check --family fasah C:\docs
```

- `run` reads every `*.pdf` in the folder, extracts the selected profile, and
  writes one database.
- `check` re-runs the field rules against a database that already exists. The
  PDFs are not opened.
- `--type NAME` selects exactly one profile. An unknown name is downloaded when
  registry credentials are set.
- `--family NAME` routes each PDF to the family member whose contract matches.
  The registry supplies the complete member list when credentials are set, so a
  partly cached family is not treated as complete.
- `--db PATH` and `--work PATH` move the database and the evidence folder.

Family routing is decided by each profile's contract and `match` rule. File
names are never used.

Output:

```text
<name>.db   SQLite database; a type run writes <name>.db, a family writes <family>.db
.unpdf/     profile snapshot, extracted fields, and quarantine evidence
```

Both live next to the database, which defaults to the PDF folder. The PDFs are
never moved or modified.

## Profiles

A profile is an approved JSON contract. The extractor never accepts an arbitrary
profile path; it selects a profile by name.

Local profiles are read from:

```text
profiles/<name>/profile.json
```

relative to the current folder, or from the folder in `UNPDF_PROFILES`.
Unapproved profiles are rejected. Registry profiles are downloaded on demand and
cached.

### Registry credentials

The package contains no registry URL, token, or bundled profile. Provide both
through the environment:

```powershell
$env:UNPDF_REGISTRY_URL = '<registry base URL>'
$env:UNPDF_REGISTRY_TOKEN = 'unpdf_...'
```

or through a user credentials file:

```text
%APPDATA%\unpdf\credentials.json
```

```json
{"url": "<registry base URL>", "token": "unpdf_..."}
```

A URL and token always come from the same place: setting only one environment
variable is an error, and an environment URL is never paired with the token from
the file. Tokens are issued by the registry owner, belong to one person, and can
be revoked individually. Never commit a token.

### Download and cache

```powershell
unpdf-extractor pull fasah-import
unpdf-extractor pull fasah-import --version 1.0.0
```

Each download is verified against the registry SHA-256 and checked against the
profile contract before it is used, then cached at:

```text
%LOCALAPPDATA%\unpdf\profiles\<name>\<version>\profile.json
```

Cached profiles work offline. Each pull keeps one version per profile; pulling a
different version replaces the cached one. Set `UNPDF_PROFILE_CACHE` to use a
different cache folder.

## Exit codes

| Code | Meaning |
| ---- | ------- |
| 0 | clean: every field accepted |
| 1 | nothing to do, or a usage or setup mistake |
| 2 | review needed: at least one field needs a person |
| 3 | at least one PDF could not be read, or the registry failed |
| 4 | a PDF was quarantined, or the profile is not approved |

3 wins over 4, and 4 wins over 2. Documents that did pass are still saved.
`unpdf-extractor help exit-codes` says the same thing offline.

## Tests

```powershell
uv run python -m unittest discover -s tests -v
```
