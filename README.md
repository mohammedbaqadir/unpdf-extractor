# unpdf-extractor

Read PDFs into a SQLite database, using approved profiles.

Extraction runs on your machine and never calls a model. The network is used only to download a profile you don't already have, locally or in the cache.

A profile is a JSON file that describes one kind of PDF: its page count, page size, the anchors that prove it's the right form, and the box for each field. You pick a profile by name, or let the identifier pick it. The extractor never takes a path to a profile.

## Install

```powershell
uv tool install --editable .
```

You need Python 3.12 or newer. Scanned PDFs also need Tesseract with the `ara` and `eng` language packs. Tesseract is a separate system program, not a Python package, so it has to be installed on the machine and on `PATH`. PDFs that already have a text layer don't need it.

## Quick start

```powershell
unpdf-extractor pull invoice
unpdf-extractor identify C:\docs
unpdf-extractor run --type invoice C:\docs
unpdf-extractor check --type invoice C:\docs
```

- `pull` downloads one profile, verifies its SHA-256 and contract, and caches it.
- `identify` reads the PDFs and prints the profile each one would get. It writes nothing.
- `run` reads every `*.pdf` in the folder, extracts the fields the profile describes, and writes the database.
- `check` runs the field rules again on a database you already have. It doesn't open the PDFs and writes no evidence.

If the profile is already in your `profiles` folder, skip `pull`.

To handle a whole family of profiles at once, use `--family` instead of `--type`:

```powershell
unpdf-extractor run --family invoice C:\docs
unpdf-extractor check --family invoice C:\docs
```

Help works offline. `help run` explains one command, `help all` prints every topic, and there's one page per profile. The topics are `profiles`, `registry`, `extraction`, `review`, `contract`, `quarantine`, and `exit-codes`.

## Options

| Option | What it does |
| ------ | ------------ |
| `folder` | The folder with the PDFs. Defaults to the current folder |
| `--type NAME` | Use one profile |
| `--family NAME` | Send each PDF to the family member that matches it |
| `--db PATH` | The database file. Defaults to `<name>.db` in the PDF folder. An automatic run writes `documents.db` |
| `--work PATH` | Where the evidence goes. `run` only. Defaults to `.unpdf` next to the database |
| `--no-color` | Plain text output |

`--type` and `--family` are alternatives. If you give neither, the identifier tries every approved profile and only saves a PDF when exactly one fits.

### Automatic runs

A run with no `--type` or `--family` uses every approved profile on the machine. For each PDF it checks each contract and match rule:

- exactly one fits: the PDF is extracted with that profile.
- none fits: the PDF is quarantined with `no profile subtype matched`.
- more than one fits: the PDF is quarantined as ambiguous, so tighten a match rule.

Use `identify` to see the same decision before writing anything:

```powershell
unpdf-extractor identify C:\docs
```

```text
identify  a.pdf: invoice
identify  b.pdf: none (no profile subtype matched)
identify  c.pdf: ambiguous (matched more than one profile: invoice, invoice-copy)
```

Exit code 0 means every PDF matched one profile, 4 means at least one did not, and 3 means at least one could not be read. If both happen, 3 wins. `identify` never writes a database or evidence.

### How a family run works

The extractor reads each PDF once, then tries every family member's contract and `match` rule to find the right one. It never looks at file names. If registry credentials are set, the registry supplies the full member list, so a half-cached family isn't treated as complete.

## What you get

```text
<name>.db    The SQLite database. A type run writes <name>.db, a family run writes <family>.db
documents.db The database for a run with no --type or --family
.unpdf/      The profile snapshot, extraction evidence, and quarantine records
```

Both are created next to the database, which defaults to the PDF folder. Use `--db` and `--work` to move them. Neither may point inside the tool's own folder. Your PDFs are never moved or changed.

The database has:

- `docs`: one row per document.
- `extracted_fields`: one row per field.
- `quarantine`: the PDFs that were rejected.
- `review`: a view of every flagged field.

## Profiles

The extractor looks for local profiles in:

```text
profiles/<name>/profile.json
```

That path is relative to the current folder, unless `UNPDF_PROFILES` points somewhere else. Profiles downloaded from the registry are cached, so they don't need a local folder.

Only approved profiles work. An unapproved one exits with code 4.

### Fallback boxes

A field can have an optional `fallback_box` next to its `box`. The extractor reads it only when the first box finds no value. That covers forms that leave a labelled row blank and print the value one row lower. The stored `bbox` is always the box that produced the value, so the evidence points at the words that were actually read.

### Modes

A field's `mode` decides how much of its box becomes the value:

- `line` keeps the longest line.
- `multi` joins every line.

If a value wraps onto a second line, use `multi` and a box tall enough for both lines. With `line`, the second line is dropped without any warning.

## Registry

Give the extractor both credential values through environment variables:

```powershell
$env:UNPDF_REGISTRY_URL = '<registry base URL>'
$env:UNPDF_REGISTRY_TOKEN = 'unpdf_...'
```

Or put them in a credentials file, with the same two values:

```text
%APPDATA%\unpdf\credentials.json        Windows
~/.config/unpdf/credentials.json        other systems
```

```json
{"url": "<registry base URL>", "token": "unpdf_..."}
```

The URL and the token must come from the same place. Setting only one environment variable is an error, and an environment URL is never paired with the token from the file. The URL must be HTTPS. Plain HTTP is allowed only for localhost.

Then pull a profile:

```powershell
unpdf-extractor pull invoice
unpdf-extractor pull invoice --version 1.0.0
```

Pulled profiles are cached at:

```text
%LOCALAPPDATA%\unpdf\profiles\<name>\<version>\profile.json
```

Cached profiles work offline. The cache keeps one version per profile, so pulling a different version replaces the cached one. Set `UNPDF_PROFILE_CACHE` to use another cache folder.

This package stores no registry URL, token, or profile data.

## Results

Every field ends up with one of three statuses:

```text
accepted   present, and passed its check
review     present but failed a check, or a required field is empty
missing    absent: optional, or genuinely blank
```

If a PDF fails the contract check, it's quarantined with a reason, and the rest of the batch keeps going.

Each run ends with a summary:

```text
run: 3 added, 1 skipped, 0 failed
database: 4 document(s) | 57 accepted, 2 review, 5 missing (optional)

review queue:
  invoice.pdf | number | not a number
```

`skipped` counts PDFs that are already in the database, and the same content showing up twice in one batch. `missing` fields are optional. A blank required field goes to review.

## Exit codes

| Code | Meaning |
| ---- | ------- |
| 0 | Clean: every field accepted |
| 1 | Nothing to do, or a usage or setup mistake |
| 2 | Review needed: at least one field needs review |
| 3 | At least one PDF couldn't be read, or the registry failed |
| 4 | A PDF was quarantined, the profile isn't approved, or `identify` found no single match |

If more than one applies, 3 wins over 4, and 4 wins over 2. Documents that passed are still saved. `unpdf-extractor help exit-codes` shows the same table offline.

### Messages

| Message | Code | What to do first |
| ------- | ---- | ---------------- |
| `Unknown profile 'x'.` | 1 | Check the name, or set registry credentials so it can be downloaded |
| `No PDFs in ...` | 1 | Point the command at the folder that holds the PDFs |
| `Folder not found: ...` | 1 | Fix the path. Nothing was read |
| `No database at ...` | 1 | `check` needs a database from an earlier `run` |
| `No approved profiles found...` | 1 | Add a profile to `profiles/`, or pull one |
| `Family 'x' has N approved profile(s)...` | 1 | Pull the missing members |
| `Duplicate PDF file names in ...` | 1 | Rename the files. Nothing was read |
| `Profile 'x' is not approved.` | 4 | Approve it, or pick a different profile |
| `quarantine <file>: expected N page(s), found M` | 4 | The folder and the profile disagree about the form |
| `quarantine <file>: no profile subtype matched` | 4 | No profile describes this document |
| `quarantine <file>: matched more than one profile` | 4 | Tighten a match rule |
| `identify <file>: none (...)` | 4 | No profile describes this document |
| `identify <file>: ambiguous (...)` | 4 | Tighten a match rule; more than one profile fits |
| `Registry rejected the token...` | 3 | Check the token, or issue a new one |
| `Profile hash mismatch...` | 3 | Pull again, and don't use the file you got |

## Environment variables

| Name | What it does |
| ---- | ------------ |
| `UNPDF_PROFILES` | Profiles folder. Default `./profiles` |
| `UNPDF_REGISTRY_URL` | Registry base URL |
| `UNPDF_REGISTRY_TOKEN` | This machine's read token |
| `UNPDF_PROFILE_CACHE` | Profile cache folder |
| `NO_COLOR` | Plain text output, same as `--no-color` |

## Tests

```powershell
uv run python -m unittest discover -s tests -v
uvx ruff@0.17.2 check --select E9,F src tests
```
