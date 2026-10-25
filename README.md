# unpdf-extractor

Deterministic PDF-to-SQLite extraction using approved profiles.

No LLM or network calls at runtime. Tesseract with `ara` and `eng` data is used for scanned PDFs.

## Install locally

```powershell
uv tool install --editable C:\Users\Mohammed\projects\unpdf\unpdf-extractor
```

## Profiles

Profiles are external data. Set:

```powershell
$env:UNPDF_PROFILES = 'C:\Users\Mohammed\projects\unpdf\profiles'
```

## Commands

```powershell
unpdf-extractor run --fasah C:\docs
unpdf-extractor run --type fasah-import C:\docs
unpdf-extractor check --fasah C:\docs
unpdf-extractor rebuild --fasah C:\docs
```

Profile families are selected by content using the profile's `match` rule. No filename matching is used.

## Tests

```powershell
uv run python -m unittest discover -s tests -v
```
