"""Fail-closed runtime configuration. No credentials in environment values."""

import os
import re
import stat
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCOPES = frozenset(
    {
        "ats:read",
        "ats:import",
        "ats:profile:write",
        "ats:analyze",
        "ats:tailor",
        "ats:review",
        "ats:approve",
        "ats:export",
        "discovery:admin",
    }
)
COOKIE = "__Host-job-agent-session"
ATS_URL = "https://ats-service:8766"


def private_file(path: Path, maximum: int = 65536) -> bytes:
    if not path.is_absolute():
        raise ValueError("Runtime files require absolute paths")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as file:
        info = os.fstat(file.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_mode & 0o077
            or info.st_uid not in (0, os.geteuid())
        ):
            raise ValueError("Unsafe runtime file permissions")
        data = file.read(maximum + 1)
        if not data or len(data) > maximum:
            raise ValueError("Invalid runtime file size")
        return data


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    origin: str
    operator_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    password_file: Path
    token_file: Path
    admin_token_file: Path | None = None
    ca_file: Path
    cert_file: Path
    key_file: Path
    database: Path = Path("/data/sessions.db")
    scopes: frozenset[str] = SCOPES
    absolute_seconds: int = Field(default=28800, ge=60, le=604800)
    idle_seconds: int = Field(default=1800, ge=30, le=86400)
    max_sessions: int = Field(default=3, ge=1, le=20)
    login_attempts: int = Field(default=5, ge=1, le=100)
    login_window: int = Field(default=300, ge=30, le=3600)
    max_upload: int = Field(default=5 * 1024 * 1024, ge=1024, le=5 * 1024 * 1024)
    max_response: int = Field(default=32 * 1024 * 1024, ge=1024, le=64 * 1024 * 1024)

    @model_validator(mode="after")
    def validate_runtime(self):
        parsed = urlsplit(self.origin)
        _ = parsed.port
        if any(c.isspace() for c in self.origin):
            raise ValueError("Invalid origin")
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path
            or parsed.query
            or parsed.fragment
            or self.origin.endswith("/")
        ):
            raise ValueError("Configure an exact HTTPS origin without trailing slash")
        if not self.scopes <= SCOPES or self.idle_seconds > self.absolute_seconds:
            raise ValueError("Invalid scopes or session lifetimes")
        if not self.database.is_absolute():
            raise ValueError("Use an absolute database path")
        return self

    @classmethod
    def environment(cls):
        names = cls.model_fields
        values = {
            name: os.environ["BFF_" + name.upper()]
            for name in names
            if "BFF_" + name.upper() in os.environ
        }
        if "scopes" in values:
            values["scopes"] = frozenset(values["scopes"].split(","))
        return cls(**values)


def load_password(settings: Settings) -> str:
    value = private_file(settings.password_file, 1024).decode("ascii").strip()
    if not re.fullmatch(
        r"\$argon2id\$v=19\$m=65536,t=3,p=4\$[A-Za-z0-9+/]+\$[A-Za-z0-9+/]+", value
    ):
        raise ValueError("Provision an Argon2id hash with the BFF operator command")
    return value


def load_token(settings: Settings) -> str:
    value = private_file(settings.token_file, 1024).decode("ascii").strip()
    if not re.fullmatch(r"[A-Za-z0-9._~-]{32,512}", value):
        raise ValueError("Invalid ATS token file")
    return value


def load_admin_token(settings: Settings) -> str:
    if settings.admin_token_file is None:
        raise ValueError("Administrative service credential is not configured")
    value = private_file(settings.admin_token_file, 1024).decode("ascii").strip()
    if not re.fullmatch(r"[A-Za-z0-9._~-]{43,512}", value):
        raise ValueError("Invalid administrative service credential")
    return value
