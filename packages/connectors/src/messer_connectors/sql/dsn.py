"""Connection-string parsing for PostgreSQL, MySQL/MariaDB and SQL Server."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import parse_qs, unquote, urlsplit

Dialect = Literal["postgresql", "mysql", "sqlserver"]

DEFAULT_PORTS: dict[str, int] = {"postgresql": 5432, "mysql": 3306, "sqlserver": 1433}


class DsnError(ValueError):
    pass


@dataclass(slots=True)
class ParsedDsn:
    dialect: Dialect
    host: str
    port: int
    database: str
    user: str
    password: str = field(repr=False)
    options: dict[str, str] = field(default_factory=dict)

    def redacted(self) -> str:
        return f"{self.dialect}://{self.user}:***@{self.host}:{self.port}/{self.database}"


_SCHEMES: dict[str, Dialect] = {
    "postgres": "postgresql",
    "postgresql": "postgresql",
    "postgresql+psycopg": "postgresql",
    "postgresql+asyncpg": "postgresql",
    "mysql": "mysql",
    "mysql+pymysql": "mysql",
    "mariadb": "mysql",
    "mssql": "sqlserver",
    "mssql+pytds": "sqlserver",
    "mssql+pyodbc": "sqlserver",
    "sqlserver": "sqlserver",
}


def parse_dsn(dsn: str, dialect: Dialect) -> ParsedDsn:
    dsn = dsn.strip()
    if not dsn:
        raise DsnError("La cadena de conexión está vacía")
    if "://" in dsn:
        return _parse_url(dsn, dialect)
    if dialect == "postgresql":
        return _parse_libpq(dsn)
    if dialect == "sqlserver" or ";" in dsn:
        return _parse_ado(dsn, dialect)
    raise DsnError("Formato de cadena de conexión no reconocido")


def _parse_url(dsn: str, dialect: Dialect) -> ParsedDsn:
    parts = urlsplit(dsn)
    scheme = parts.scheme.lower()
    found = _SCHEMES.get(scheme)
    if found is None:
        raise DsnError(f"Esquema no admitido: {scheme}")
    if found != dialect:
        raise DsnError(f"La cadena de conexión es de {found}, no de {dialect}")
    if not parts.hostname:
        raise DsnError("La cadena de conexión no indica el servidor")
    options = {k: v[-1] for k, v in parse_qs(parts.query).items()}
    database = unquote(parts.path.lstrip("/")) or options.pop("database", "") or options.pop("dbname", "")
    return ParsedDsn(
        dialect=dialect,
        host=parts.hostname,
        port=parts.port or DEFAULT_PORTS[dialect],
        database=database,
        user=unquote(parts.username or ""),
        password=unquote(parts.password or ""),
        options=options,
    )


def _parse_libpq(dsn: str) -> ParsedDsn:
    values: dict[str, str] = {}
    for token in _split_libpq(dsn):
        if "=" not in token:
            raise DsnError("Formato clave=valor no válido")
        key, _, value = token.partition("=")
        values[key.strip().lower()] = value.strip().strip("'")
    host = values.pop("host", "") or values.pop("hostaddr", "")
    if not host:
        raise DsnError("La cadena de conexión no indica el servidor")
    return ParsedDsn(
        dialect="postgresql",
        host=host,
        port=int(values.pop("port", DEFAULT_PORTS["postgresql"])),
        database=values.pop("dbname", ""),
        user=values.pop("user", ""),
        password=values.pop("password", ""),
        options=values,
    )


def _split_libpq(dsn: str) -> list[str]:
    tokens: list[str] = []
    current: list[str] = []
    quoted = False
    for ch in dsn:
        if ch == "'":
            quoted = not quoted
            current.append(ch)
        elif ch.isspace() and not quoted:
            if current:
                tokens.append("".join(current))
                current = []
        else:
            current.append(ch)
    if current:
        tokens.append("".join(current))
    return tokens


_ADO_KEYS = {
    "server": "host",
    "data source": "host",
    "address": "host",
    "addr": "host",
    "network address": "host",
    "database": "database",
    "initial catalog": "database",
    "user id": "user",
    "uid": "user",
    "user": "user",
    "password": "password",
    "pwd": "password",
}


def _parse_ado(dsn: str, dialect: Dialect) -> ParsedDsn:
    values: dict[str, str] = {}
    options: dict[str, str] = {}
    for part in dsn.split(";"):
        if not part.strip():
            continue
        if "=" not in part:
            raise DsnError("Formato clave=valor no válido")
        key, _, value = part.partition("=")
        norm = key.strip().lower()
        target = _ADO_KEYS.get(norm)
        if target:
            values[target] = value.strip()
        else:
            options[norm.replace(" ", "_")] = value.strip()
    host = values.get("host", "")
    if host.lower().startswith("tcp:"):
        host = host[4:]
    port = DEFAULT_PORTS[dialect]
    if "," in host:
        host, _, raw_port = host.partition(",")
        port = int(raw_port)
    elif ":" in host and dialect == "mysql":
        host, _, raw_port = host.partition(":")
        port = int(raw_port)
    if "\\" in host:
        host = host.split("\\", 1)[0]  # named instances need the SQL Browser; the port must be explicit
    if not host:
        raise DsnError("La cadena de conexión no indica el servidor")
    if "port" in options:
        port = int(options.pop("port"))
    return ParsedDsn(
        dialect=dialect,
        host=host,
        port=port,
        database=values.get("database", ""),
        user=values.get("user", ""),
        password=values.get("password", ""),
        options=options,
    )


def truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes", "on", "require", "required", "mandatory", "strict")
