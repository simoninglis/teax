"""Pydantic models for Gitea API responses."""

from pydantic import AliasChoices, BaseModel, Field, SecretStr, field_validator


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


class Secret(BaseModel):
    """Gitea Actions secret (metadata only - values are never returned)."""

    name: str
    created_at: str = ""


class Variable(BaseModel):
    """Gitea Actions variable."""

    name: str
    data: str = Field(
        validation_alias=AliasChoices("data", "value")
    )  # The variable value (Gitea uses "data", but accept "value" for robustness)
    owner_id: int = 0
    repo_id: int = 0
    description: str = ""


class Workflow(BaseModel):
    """Gitea Actions workflow."""

    id: str  # Gitea uses string ID (typically the file path)
    name: str
    path: str
    state: str  # active, disabled_fork, disabled_inactivity, disabled_manually, unknown
    created_at: str | None = None
    updated_at: str | None = None

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def normalize_empty_timestamp(cls, v: str | None) -> str | None:
        """Normalize empty string timestamps to None."""
        if v == "":
            return None
        return v


class WorkflowStep(BaseModel):
    """Gitea Actions workflow step."""

    number: int
    name: str
    status: str  # queued, in_progress, completed
    conclusion: str | None = None  # success, failure, cancelled, skipped
    started_at: str | None = None
    completed_at: str | None = None

    @field_validator("started_at", "completed_at", mode="before")
    @classmethod
    def normalize_empty_timestamp(cls, v: str | None) -> str | None:
        """Normalize empty string timestamps to None."""
        if v == "":
            return None
        return v


class WorkflowJob(BaseModel):
    """Gitea Actions workflow job."""

    id: int
    run_id: int
    name: str
    status: str  # queued, in_progress, completed, waiting
    conclusion: str | None = None  # success, failure, cancelled, skipped
    started_at: str | None = None
    completed_at: str | None = None
    created_at: str | None = None
    head_sha: str = ""
    head_branch: str = ""
    runner_id: int | None = None
    runner_name: str | None = None
    labels: list[str] = Field(default_factory=list)
    steps: list[WorkflowStep] = Field(default_factory=list)
    html_url: str = ""
    run_url: str = ""

    @field_validator("steps", mode="before")
    @classmethod
    def normalize_steps(cls, v: list[WorkflowStep] | None) -> list[WorkflowStep]:
        """Convert null or missing steps to empty list."""
        return v if v is not None else []

    @field_validator("started_at", "completed_at", "created_at", mode="before")
    @classmethod
    def normalize_empty_timestamp(cls, v: str | None) -> str | None:
        """Normalize empty string timestamps to None."""
        if v == "":
            return None
        return v


class WorkflowRun(BaseModel):
    """Gitea Actions workflow run."""

    id: int
    run_number: int
    run_attempt: int = 1
    status: str  # queued, in_progress, completed, waiting
    conclusion: str | None = None  # success, failure, cancelled, skipped
    head_sha: str
    head_branch: str = ""  # May be empty for workflow_dispatch events
    event: str  # push, pull_request, workflow_dispatch, schedule
    display_title: str = ""
    path: str  # workflow file path
    started_at: str | None = None
    completed_at: str | None = None
    html_url: str = ""
    url: str = ""
    repository_id: int = 0
    actor: User | None = None
    trigger_actor: User | None = None

    @field_validator("started_at", "completed_at", mode="before")
    @classmethod
    def normalize_empty_timestamp(cls, v: str | None) -> str | None:
        """Normalize empty string timestamps to None."""
        if v == "":
            return None
        return v
