"""Pydantic models for Gitea API responses."""

from pydantic import BaseModel, Field, SecretStr, field_validator


class TeaLogin(BaseModel):
    """tea CLI login configuration."""

    name: str
    url: str
    token: SecretStr
    default: bool = False
    user: str = ""

    @field_validator("url")
    @classmethod
    def validate_url_scheme(cls, v: str) -> str:
        """Validate URL has http:// or https:// scheme."""
        v = v.strip()
        if not v:
            raise ValueError("URL cannot be empty")
        if not v.startswith(("http://", "https://")):
            raise ValueError("URL must start with http:// or https://")
        return v


class TeaConfig(BaseModel):
    """tea CLI configuration file structure."""

    logins: list[TeaLogin] = Field(default_factory=list)


class Issue(BaseModel):
    """Gitea issue representation."""

    id: int
    number: int
    title: str
    state: str
    body: str = ""
    labels: list["Label"] | None = Field(default_factory=list)
    assignees: list["User"] | None = Field(default_factory=list)
    milestone: "Milestone | None" = None


class Label(BaseModel):
    """Gitea label."""

    id: int
    name: str
    color: str = ""
    description: str = ""


class User(BaseModel):
    """Gitea user."""

    id: int
    login: str
    full_name: str = ""


class Milestone(BaseModel):
    """Gitea milestone."""

    id: int
    title: str
    state: str = "open"


class Dependency(BaseModel):
    """Issue dependency relationship."""

    id: int
    number: int
    title: str
    state: str
    repository: "Repository"


class Repository(BaseModel):
    """Gitea repository reference."""

    id: int
    name: str
    full_name: str
    owner: "User | str | None" = None


class Comment(BaseModel):
    """Gitea issue comment."""

    id: int
    body: str
    user: User
    created_at: str
    updated_at: str = ""


class Runner(BaseModel):
    """Gitea Actions runner."""

    id: int
    name: str
    status: str  # online, offline, idle, active
    busy: bool
    labels: list[str] = Field(default_factory=list)
    version: str = ""


class RegistrationToken(BaseModel):
    """Runner registration token."""

    token: str


class PackageFile(BaseModel):
    """Gitea package file metadata."""

    id: int
    size: int
    name: str
    md5: str = ""
    sha1: str = ""
    sha256: str = ""
    sha512: str = ""


class Package(BaseModel):
    """Gitea package representation."""

    id: int
    owner: User
    name: str
    type: str  # pypi, container, generic, npm, etc.
    version: str
    created_at: str
    html_url: str = ""


class PackageVersion(BaseModel):
    """Gitea package version details."""

    id: int
    version: str
    created_at: str
    html_url: str = ""
