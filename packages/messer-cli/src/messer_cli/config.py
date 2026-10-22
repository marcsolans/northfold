"""``~/.messer/config`` and ``~/.messer/credentials`` (INI, AWS-style profiles: ``[default]``, ``[profile dev]``).

The format is shared with the inherited Zig CLI and with the engine (``messer.state.config_loader``), so a
project run with ``messer start`` or deployed code picks up the same profile:

    ~/.messer/config                 ~/.messer/credentials (mode 600)
    [default]                        [default]
    base_url = https://api.x/api/v1  api_key = msr_…
    org = <organization id>
    model = anthropic/…              (default model for `messer create`, from the platform's Standard tier)
"""

from __future__ import annotations

import configparser
import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PROFILE = "default"
API_PREFIX = "/api/v1"


class ConfigError(Exception):
    """A missing or invalid setting; the message tells the user what to run."""


def config_dir() -> Path:
    override = os.environ.get("MESSER_CONFIG_DIR")
    return Path(override).expanduser() if override else Path.home() / ".messer"


def section_name(profile: str) -> str:
    return DEFAULT_PROFILE if profile == DEFAULT_PROFILE else f"profile {profile}"


def normalize_base_url(raw: str) -> str:
    """API root or base URL → base URL ending in ``/api/v1`` (``http`` only for localhost)."""
    url = raw.strip().rstrip("/")
    if not url.startswith(("https://", "http://")):
        url = f"https://{url}"
    if url.startswith("http://"):
        host = url[len("http://") :].split("/", 1)[0].split(":", 1)[0]
        if host not in ("localhost", "127.0.0.1", "[::1]", "::1") and not os.environ.get("MESSER_ALLOW_HTTP"):
            raise ConfigError("Usa https:// (http solo para localhost) para no enviar tu API key sin cifrar")
    if not url.endswith(API_PREFIX):
        url = f"{url}{API_PREFIX}"
    return url


def api_root(base_url: str) -> str:
    return base_url[: -len(API_PREFIX)] if base_url.endswith(API_PREFIX) else base_url


def _read(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=None)
    if path.is_file():
        try:
            parser.read(path, encoding="utf-8")
        except configparser.Error as exc:
            raise ConfigError(f"No se puede leer {path}: {exc}") from exc
    return parser


def _write(path: Path, parser: configparser.ConfigParser, *, private: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600 if private else 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        parser.write(fh)
    os.replace(tmp, path)


@dataclass(slots=True)
class Profile:
    name: str
    base_url: str | None = None
    org: str | None = None
    api_key: str | None = None
    model: str | None = None

    @property
    def api_url(self) -> str | None:
        return api_root(self.base_url) if self.base_url else None


def load_profile(name: str | None = None) -> Profile:
    profile = name or os.environ.get("MESSER_PROFILE") or DEFAULT_PROFILE
    section = section_name(profile)
    cfg = _read(config_dir() / "config")
    creds = _read(config_dir() / "credentials")
    out = Profile(name=profile)
    if cfg.has_section(section):
        out.base_url = cfg.get(section, "base_url", fallback=None) or None
        out.org = cfg.get(section, "org", fallback=None) or None
        out.model = cfg.get(section, "model", fallback=None) or None
    if creds.has_section(section):
        out.api_key = creds.get(section, "api_key", fallback=None) or None
    return out


def resolve(
    profile: str | None = None, *, api_url: str | None = None, api_key: str | None = None, org: str | None = None
) -> Profile:
    """Flags > environment (``MESSER_API_URL``, ``MESSER_API_KEY``, ``MESSER_ORG_ID``) > profile files."""
    loaded = load_profile(profile)
    url = api_url or os.environ.get("MESSER_API_URL")
    if url:
        loaded.base_url = normalize_base_url(url)
    loaded.api_key = api_key or os.environ.get("MESSER_API_KEY") or loaded.api_key
    loaded.org = org or os.environ.get("MESSER_ORG_ID") or loaded.org
    return loaded


def require(profile: Profile) -> tuple[str, str]:
    if not profile.base_url:
        raise ConfigError("Messer no está configurado: ejecuta `messer configure`")
    if not profile.api_key:
        raise ConfigError(f"No hay API key para el perfil «{profile.name}»: ejecuta `messer configure`")
    return profile.base_url, profile.api_key


def save_profile(profile: Profile) -> None:
    section = section_name(profile.name)
    cfg_path, creds_path = config_dir() / "config", config_dir() / "credentials"
    cfg, creds = _read(cfg_path), _read(creds_path)
    if not cfg.has_section(section):
        cfg.add_section(section)
    for key in ("base_url", "org", "model"):
        value = getattr(profile, key)
        if value:
            cfg.set(section, key, value)
    _write(cfg_path, cfg, private=False)
    if profile.api_key:
        if not creds.has_section(section):
            creds.add_section(section)
        creds.set(section, "api_key", profile.api_key)
        _write(creds_path, creds, private=True)


def profiles() -> list[Profile]:
    cfg = _read(config_dir() / "config")
    names: list[str] = []
    for section in cfg.sections():
        if section == DEFAULT_PROFILE:
            names.append(DEFAULT_PROFILE)
        elif section.startswith("profile "):
            names.append(section[len("profile ") :].strip())
    return [load_profile(n) for n in names]
