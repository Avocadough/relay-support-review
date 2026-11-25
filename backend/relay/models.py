"""Bounded mutation inputs; customer text and decisions never share a schema."""
import re
from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator


Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
Revision = Annotated[int, Field(strict=True, ge=0)]


class Mutation(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Facts(Mutation):
    plan: Literal["monthly", "annual"] | None = None
    charged_on: date | None = None
    requested_on: date | None = None
    usage_count: Annotated[int, Field(strict=True, ge=0, le=1_000_000_000)] | None = None
    reason: Literal["refund", "duplicate_charge", "cancel"] | None = None

    @field_validator("charged_on", "requested_on", mode="before")
    @classmethod
    def strict_date(cls, value):
        if value is not None and (not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)):
            raise ValueError("Use an ISO date in YYYY-MM-DD format.")
        return value

    @model_validator(mode="after")
    def chronological_dates(self):
        if self.charged_on and self.requested_on and self.charged_on > self.requested_on:
            raise ValueError("Charge date cannot be after the request date.")
        return self


class TicketInput(Mutation):
    customer: Name
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
    body: Text
    facts: Facts


class DraftInput(Mutation):
    mode: Literal["template", "ai"]
    expected_revision: Revision


class ReviewInput(Mutation):
    draft_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    expected_revision: Revision
    action: Literal["approve", "reject"]
    body: Text
    note: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
    reviewer: Name
