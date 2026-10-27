"""Fetch approved profiles from the private registry and cache them locally.

The registry URL and token are never part of the package.  They come from the
environment or from a user credentials file:

    %APPDATA%\\unpdf\\credentials.json      (Windows)
    ~/.config/unpdf/credentials.json        (other systems)

The file shape is ``{"url": "https://...", "token": "unpdf_..."}``.  A URL and
token always come from the same place, so a token is never sent to a host it was
not issued for.  Profiles are cached under the user cache folder, so repeat runs
and offline use do not need the network.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlsplit

from .errors import UnpdfError
from .profile import LayoutProfile
from .version import __version__

TIMEOUT = 30
_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")
_VERSION_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._-]*$")
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


@dataclass(frozen=True)
class Credentials:
    url: str
    token: str


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never forward the bearer token to another URL."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def credentials_path() -> Path:
    base = os.environ.get("APPDATA")
    root = Path(base) if base else Path.home() / ".config"
    return root / "unpdf" / "credentials.json"


def _check_registry_url(url: str) -> None:
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
    except ValueError as exc:
        raise UnpdfError(f"Invalid registry URL: {url!r}", exit_code=1) from exc
    if not host:
        raise UnpdfError(f"Invalid registry URL (missing host): {url!r}", exit_code=1)
    if parts.scheme == "https":
        return
    if parts.scheme == "http" and host in _LOCAL_HOSTS:
        return
    raise UnpdfError(
        "Registry URL must use HTTPS. Plain HTTP is only allowed for localhost, "
        f"127.0.0.1, or [::1]: {url!r}",
        exit_code=1,
    )


def secure_url(url: str) -> str:
    """Validate a registry URL and return it without a trailing slash."""
    _check_registry_url(url)
    return url.rstrip("/")


def open_no_redirect(request: urllib.request.Request, timeout: int = TIMEOUT):
    """Open a request without forwarding headers to a redirect target."""
    return _OPENER.open(request, timeout=timeout)


def load_credentials() -> Credentials | None:
    """Return the configured credentials, or None when none are set up."""
    env_url = os.environ.get("UNPDF_REGISTRY_URL", "").strip()
    env_token = os.environ.get("UNPDF_REGISTRY_TOKEN", "").strip()
    if env_url or env_token:
        if not (env_url and env_token):
            raise UnpdfError(
                "Set both UNPDF_REGISTRY_URL and UNPDF_REGISTRY_TOKEN, or neither.",
                exit_code=1,
            )
        return Credentials(secure_url(env_url), env_token)

    path = credentials_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise UnpdfError(f"Cannot read registry credentials {path}: {exc}", exit_code=1) from exc
    if not isinstance(data, dict):
        raise UnpdfError(f"Registry credentials must be a JSON object: {path}", exit_code=1)
    url = str(data.get("url") or "").strip()
    token = str(data.get("token") or "").strip()
    if not url or not token:
        raise UnpdfError(f"Registry credentials need both url and token: {path}", exit_code=1)
    return Credentials(secure_url(url), token)


def require_credentials() -> Credentials:
    credentials = load_credentials()
    if credentials is None:
        raise UnpdfError(
            "No registry credentials. Set UNPDF_REGISTRY_URL and UNPDF_REGISTRY_TOKEN, "
            f'or create {credentials_path()} with {{"url": "...", "token": "..."}}.',
            exit_code=1,
        )
    return credentials


def cache_root() -> Path:
    configured = os.environ.get("UNPDF_PROFILE_CACHE", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else Path.home() / ".cache"
    return (root / "unpdf" / "profiles").resolve()


def _version_key(value: str) -> tuple:
    """Sort versions by number; ``1.0.0`` sorts after ``1.0.0-rc1``."""
    base, _, tag = value.partition("-")
    numbers = [int(part) if part.isdigit() else 0 for part in re.split(r"[._]", base)]
    return numbers, 0 if tag else 1, tag


def cached_profile_paths() -> dict[str, Path]:
    """Return the newest cached profile.json per profile name."""
    root = cache_root()
    found: dict[str, Path] = {}
    if not root.is_dir():
        return found
    for folder in sorted(root.iterdir()):
        if not folder.is_dir() or not _NAME_RE.fullmatch(folder.name):
            continue
        versions = [item for item in folder.iterdir() if (item / "profile.json").is_file()]
        if not versions:
            continue
        latest = max(versions, key=lambda item: _version_key(item.name))
        found[folder.name] = latest / "profile.json"
    return found


def _error_message(exc: urllib.error.HTTPError, url: str) -> str:
    if exc.code in (401, 403):
        return "Registry rejected the token; check the credentials."
    if exc.code == 404:
        return f"Registry has nothing at {url}."
    if 300 <= exc.code < 400:
        return "Registry redirected; use its final URL as UNPDF_REGISTRY_URL."
    try:
        detail = exc.read().decode("utf-8", errors="replace").strip()
    except OSError:
        detail = ""
    if len(detail) > 300:
        detail = detail[:300] + "..."
    return f"Registry error {exc.code}: {detail or exc.reason}"


def _request(url: str, token: str, *, accept: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "authorization": f"Bearer {token}",
            "user-agent": f"unpdf-extractor/{__version__}",
            "accept": accept,
        },
    )
    try:
        with open_no_redirect(request) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raise UnpdfError(_error_message(exc, url), exit_code=3) from exc
    except (urllib.error.URLError, OSError) as exc:
        raise UnpdfError(
            f"Registry request failed: {getattr(exc, 'reason', exc)}", exit_code=3
        ) from exc


def _get_json(url: str, token: str) -> dict:
    raw = _request(url, token, accept="application/json")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise UnpdfError("Registry returned invalid JSON.", exit_code=3) from exc
    if not isinstance(data, dict):
        raise UnpdfError("Registry returned an unexpected response.", exit_code=3)
    return data


def family_members(family: str) -> list[str]:
    """Return the current profile names in one family."""
    if not _NAME_RE.fullmatch(family):
        raise UnpdfError(f"Invalid family name: {family!r}", exit_code=1)
    credentials = require_credentials()
    payload = _get_json(
        f"{credentials.url}/v1/families/{quote(family, safe='')}", credentials.token
    )
    return [
        str(item["name"])
        for item in payload.get("profiles") or []
        if isinstance(item, dict) and item.get("name")
    ]


def _prune_versions(profile_folder: Path, keep: str) -> None:
    for item in profile_folder.iterdir():
        if item.is_dir() and item.name != keep:
            shutil.rmtree(item, ignore_errors=True)


def _cache_bytes(name: str, version: str, body: bytes) -> Path:
    target = cache_root() / name / version / "profile.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(body).hexdigest()
    if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == digest:
        _prune_versions(target.parent.parent, version)
        return target
    handle, temp_path = tempfile.mkstemp(dir=target.parent, prefix=".profile-", suffix=".json")
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(body)
        os.replace(temp_path, target)
    except BaseException:
        Path(temp_path).unlink(missing_ok=True)
        raise
    _prune_versions(target.parent.parent, version)
    return target


def fetch_profile(name: str, version: str | None = None) -> dict:
    """Download, verify, validate, and cache one approved profile."""
    if not _NAME_RE.fullmatch(name):
        raise UnpdfError(f"Invalid profile name: {name!r}", exit_code=1)
    if version is not None and not _VERSION_RE.fullmatch(version):
        raise UnpdfError(f"Invalid profile version: {version!r}", exit_code=1)
    credentials = require_credentials()
    suffix = f"/{quote(version, safe='')}" if version else ""
    metadata = _get_json(
        f"{credentials.url}/v1/profiles/{quote(name, safe='')}{suffix}", credentials.token
    )
    resolved = str(metadata.get("version") or version or "").strip()
    expected = str(metadata.get("sha256") or "").strip()
    if not resolved or not _VERSION_RE.fullmatch(resolved) or not expected:
        raise UnpdfError("Registry profile metadata is incomplete.", exit_code=3)

    body = _request(
        f"{credentials.url}/v1/profiles/{quote(name, safe='')}/{quote(resolved, safe='')}/content",
        credentials.token,
        accept="application/json",
    )
    digest = hashlib.sha256(body).hexdigest()
    if digest != expected:
        raise UnpdfError(
            f"Profile hash mismatch for {name} {resolved}: expected {expected}, got {digest}.",
            exit_code=3,
        )
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise UnpdfError(f"Downloaded profile is not valid JSON: {exc}", exit_code=3) from exc

    contract = LayoutProfile.from_dict(data, None)
    if contract.name != name:
        raise UnpdfError(
            f"Downloaded profile name mismatch: requested {name!r}, got {contract.name!r}.",
            exit_code=3,
        )
    if not contract.approved:
        raise UnpdfError(f"Downloaded profile {name} {resolved} is not approved.", exit_code=3)

    path = _cache_bytes(name, resolved, body)
    return {"name": name, "version": resolved, "sha256": digest, "path": path}
