"""Narrow discovery administration contracts; never a general HTTP proxy."""

from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from bff.models import Strict

AdminProvider = Literal[
    "greenhouse",
    "lever",
    "ashby",
    "smartrecruiters",
    "workable",
    "gupy",
    "jobicy",
]
Outcome = Literal["running", "succeeded", "partial", "failed", "interrupted"]


class SourceInput(Strict):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    provider: AdminProvider
    token: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,120}$")
    company: str = Field(min_length=1, max_length=500)
    active: bool = True


class SourcePatch(Strict):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    provider: AdminProvider | None = None
    token: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]{1,120}$")
    company: str | None = Field(default=None, min_length=1, max_length=500)
    active: bool | None = None

    @model_validator(mode="after")
    def has_change(self):
        if not self.model_fields_set or any(
            getattr(self, name) is None for name in self.model_fields_set
        ):
            raise ValueError("Supply a non-null source field")
        return self


class ManagedSource(Strict):
    id: int
    provider: AdminProvider
    token: str
    company: str
    active: bool
    created_at: str
    updated_at: str
    last_collected_at: str | None
    last_result: Outcome | None
    collection_ready: bool = True
    collection_block_reason: str | None = None


class SourcePage(Strict):
    items: list[ManagedSource]
    total: int
    limit: int
    offset: int
    has_next: bool


class ImportResult(Strict):
    created: int
    skipped: int
    configuration_mode: Literal["database"]


class SourceRun(Strict):
    id: int
    run_id: int
    source_id: int | None
    provider: AdminProvider
    company: str
    started_at: str
    finished_at: str | None
    duration_seconds: float | None
    status: Outcome
    received: int
    new_jobs: int
    updated_jobs: int
    duplicates: int
    requests: int
    errors: int


class CollectionRun(Strict):
    id: int
    trigger: Literal["manual", "scheduled"]
    configuration_mode: Literal["legacy", "database"]
    started_at: str
    finished_at: str | None
    duration_seconds: float | None
    status: Outcome
    received: int
    new_jobs: int
    updated_jobs: int
    duplicates: int
    requests: int
    errors: int


class RunDetail(CollectionRun):
    sources: list[SourceRun]
    selected_source_ids: list[int] = Field(default_factory=list)


class CollectionStartRequest(Strict):
    source_ids: list[int] = Field(min_length=1, max_length=210)

    @model_validator(mode="after")
    def unique_positive_source_ids(self):
        if any(value <= 0 for value in self.source_ids) or len(set(self.source_ids)) != len(self.source_ids):
            raise ValueError("Source IDs must be unique positive integers")
        return self


class CollectionAccepted(Strict):
    run_id: int
    status: Literal["running"]
    selected_source_ids: list[int]
    started_at: str


class RunPage(Strict):
    items: list[CollectionRun]
    total: int
    limit: int
    offset: int
    has_next: bool


class CollectionError(Strict):
    id: int
    run_id: int
    source_run_id: int | None
    source_id: int | None
    provider: str | None
    category: str
    retryable: bool
    occurred_at: str


class ErrorPage(Strict):
    items: list[CollectionError]
    total: int
    limit: int
    offset: int
    has_next: bool


class AutomationStatus(Strict):
    configuration_mode: Literal["legacy", "database"]
    scheduler_enabled: bool
    interval_seconds: int
    scheduler_task_running: bool
    scheduler_last_error: str | None
    running: bool
    lease_expires_at: str | None
    next_run_at: str | None
    last_run: CollectionRun | None


class ManualResult(Strict):
    run_id: int
    imported: dict[str, int]
    errors: list[dict[str, str]]
    requests: int
