# unpdf-extractor

Deterministic PDF-to-SQLite extraction using approved profiles.

Extraction runs locally. Tesseract with `ara` and `eng` data is used for scanned
PDFs. No LLM is called. The network is used only to download a profile that is
not already cached.

## Install locally

```powershell
uv tool install --editable .
```

## Profiles

A profile is an approved JSON contract. The extractor never accepts an
arbitrary profile path; it selects a profile by name.

Local profiles are read from:

```text
profiles/<name>/profile.json
```

or from the folder in `UNPDF_PROFILES`. Registry profiles are downloaded on
demand and cached.

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

Environment variables win over the file. Tokens are issued by the registry
owner, belong to one person, and can be revoked individually. Never commit a
token.

### Download and cache

```powershell
unpdf-extractor pull fasah-import
unpdf-extractor pull fasah-import --version 1.0.0
```

Each download is verified against the registry SHA-256 before it is used, then
cached at:

```text
%LOCALAPPDATA%\unpdf\profiles\<name>\<version>\profile.json
```

Cached profiles work offline. Delete a version folder to force a fresh download.
Set `UNPDF_PROFILE_CACHE` to use a different cache folder.

## Commands

```powershell
unpdf-extractor run --type fasah-import C:\docs
unpdf-extractor run --family fasah C:\docs
unpdf-extractor run --fasah C:\docs
unpdf-extractor check --family fasah C:\docs
```

- `--type NAME` selects one profile. If it is not local or cached, it is
  downloaded.
- `--family NAME` routes PDFs by content across the family members, downloading
  the family when it is not cached.
- `--fasah` is a shortcut generated from a local or cached family.

Profile families are selected by content using the profile's `match` rule. No
filename matching is used.

## Tests

```powershell
uv run python -m unittest discover -s tests -v
```
