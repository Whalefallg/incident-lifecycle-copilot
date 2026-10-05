"""Validated, static IncidentBench scenario schema."""

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, model_validator


Category = Literal[
    "basic", "retrieval", "suspend_resume", "idempotency",
    "concurrency", "degraded", "postmortem",
]


class ScenarioStep(BaseModel):
    action: str
    request_id: str | None = None
    content: str | None = None
    state: str | None = None
    event_type: str | None = None
    document_ids: list[str] = Field(default_factory=list)
    facts: dict[str, Any] = Field(default_factory=dict)
    failure: str | None = None


class FactExpectation(BaseModel):
    id: str
    any_of: list[str]


class ScenarioExpectations(BaseModel):
    final_state: str | None = None
    required_states: list[str] = Field(default_factory=list)
    required_event_types: list[str] = Field(default_factory=list)
    forbidden_event_types: list[str] = Field(default_factory=list)
    required_document_ids: list[str] = Field(default_factory=list)
    required_facts: list[FactExpectation] = Field(default_factory=list)
    forbidden_claims: list[str] = Field(default_factory=list)
    duplicate_event_count: int | None = None
    idempotency_required: bool = False
    mismatch_rejected: bool = False
    stale_write_rejected: bool = False
    degraded_outcome: Literal["surfaced", "fallback", "skipped"] | None = None


class IncidentScenario(BaseModel):
    id: str
    title: str
    category: Category
    initial_state: dict[str, Any] = Field(default_factory=dict)
    steps: list[ScenarioStep]
    expectations: ScenarioExpectations
    live_mcp: bool = False

    @model_validator(mode="after")
    def validate_steps(self) -> "IncidentScenario":
        if not self.steps:
            raise ValueError("scenario must have at least one step")
        return self


def load_scenarios(dataset: Path) -> list[IncidentScenario]:
    scenario_dir = dataset / "scenarios"
    rows: list[IncidentScenario] = []
    for path in sorted(scenario_dir.glob("*.yaml")):
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        entries = payload if isinstance(payload, list) else [payload]
        rows.extend(IncidentScenario.model_validate(item) for item in entries)
    ids = [row.id for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("scenario IDs must be unique")
    return rows
