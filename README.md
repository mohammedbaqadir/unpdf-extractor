# unpdf-extractor

Read PDFs into a validation-checked SQLite database using approved profiles.

Extraction is deterministic and runs on this machine. No model is called. The
network is used only to download a profile that is not already local or cached.

A profile is an approved JSON contract for one document type: page count, page
size, label anchors, and the box for each field. The extractor selects a profile
by name and never accepts a profile path.

## Install

```powershell
uv tool install --editable .
```

Needs Python 3.12+. Scanned PDFs need Tesseract with the `ara` and `eng` language
packs; PDFs with a text layer do not.

## Commands

```powershell
unpdf-extractor run --type fasah-import C:\docs
unpdf-extractor run --family fasah C:\docs
unpdf-extractor check --family fasah C:\docs
unpdf-extractor pull fasah-import
```

- `run` reads every `*.pdf` in the folder, extracts the selected profile, and
  writes the database.
- `check` re-runs the field rules against a database that already exists. The
  PDFs are not opened and no evidence is written.
- `pull` downloads one profile, verifies its SHA-256 and contract, and caches it.

Help is offline: `help run` describes one command, `help all` prints every topic,
and there is one page per profile. Topics: `profiles`, `registry`, `extraction`,
`review`, `contract`, `quarantine`, `exit-codes`.

## Options

| Option | Meaning |
| ------ | ------- |
| `folder` | PDF folder; defaults to the current folder |
| `--type NAME` | one profile |
| `--family NAME` | route each PDF to the family member that matches |
| `--db PATH` | database file; defaults to `<name>.db` in the PDF folder |
| `--work PATH` | evidence folder; `run` only; default `.unpdf` beside the database |
| `--no-color` | plain text output |

`--type` and `--family` are alternatives. With neither, the command prints the
available choices and exits 1.

A family run reads each PDF once and lets the members' contracts and `match`
rules decide the subtype. File names are never used. When registry credentials
are set, the registry supplies the complete family member list, so a partly
cached family is not treated as complete.

## Output

```text
<name>.db    SQLite database; a type run writes <name>.db, a family writes <family>.db
.unpdf/      profile snapshot, extraction evidence, and quarantine records
```

Both live next to the database, which defaults to the PDF folder. `--db` and
`--work` move them, and neither may point inside the tool's own folder. The PDFs
are never moved or modified.

The database holds one row per document in `docs`, one row per field in
`extracted_fields`, rejected PDFs in `quarantine`, and a `review` view of every
flagged field.

## Profiles

Local profiles are read from:

```text
profiles/<name>/profile.json
```

relative to the current folder, or from the folder in `UNPDF_PROFILES`.
Profiles downloaded from the registry are cached and need no local folder. Only
approved profiles are accepted; an unapproved one exits with code 4.

## Registry

Provide both credential values through the environment:

```powershell
$env:UNPDF_REGISTRY_URL = '<registry base URL>'
$env:UNPDF_REGISTRY_TOKEN = 'unpdf_...'
```

or through a credentials file, which holds the same two keys:

```text
%APPDATA%\unpdf\credentials.json        Windows
~/.config/unpdf/credentials.json        other systems
```

```json
{"url": "<registry base URL>", "token": "unpdf_..."}
```

A URL and token always come from the same place. Setting only one environment
variable is an error, and an environment URL is never paired with the token from
the file. The URL must be HTTPS; plain HTTP is allowed for localhost only.

```powershell
unpdf-extractor pull fasah-import
unpdf-extractor pull fasah-import --version 1.0.0
```

Downloads are cached at:

```text
%LOCALAPPDATA%\unpdf\profiles\<name>\<version>\profile.json
```

Cached profiles work offline. Each profile keeps one version; pulling a different
version replaces the cached one. Set `UNPDF_PROFILE_CACHE` to use another cache
folder. No registry URL, token, or profile data is stored in this package.

## Results

Every field gets one status:

```text
accepted   present and passed its check
review     present but failed a check, or a required field is empty
missing    absent; optional, or genuinely blank
```

A PDF that fails the contract check is quarantined with a reason, and the rest of
the batch continues. Each run ends with a summary:

```text
run: 3 added, 1 skipped, 0 failed
database: 4 document(s) | 57 accepted, 2 review, 5 missing (optional)

review queue:
  invoice.pdf | number | not a number
```

`skipped` counts PDFs already in the database, or the same content twice in one
batch. `missing` fields are optional; a blank required field lands in review.

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

## Environment variables

| Name | Purpose |
| ---- | ------- |
| `UNPDF_PROFILES` | Profiles folder, default `./profiles` |
| `UNPDF_REGISTRY_URL` | Registry base URL |
| `UNPDF_REGISTRY_TOKEN` | This machine's read token |
| `UNPDF_PROFILE_CACHE` | Profile cache folder |
| `NO_COLOR` | Plain text output, same as `--no-color` |

## Tests

```powershell
uv run python -m unittest discover -s tests -v
uvx ruff@0.17.2 check --select E9,F src tests
```
