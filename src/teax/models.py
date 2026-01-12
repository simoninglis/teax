"""Pydantic models for Gitea API responses."""

from pydantic import BaseModel, Field, SecretStr


class TeaLogin(BaseModel):
    """tea CLI login configuration."""

    name: str
    url: str
    token: SecretStr
    default: bool = False
    user: str = ""


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
    labels: list["Label"] = Field(default_factory=list)
    assignees: list["User"] = Field(default_factory=list)
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
